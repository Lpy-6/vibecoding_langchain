"""
Semantic cache backed by SQLite.

Exact key = hash(scope + normalized question + model + prompt version + config
+ KB versions). Fuzzy hit = same scope, same KB versions, unexpired, cosine
similarity >= threshold. Because KB versions are part of the key, any document
ingestion/deletion invalidates stale answers automatically.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import SemanticCache
from app.rag.embeddings import cosine_similarity, decode_vector, encode_vector
from app.rag.prompts import PROMPT_VERSION


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope_key(kb_ids: list[str]) -> str:
    return _sha("|".join(sorted(kb_ids)))


def config_hash() -> str:
    # Bump when retrieval/chunking logic changes so stale answers are ignored.
    pipeline_version = "r4-heading-aware"
    return _sha(
        f"{settings.chat_model}|{settings.embedding_model}|{settings.embedding_dim}|"
        f"{PROMPT_VERSION}|{pipeline_version}|{settings.parent_chunk_size}|"
        f"{settings.child_chunk_size}|{settings.rerank_top_n}"
    )


def cache_key(scope: str, question: str, kb_versions: dict[str, int]) -> str:
    versions = json.dumps({k: str(v) for k, v in sorted(kb_versions.items())}, sort_keys=True)
    return _sha(f"{scope}|{question}|{config_hash()}|{versions}")


async def get_cached(
    db: AsyncSession,
    scope: str,
    question: str,
    query_vector: list[float],
    kb_versions_map: dict[str, int],
) -> dict | None:
    if not settings.cache_enabled:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    versions_json = {k: str(v) for k, v in kb_versions_map.items()}

    exact = await db.scalar(
        select(SemanticCache).where(
            SemanticCache.cache_key == cache_key(scope, question, kb_versions_map),
            SemanticCache.expires_at > now,
        )
    )
    hit = exact
    similarity = 1.0
    if hit is None:
        rows = (
            await db.execute(
                select(SemanticCache)
                .where(
                    SemanticCache.scope_key == scope,
                    SemanticCache.expires_at > now,
                    SemanticCache.prompt_version == PROMPT_VERSION,
                    SemanticCache.config_hash == config_hash(),
                )
                .order_by(SemanticCache.last_hit_at.desc().nullslast())
                .limit(200)
            )
        ).scalars().all()
        q_vec = np.asarray(query_vector, dtype=np.float32)
        best: tuple[float, SemanticCache] | None = None
        for row in rows:
            if row.kb_versions != versions_json:
                continue
            sim = cosine_similarity(decode_vector(row.query_embedding), q_vec)
            if sim >= settings.cache_fuzzy_threshold and (best is None or sim > best[0]):
                best = (sim, row)
        if best:
            similarity, hit = best

    if hit is None:
        return None

    hit.hit_count += 1
    hit.last_hit_at = now
    await db.flush()
    return {
        "answer": hit.answer,
        "citations": hit.citations or [],
        "query_text": hit.query_text,
        "similarity": similarity,
        "cache_key": hit.cache_key,
        "model": hit.model,
    }


async def put_cached(
    db: AsyncSession,
    scope: str,
    question: str,
    query_vector: list[float],
    answer: str,
    citations: list[dict],
    kb_versions_map: dict[str, int],
) -> None:
    if not settings.cache_enabled or not answer.strip():
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    key = cache_key(scope, question, kb_versions_map)
    exists = await db.scalar(select(SemanticCache.id).where(SemanticCache.cache_key == key))
    if exists:
        return
    row = SemanticCache(
        cache_key=key,
        scope_key=scope,
        query_text=question,
        query_embedding=encode_vector(query_vector),
        answer=answer,
        citations=citations,
        kb_versions={k: str(v) for k, v in kb_versions_map.items()},
        model=settings.chat_model,
        prompt_version=PROMPT_VERSION,
        config_hash=config_hash(),
        expires_at=now + timedelta(seconds=settings.cache_ttl_seconds),
    )
    db.add(row)
    await db.flush()


async def purge_expired(db: AsyncSession) -> int:
    result = await db.execute(
        delete(SemanticCache).where(SemanticCache.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None))
    )
    return result.rowcount or 0


async def clear_all(db: AsyncSession) -> int:
    result = await db.execute(delete(SemanticCache))
    return result.rowcount or 0


async def cache_stats(db: AsyncSession) -> dict:
    total = await db.scalar(select(func.count(SemanticCache.id))) or 0
    hits = await db.scalar(select(func.coalesce(func.sum(SemanticCache.hit_count), 0))) or 0
    return {"entries": int(total), "hits": int(hits)}
