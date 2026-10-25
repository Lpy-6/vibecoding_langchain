"""Admin document management + ingestion task progress."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_admin
from app.db.models import Chunk, Document, IngestTask, KnowledgeBase, User, utcnow
from app.db.session import AsyncSessionLocal, get_db
from app.ingest.tasks import task_runner
from app.ingest.vector_index import vector_index_manager
from app.schemas import ChunkOut, DocumentOut, TaskOut, UrlImportIn
from app.services.audit import add_audit
from app.services.kb_stats import recalc_kb_counts
from app.services.storage import delete_file, safe_filename, save_bytes, write_text_snapshot
from app.ingest.parsers import fetch_url

router = APIRouter(prefix="/admin", tags=["documents"])

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _get_kb(db: AsyncSession, kb_id: str) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    return kb


@router.post("/kbs/{kb_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_documents(
    kb_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="请选择文件")
    if len(files) > settings.upload_max_files:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {settings.upload_max_files} 个文件")
    await _get_kb(db, kb_id)

    created: list[dict] = []
    duplicates: list[str] = []
    pending_jobs: list[tuple[str, str]] = []
    for upload in files:
        filename = safe_filename(upload.filename or "file")
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型：{filename}")
        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"文件为空：{filename}")
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"文件超过 {settings.max_upload_mb}MB：{filename}")

        import hashlib

        content_hash = hashlib.sha256(data).hexdigest()
        existing = await db.scalar(
            select(Document.id).where(
                Document.kb_id == kb_id,
                Document.content_hash == content_hash,
                Document.deleted_at.is_(None),
            )
        )
        if existing:
            duplicates.append(filename)
            continue

        path, saved_hash = save_bytes(data, filename)
        doc = Document(
            kb_id=kb_id,
            title=Path(filename).stem,
            source_type="image" if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"} else "file",
            original_filename=filename,
            mime_type=ALLOWED_EXTENSIONS.get(suffix) or upload.content_type,
            size_bytes=len(data),
            storage_path=str(path),
            content_hash=saved_hash or content_hash,
            status="pending",
            created_by=admin.id,
        )
        db.add(doc)
        await db.flush()
        task = IngestTask(document_id=doc.id, kb_id=kb_id, task_type="ingest", max_attempts=settings.ingest_max_attempts)
        db.add(task)
        await db.flush()
        add_audit(db, admin, "document.upload", "document", doc.id, request, {"filename": filename, "kb_id": kb_id})
        created.append({"document": DocumentOut.model_validate(doc).model_dump(), "task": TaskOut.model_validate(task).model_dump()})
        pending_jobs.append((task.id, doc.id))

    kb = await _get_kb(db, kb_id)
    await recalc_kb_counts(db, kb)
    await db.commit()
    for task_id, doc_id in pending_jobs:
        task_runner.submit(task_id, doc_id)
    if duplicates:
        return {"items": created, "duplicates": duplicates, "message": f"跳过重复文件 {len(duplicates)} 个"}
    return {"items": created, "duplicates": [], "message": "已提交解析任务"}


@router.post("/kbs/{kb_id}/documents/url", status_code=status.HTTP_201_CREATED)
async def import_url(
    kb_id: str,
    payload: UrlImportIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    import hashlib

    await _get_kb(db, kb_id)
    try:
        html, final_url = await asyncio.to_thread(fetch_url, payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"网页抓取失败：{exc}") from exc

    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    existing = await db.scalar(
        select(Document.id).where(
            Document.kb_id == kb_id, Document.content_hash == content_hash, Document.deleted_at.is_(None)
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="该网页内容已导入过")

    path, _ = write_text_snapshot(html, ".html")
    title = (payload.title or final_url.split("//")[-1].split("/")[0])[:200]
    doc = Document(
        kb_id=kb_id,
        title=title,
        source_type="url",
        original_filename=None,
        mime_type="text/html",
        size_bytes=len(html.encode("utf-8")),
        storage_path=str(path),
        source_url=final_url,
        content_hash=content_hash,
        status="pending",
        created_by=admin.id,
        parser_meta={"custom_title": bool(payload.title)},
    )
    db.add(doc)
    await db.flush()
    task = IngestTask(document_id=doc.id, kb_id=kb_id, task_type="ingest", max_attempts=settings.ingest_max_attempts)
    db.add(task)
    await db.flush()
    add_audit(db, admin, "document.import_url", "document", doc.id, request, {"url": final_url, "kb_id": kb_id})
    kb = await _get_kb(db, kb_id)
    await recalc_kb_counts(db, kb)
    await db.commit()
    task_runner.submit(task.id, doc.id)
    return {"document": DocumentOut.model_validate(doc), "task": TaskOut.model_validate(task), "message": "已提交解析任务"}


@router.get("/kbs/{kb_id}/documents")
async def list_documents(
    kb_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = None,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_kb(db, kb_id)
    stmt = select(Document).where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
    count_stmt = select(func.count(Document.id)).where(Document.kb_id == kb_id, Document.deleted_at.is_(None))
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
        count_stmt = count_stmt.where(Document.status == status_filter)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Document.title.like(like))
        count_stmt = count_stmt.where(Document.title.like(like))
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {"items": [DocumentOut.model_validate(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, document_id)
    if not doc or doc.deleted_at:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    kb = await _get_kb(db, doc.kb_id)
    path = doc.storage_path
    await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await db.delete(doc)
    await db.flush()
    await recalc_kb_counts(db, kb)
    add_audit(db, admin, "document.delete", "document", document_id, request, {"kb_id": kb.id})
    await db.commit()
    delete_file(path)
    vector_index_manager.invalidate(kb.id)
    return {"ok": True}


@router.post("/documents/{document_id}/reindex")
async def reindex_document(
    document_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if not doc or doc.deleted_at:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.storage_path or not Path(doc.storage_path).is_file():
        raise HTTPException(status_code=400, detail="原始文件已丢失，请重新上传")
    doc.status = "pending"
    doc.error_message = None
    task = IngestTask(
        document_id=doc.id,
        kb_id=doc.kb_id,
        task_type="reindex",
        max_attempts=settings.ingest_max_attempts,
    )
    db.add(task)
    await db.flush()
    add_audit(db, admin, "document.reindex", "document", doc.id, request, {"kb_id": doc.kb_id})
    await db.commit()
    task_runner.submit(task.id, doc.id)
    return {"task": TaskOut.model_validate(task)}


@router.get("/documents/{document_id}/chunks")
async def list_chunks(
    document_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    chunk_type: str | None = None,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Chunk).where(Chunk.document_id == document_id)
    count_stmt = select(func.count(Chunk.id)).where(Chunk.document_id == document_id)
    if chunk_type:
        stmt = stmt.where(Chunk.chunk_type == chunk_type)
        count_stmt = count_stmt.where(Chunk.chunk_type == chunk_type)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Chunk.chunk_type, Chunk.ordinal).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {"items": [ChunkOut.model_validate(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    task = await db.get(IngestTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, _: User = Depends(require_admin)):
    async def gen():
        terminal = {"completed", "failed"}
        for _tick in range(3600):
            async with AsyncSessionLocal() as session:
                task = await session.get(IngestTask, task_id)
                if not task:
                    yield _sse("error", {"message": "任务不存在"})
                    return
                payload = {
                    "id": task.id,
                    "status": task.status,
                    "stage": task.stage,
                    "progress": task.progress,
                    "attempts": task.attempts,
                    "error": task.error,
                }
                yield _sse("progress", payload)
                if task.status in terminal:
                    yield _sse("done", payload)
                    return
            await asyncio.sleep(0.5)
        yield _sse("error", {"message": "进度监听超时"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
