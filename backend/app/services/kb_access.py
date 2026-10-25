"""Knowledge-base visibility and permission helpers."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KBPermission, KnowledgeBase, User


async def visible_kb_ids(db: AsyncSession, user: User) -> list[str]:
    kbs = (await db.execute(select(KnowledgeBase.id, KnowledgeBase.is_public))).all()
    if user.role == "admin":
        return [kb_id for kb_id, _ in kbs]
    granted = set(
        (
            await db.execute(select(KBPermission.kb_id).where(KBPermission.user_id == user.id, KBPermission.can_read.is_(True)))
        ).scalars()
    )
    return [kb_id for kb_id, is_public in kbs if is_public or kb_id in granted]


async def visible_kbs(db: AsyncSession, user: User) -> list[KnowledgeBase]:
    rows = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))).scalars().all()
    if user.role == "admin":
        return list(rows)
    granted = set(
        (
            await db.execute(select(KBPermission.kb_id).where(KBPermission.user_id == user.id, KBPermission.can_read.is_(True)))
        ).scalars()
    )
    return [kb for kb in rows if kb.is_public or kb.id in granted]


async def assert_kb_visible(db: AsyncSession, user: User, kb_id: str) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if user.role == "admin":
        return kb
    if kb.is_public:
        return kb
    granted = await db.scalar(
        select(KBPermission.id).where(
            KBPermission.kb_id == kb_id,
            KBPermission.user_id == user.id,
            KBPermission.can_read.is_(True),
        )
    )
    if not granted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该知识库")
    return kb


async def resolve_query_kbs(db: AsyncSession, user: User, requested: list[str]) -> list[KnowledgeBase]:
    allowed = set(await visible_kb_ids(db, user))
    if requested:
        targets = [kb_id for kb_id in requested if kb_id in allowed]
    else:
        targets = list(allowed)
    if not targets:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有可用的知识库，请联系管理员")
    rows = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(targets)))).scalars().all()
    by_id = {kb.id: kb for kb in rows}
    return [by_id[kb_id] for kb_id in targets if kb_id in by_id]


async def kb_versions(db: AsyncSession, kbs: list[KnowledgeBase]) -> dict[str, int]:
    return {kb.id: kb.version for kb in kbs}
