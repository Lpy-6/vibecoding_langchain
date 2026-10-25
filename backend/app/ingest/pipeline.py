"""
Synchronous ingestion pipeline executed in worker threads.

Stages: parse -> chunk -> embed -> persist. Progress is written to
ingest_tasks so the admin UI can follow it over SSE; document/KB counters and
the KB version are updated in one final transaction, which in turn invalidates
the semantic cache and the in-memory vector index.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.db.models import Chunk, Document, IngestTask, KnowledgeBase, utcnow
from app.db.session import sync_session_scope
from app.ingest.chunker import ChunkDraft, chunk_blocks
from app.ingest.parsers import ParsedDocument, parse_html, parse_image, parse_path
from app.ingest.vector_index import vector_index_manager
from app.rag.embeddings import encode_vector, get_embedding_provider

logger = logging.getLogger(__name__)


def _update_task(task_id: str, **fields) -> None:
    with sync_session_scope() as session:
        task = session.get(IngestTask, task_id)
        if not task:
            return
        for key, value in fields.items():
            setattr(task, key, value)


def _update_document(document_id: str, **fields) -> None:
    with sync_session_scope() as session:
        doc = session.get(Document, document_id)
        if not doc:
            return
        for key, value in fields.items():
            setattr(doc, key, value)


def _load_document(document_id: str) -> dict:
    with sync_session_scope() as session:
        doc = session.get(Document, document_id)
        if not doc:
            raise ValueError("文档不存在")
        return {
            "id": doc.id,
            "kb_id": doc.kb_id,
            "title": doc.title,
            "source_type": doc.source_type,
            "mime_type": doc.mime_type or "",
            "storage_path": doc.storage_path,
            "source_url": doc.source_url,
            "parser_meta": dict(doc.parser_meta or {}),
        }


def _parse(doc: dict) -> ParsedDocument:
    path = Path(doc["storage_path"] or "")
    if not path.is_file():
        raise ValueError("原始文件不存在，无法解析")
    if doc["source_type"] == "url":
        html = path.read_text(encoding="utf-8", errors="replace")
        return parse_html(html, fallback_title=doc["title"])
    if doc["source_type"] == "image":
        return parse_image(path, doc["mime_type"] or "image/png")
    return parse_path(path, doc["mime_type"])


def process_document(document_id: str, task_id: str) -> None:
    doc = _load_document(document_id)

    _update_task(task_id, stage="解析中", progress=5, status="running")
    _update_document(document_id, status="parsing", error_message=None)

    parsed = _parse(doc)
    if doc["source_type"] == "url" and not doc["parser_meta"].get("custom_title") and parsed.title:
        _update_document(document_id, title=parsed.title[:200])
        doc["title"] = parsed.title[:200]
    _update_task(task_id, stage="切分中", progress=20)

    drafts = chunk_blocks(parsed.blocks, doc["title"])
    children = [d for d in drafts if d.chunk_type == "child"]
    if not children:
        raise ValueError("文档切分后没有有效内容")
    _update_task(task_id, stage="向量化中", progress=35)
    _update_document(document_id, status="embedding", parser_meta={**doc["parser_meta"], "stage": "embedding"})

    provider = get_embedding_provider()
    batch_size = settings.embedding_batch_size
    vectors: list[list[float]] = []
    for start in range(0, len(children), batch_size):
        batch = children[start : start + batch_size]
        batch_vectors = provider.embed_texts_sync([c.embedding_text for c in batch])
        vectors.extend(batch_vectors)
        done = min(len(children), start + len(batch))
        progress = 35 + int(50 * done / len(children))
        _update_task(task_id, stage="向量化中", progress=progress)
    if len(vectors) != len(children):
        raise ValueError("向量数量与分块数量不一致")
    for vec in vectors:
        if len(vec) != settings.embedding_dim:
            raise ValueError(f"向量维度 {len(vec)} 与配置 {settings.embedding_dim} 不一致")

    _update_task(task_id, stage="写入知识库", progress=90)
    _update_document(document_id, status="persisting")

    with sync_session_scope() as session:
        session.execute(delete(Chunk).where(Chunk.document_id == document_id))

        parents = [d for d in drafts if d.chunk_type == "parent"]
        parent_rows: list[Chunk] = []
        for draft in parents:
            row = Chunk(
                kb_id=doc["kb_id"],
                document_id=document_id,
                chunk_type="parent",
                ordinal=draft.ordinal,
                content=draft.content,
                content_hash=draft.content_hash,
                token_count=draft.token_count,
                page_no=draft.page_no,
                sheet_name=draft.sheet_name,
                row_start=draft.row_start,
                row_end=draft.row_end,
                heading_path=draft.heading_path,
            )
            session.add(row)
            parent_rows.append(row)
        session.flush()

        for draft, vector in zip(children, vectors):
            parent = parent_rows[draft.parent_index] if draft.parent_index is not None else None
            session.add(
                Chunk(
                    kb_id=doc["kb_id"],
                    document_id=document_id,
                    parent_id=parent.id if parent else None,
                    chunk_type="child",
                    ordinal=draft.ordinal,
                    content=draft.content,
                    content_hash=draft.content_hash,
                    token_count=draft.token_count,
                    page_no=draft.page_no,
                    sheet_name=draft.sheet_name,
                    row_start=draft.row_start,
                    row_end=draft.row_end,
                    heading_path=draft.heading_path,
                    embedding=encode_vector(vector),
                    embedding_dim=len(vector),
                    embedding_model=provider.name,
                )
            )
        session.flush()

        db_doc = session.get(Document, document_id)
        if db_doc:
            db_doc.status = "ready"
            db_doc.error_message = None
            db_doc.page_count = parsed.page_count
            db_doc.ocr_pages = parsed.ocr_pages
            db_doc.chunk_count = len(children)
            db_doc.size_bytes = db_doc.size_bytes or 0
            db_doc.parser_meta = {
                **(db_doc.parser_meta or {}),
                **parsed.meta,
                "stage": "ready",
                "embedding_model": provider.name,
                "percent_ocr": round(parsed.ocr_pages / parsed.page_count, 3) if parsed.page_count else 0,
            }
            db_doc.updated_at = utcnow()
            session.flush()

        kb = session.get(KnowledgeBase, doc["kb_id"])
        if kb:
            kb.version += 1
            kb.embedding_model = provider.name
            kb.embedding_dim = settings.embedding_dim
            kb.doc_count = int(
                session.scalar(
                    select(func.count(Document.id)).where(
                        Document.kb_id == kb.id, Document.status == "ready", Document.deleted_at.is_(None)
                    )
                )
                or 0
            )
            kb.chunk_count = int(
                session.scalar(
                    select(func.count(Chunk.id)).where(Chunk.kb_id == kb.id, Chunk.chunk_type == "child")
                )
                or 0
            )
            kb.updated_at = utcnow()

        task = session.get(IngestTask, task_id)
        if task:
            task.status = "completed"
            task.stage = "完成"
            task.progress = 100
            task.error = None
            task.finished_at = utcnow()

    vector_index_manager.invalidate(doc["kb_id"])
    logger.info("document ingested id=%s chunks=%d", document_id, len(children))
