"""Async helpers for KB counters and versions."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document, KnowledgeBase, utcnow


async def recalc_kb_counts(db: AsyncSession, kb: KnowledgeBase) -> None:
    kb.doc_count = int(
        await db.scalar(
            select(func.count(Document.id)).where(
                Document.kb_id == kb.id, Document.status == "ready", Document.deleted_at.is_(None)
            )
        )
        or 0
    )
    kb.chunk_count = int(
        await db.scalar(select(func.count(Chunk.id)).where(Chunk.kb_id == kb.id, Chunk.chunk_type == "child"))
        or 0
    )
    kb.version += 1
    kb.updated_at = utcnow()
