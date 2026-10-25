"""Admin APIs: KB management, permissions, users, statistics, feedback, audit, cache."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_admin
from app.core.security import hash_password
from app.db.models import (
    AuditLog,
    Chunk,
    Conversation,
    Document,
    Feedback,
    IngestTask,
    KBPermission,
    KnowledgeBase,
    Message,
    RefreshToken,
    SemanticCache,
    User,
    utcnow,
)
from app.db.session import get_db
from app.ingest.vector_index import vector_index_manager
from app.schemas import (
    KBCreate,
    KBOut,
    KBPermissionIn,
    KBUpdate,
    ResetPasswordIn,
    UserAdminUpdate,
    UserOut,
)
from app.services.audit import add_audit
from app.services.cache import cache_stats, clear_all
from app.services.kb_stats import recalc_kb_counts
from app.services.storage import delete_file

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------- knowledge bases ----------------
@router.get("/kbs", response_model=list[KBOut])
async def admin_list_kbs(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))).scalars().all()
    return list(rows)


@router.post("/kbs", response_model=KBOut, status_code=status.HTTP_201_CREATED)
async def create_kb(
    payload: KBCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    exists = await db.scalar(select(KnowledgeBase.id).where(KnowledgeBase.name == payload.name))
    if exists:
        raise HTTPException(status_code=409, detail="知识库名称已存在")
    from app.rag.embeddings import get_embedding_provider

    provider = get_embedding_provider()
    kb = KnowledgeBase(
        name=payload.name.strip(),
        description=payload.description.strip(),
        is_public=payload.is_public,
        embedding_model=provider.name,
        embedding_dim=settings.embedding_dim,
        created_by=admin.id,
    )
    db.add(kb)
    await db.flush()
    add_audit(db, admin, "kb.create", "knowledge_base", kb.id, request, {"name": kb.name})
    await db.commit()
    return kb


@router.patch("/kbs/{kb_id}", response_model=KBOut)
async def update_kb(
    kb_id: str,
    payload: KBUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if payload.name and payload.name != kb.name:
        exists = await db.scalar(select(KnowledgeBase.id).where(KnowledgeBase.name == payload.name))
        if exists:
            raise HTTPException(status_code=409, detail="知识库名称已存在")
        kb.name = payload.name.strip()
    if payload.description is not None:
        kb.description = payload.description.strip()
    if payload.is_public is not None:
        kb.is_public = payload.is_public
    kb.updated_at = utcnow()
    add_audit(db, admin, "kb.update", "knowledge_base", kb.id, request, payload.model_dump(exclude_none=True))
    await db.commit()
    return kb


@router.delete("/kbs/{kb_id}")
async def delete_kb(
    kb_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    docs = (await db.execute(select(Document).where(Document.kb_id == kb_id))).scalars().all()
    paths = [d.storage_path for d in docs]
    await db.execute(delete(Chunk).where(Chunk.kb_id == kb_id))
    await db.execute(delete(IngestTask).where(IngestTask.kb_id == kb_id))
    await db.execute(delete(Document).where(Document.kb_id == kb_id))
    await db.execute(delete(KBPermission).where(KBPermission.kb_id == kb_id))
    await db.execute(delete(SemanticCache))
    await db.delete(kb)
    add_audit(db, admin, "kb.delete", "knowledge_base", kb_id, request, {"name": kb.name})
    await db.commit()
    for path in paths:
        delete_file(path)
    vector_index_manager.invalidate(kb_id)
    return {"ok": True}


@router.get("/kbs/{kb_id}/permissions")
async def get_kb_permissions(
    kb_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    users = (await db.execute(select(User).order_by(User.username))).scalars().all()
    granted = set(
        (await db.execute(select(KBPermission.user_id).where(KBPermission.kb_id == kb_id))).scalars()
    )
    return {
        "kb_id": kb_id,
        "is_public": kb.is_public,
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "is_active": u.is_active,
                "granted": u.id in granted,
            }
            for u in users
        ],
    }


@router.put("/kbs/{kb_id}/permissions")
async def set_kb_permissions(
    kb_id: str,
    payload: KBPermissionIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    await db.execute(delete(KBPermission).where(KBPermission.kb_id == kb_id))
    valid: set[str] = set()
    if payload.user_ids:
        valid = set(
            (await db.execute(select(User.id).where(User.id.in_(payload.user_ids)))).scalars()
        )
        for user_id in payload.user_ids:
            if user_id in valid:
                db.add(KBPermission(kb_id=kb_id, user_id=user_id, can_read=True, granted_by=admin.id))
    add_audit(db, admin, "kb.permissions", "knowledge_base", kb_id, request, {"user_ids": payload.user_ids})
    await db.commit()
    return {"ok": True, "count": len([u for u in payload.user_ids if u in valid])}


# ---------------- users ----------------
@router.get("/users")
async def list_users(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User)
    count_stmt = select(func.count(User.id))
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.username.like(like)) | (User.display_name.like(like)))
        count_stmt = count_stmt.where((User.username.like(like)) | (User.display_name.like(like)))
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return {
        "items": [UserOut.model_validate(u) for u in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    payload: UserAdminUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == admin.id and (
        (payload.is_active is False) or (payload.role is not None and payload.role != "admin")
    ):
        raise HTTPException(status_code=400, detail="不能禁用或降级当前登录的管理员")
    if target.role == "admin" and payload.role == "user":
        admin_count = int(await db.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0)
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="至少保留一个管理员")
    if payload.display_name is not None:
        target.display_name = payload.display_name
    if payload.is_active is not None:
        target.is_active = payload.is_active
        if not payload.is_active:
            target.token_version += 1
            await db.execute(
                delete(RefreshToken).where(RefreshToken.user_id == target.id)
            )
    if payload.role is not None:
        target.role = payload.role
        target.token_version += 1
    add_audit(db, admin, "user.update", "user", target.id, request, payload.model_dump(exclude_none=True))
    await db.commit()
    return target


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    payload: ResetPasswordIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    target.password_hash = hash_password(payload.new_password)
    target.token_version += 1
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == target.id))
    add_audit(db, admin, "user.reset_password", "user", target.id, request)
    await db.commit()
    return {"ok": True, "message": "密码已重置，该用户需重新登录"}


# ---------------- stats ----------------
@router.get("/stats/overview")
async def stats_overview(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    now = utcnow()
    week_ago = now - timedelta(days=6)

    async def count(model, *where):
        return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0) if where else int(
            await db.scalar(select(func.count()).select_from(model)) or 0
        )

    users_total = await count(User)
    users_active = await count(User, User.is_active.is_(True))
    kb_total = await count(KnowledgeBase)
    docs_total = await count(Document, Document.deleted_at.is_(None))
    docs_ready = await count(Document, Document.deleted_at.is_(None), Document.status == "ready")
    docs_failed = await count(Document, Document.deleted_at.is_(None), Document.status == "failed")
    chunks = await count(Chunk, Chunk.chunk_type == "child")
    conversations = await count(Conversation, Conversation.deleted_at.is_(None))
    answers = await count(Message, Message.role == "assistant", Message.status == "complete")
    feedback_up = await count(Feedback, Feedback.rating == 1)
    feedback_down = await count(Feedback, Feedback.rating == -1)
    cache = await cache_stats(db)

    avg_latency = await db.scalar(
        select(func.avg(Message.latency_ms)).where(Message.role == "assistant", Message.latency_ms.is_not(None))
    )

    rows = (
        await db.execute(
            select(Message.created_at).where(Message.role == "user", Message.created_at >= week_ago)
        )
    ).scalars().all()
    daily = []
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).date()
        daily.append({"date": day.isoformat(), "count": sum(1 for ts in rows if ts.date() == day)})

    return {
        "users": {"total": users_total, "active": users_active},
        "kbs": {"total": kb_total},
        "documents": {"total": docs_total, "ready": docs_ready, "failed": docs_failed},
        "chunks": chunks,
        "conversations": conversations,
        "answers": answers,
        "feedback": {"up": feedback_up, "down": feedback_down},
        "cache": cache,
        "avg_latency_ms": int(avg_latency) if avg_latency else 0,
        "daily_questions": daily,
        "llm_mode": settings.effective_llm_mode,
        "vector_index": vector_index_manager.stats(),
    }


@router.get("/stats/qa")
async def qa_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total = int(await db.scalar(select(func.count(Message.id)).where(Message.role == "assistant")) or 0)
    rows = (
        await db.execute(
            select(Message, Conversation, User)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(User, User.id == Conversation.user_id)
            .where(Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    ids = [m.id for m, _, _ in rows]
    feedback_map = {}
    if ids:
        for mid, rating in (
            await db.execute(select(Feedback.message_id, Feedback.rating).where(Feedback.message_id.in_(ids)))
        ).all():
            feedback_map[mid] = rating
    return {
        "items": [
            {
                "message_id": m.id,
                "conversation_id": c.id,
                "conversation_title": c.title,
                "username": u.username,
                "question": None,
                "answer": m.content[:240],
                "status": m.status,
                "latency_ms": m.latency_ms,
                "cache_hit": bool((m.retrieval_meta or {}).get("cache_hit")),
                "retrieval_meta": m.retrieval_meta,
                "feedback": feedback_map.get(m.id),
                "created_at": m.created_at,
            }
            for m, c, u in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/feedback")
async def list_feedback(
    rating: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Feedback, Message, User).join(Message, Message.id == Feedback.message_id).join(
        User, User.id == Feedback.user_id
    )
    count_stmt = select(func.count(Feedback.id))
    if rating in (1, -1):
        stmt = stmt.where(Feedback.rating == rating)
        count_stmt = count_stmt.where(Feedback.rating == rating)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Feedback.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": f.id,
                "rating": f.rating,
                "reason_code": f.reason_code,
                "comment": f.comment,
                "username": u.username,
                "message_id": f.message_id,
                "answer": m.content[:300],
                "created_at": f.created_at,
            }
            for f, m, u in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/audit-logs")
async def audit_logs(
    action: str | None = None,
    actor: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action.like(f"%{action}%"))
        count_stmt = count_stmt.where(AuditLog.action.like(f"%{action}%"))
    if actor:
        stmt = stmt.where(AuditLog.actor_name.like(f"%{actor}%"))
        count_stmt = count_stmt.where(AuditLog.actor_name.like(f"%{actor}%"))
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "actor_name": row.actor_name,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "ip": row.ip,
                "user_agent": row.user_agent,
                "detail": row.detail,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/cache/stats")
async def get_cache_stats(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await cache_stats(db)


@router.delete("/cache")
async def purge_cache(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    removed = await clear_all(db)
    await db.commit()
    return {"ok": True, "removed": removed}


@router.get("/system")
async def system_info(_: User = Depends(require_admin)):
    from app.rag.embeddings import get_embedding_provider
    from app.rag.prompts import PROMPT_VERSION

    provider = get_embedding_provider()
    return {
        "llm_mode": settings.effective_llm_mode,
        "chat_model": settings.chat_model,
        "embedding_provider": provider.name,
        "embedding_dim": settings.embedding_dim,
        "rerank_model": settings.rerank_model,
        "prompt_version": PROMPT_VERSION,
        "vector_index": vector_index_manager.stats(),
        "data_dir": str(settings.data_dir),
    }
