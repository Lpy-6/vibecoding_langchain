"""
Hybrid retrieval, reranking, parent expansion and context assembly.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Chunk, Document, KnowledgeBase
from app.ingest.vector_index import hybrid_search
from app.llm import dashscope
from app.rag.embeddings import approx_token_count, tokenize_query

logger = logging.getLogger(__name__)


@dataclass
class RetrievedSource:
    rank: int
    chunk_id: int
    parent_id: int | None
    document_id: str
    kb_id: str
    doc_title: str
    kb_name: str
    snippet: str
    content: str
    locator: dict
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_citation_payload(self) -> dict:
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "kb_id": self.kb_id,
            "doc_title": self.doc_title,
            "snippet": self.snippet[:500],
            "locator": self.locator,
            "dense_score": round(self.dense_score, 4),
            "sparse_score": round(self.sparse_score, 4),
            "rerank_score": round(self.rerank_score, 4),
        }


def _lexical_score(
    query_tokens: set[str], doc_tokens: list[str], idf: dict[str, float] | None = None
) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    doc_set = set(doc_tokens)
    if idf is None:
        return len(query_tokens & doc_set) / max(1, len(query_tokens))
    matched = sum(idf.get(token, 1.0) for token in query_tokens if token in doc_set)
    total = sum(idf.get(token, 1.0) for token in query_tokens) or 1.0
    return matched / total


def _locator(page_no, sheet_name, row_start, row_end, heading_path) -> dict:
    return {
        "page_no": page_no,
        "sheet_name": sheet_name,
        "row_start": row_start,
        "row_end": row_end,
        "heading_path": heading_path,
    }


async def _rerank_candidates(
    query: str, candidates: list[RetrievedSource], top_n: int
) -> tuple[list[RetrievedSource], bool]:
    degraded = False
    if settings.use_dashscope and candidates:
        try:
            results = await asyncio.wait_for(
                dashscope.rerank(query, [c.snippet for c in candidates], top_n=top_n),
                timeout=12.0,
            )
            score_map = {idx: score for idx, score in results}
            for i, cand in enumerate(candidates):
                cand.rerank_score = score_map.get(i, 0.0)
            ranked = [candidates[i] for i, _ in results if 0 <= i < len(candidates)]
            return ranked[:top_n], degraded
        except Exception as exc:  # noqa: BLE001
            logger.warning("rerank failed, falling back to lexical fusion: %s", exc)
            degraded = True

    query_tokens = set(tokenize_query(query))
    token_lists = [
        tokenize_query(f"{c.doc_title} {c.locator.get('heading_path') or ''} {c.snippet}")
        for c in candidates
    ]
    doc_freq: dict[str, int] = {}
    for tokens in token_lists:
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1
    total_docs = max(1, len(candidates))
    idf = {token: math.log(1 + total_docs / (1 + df)) for token, df in doc_freq.items()}

    max_sparse = max((c.sparse_score for c in candidates), default=1.0) or 1.0
    max_dense = max((c.dense_score for c in candidates), default=1.0) or 1.0
    max_rrf = max((c.rrf_score for c in candidates), default=1.0) or 1.0
    for cand, tokens in zip(candidates, token_lists):
        lexical = _lexical_score(query_tokens, tokens, idf)
        cand.rerank_score = (
            0.45 * (cand.sparse_score / max_sparse)
            + 0.30 * lexical
            + 0.15 * (cand.dense_score / max_dense)
            + 0.10 * (cand.rrf_score / max_rrf)
        )
    candidates.sort(key=lambda c: c.rerank_score, reverse=True)
    return candidates[:top_n], degraded


async def retrieve(
    db: AsyncSession,
    kb_versions: dict[str, int],
    query_text: str,
    query_vector: list[float],
    top_n: int | None = None,
) -> tuple[list[RetrievedSource], dict]:
    top_n = top_n or settings.rerank_top_n
    candidates_raw = await asyncio.to_thread(
        hybrid_search,
        kb_versions,
        query_vector,
        query_text,
        settings.retrieval_top_k_dense,
        settings.retrieval_top_k_sparse,
    )
    meta = {
        "dense_k": settings.retrieval_top_k_dense,
        "sparse_k": settings.retrieval_top_k_sparse,
        "candidates": len(candidates_raw),
        "rerank_degraded": False,
    }
    if not candidates_raw:
        return [], meta

    shortlist = candidates_raw[: settings.retrieval_fuse_k]
    ids = [item["chunk_id"] for item in shortlist]
    rows = (
        await db.execute(
            select(Chunk, Document, KnowledgeBase)
            .join(Document, Document.id == Chunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == Chunk.kb_id)
            .where(Chunk.id.in_(ids), Document.deleted_at.is_(None))
        )
    ).all()
    row_map = {chunk.id: (chunk, doc, kb) for chunk, doc, kb in rows}

    ordered: list[RetrievedSource] = []
    for item in shortlist:
        found = row_map.get(item["chunk_id"])
        if not found:
            continue
        chunk, doc, kb = found
        ordered.append(
            RetrievedSource(
                rank=0,
                chunk_id=chunk.id,
                parent_id=chunk.parent_id,
                document_id=doc.id,
                kb_id=kb.id,
                doc_title=doc.title,
                kb_name=kb.name,
                snippet=chunk.content.strip(),
                content=chunk.content.strip(),
                locator=_locator(chunk.page_no, chunk.sheet_name, chunk.row_start, chunk.row_end, chunk.heading_path),
                dense_score=item.get("dense", 0.0),
                sparse_score=item.get("sparse", 0.0),
                rrf_score=item.get("rrf", 0.0),
            )
        )

    ranked, degraded = await _rerank_candidates(query_text, ordered, top_n)
    meta["rerank_degraded"] = degraded

    # Parent expansion: pull the larger parent block for generation context while
    # keeping the child snippet as the precise citation.
    parent_ids = [c.parent_id for c in ranked if c.parent_id]
    parent_map: dict[int, str] = {}
    if parent_ids:
        parent_rows = (
            await db.execute(select(Chunk.id, Chunk.content).where(Chunk.id.in_(parent_ids)))
        ).all()
        parent_map = {pid: text for pid, text in parent_rows}
        for cand in ranked:
            if cand.parent_id and cand.parent_id in parent_map:
                cand.content = parent_map[cand.parent_id]
                cand.extra["expanded"] = True

    # Deduplicate by parent so the same 1200-char block is not repeated; keep the
    # highest-scoring child as the citation anchor.
    final: list[RetrievedSource] = []
    seen_parents: set[int | None] = set()
    for cand in ranked:
        key = cand.parent_id or cand.chunk_id
        if key in seen_parents and len(final) < top_n:
            continue
        seen_parents.add(key)
        cand.rank = len(final) + 1
        final.append(cand)
        if len(final) >= top_n:
            break

    return final, meta


def build_context(sources: list[RetrievedSource], budget_chars: int | None = None) -> tuple[str, list[RetrievedSource]]:
    """Assemble numbered context blocks under a character budget."""
    budget = budget_chars or settings.context_char_budget
    used: list[RetrievedSource] = []
    blocks: list[str] = []
    consumed = 0
    for src in sources:
        location = []
        if src.locator.get("page_no"):
            location.append(f"第{src.locator['page_no']}页")
        if src.locator.get("sheet_name"):
            location.append(f"工作表{src.locator['sheet_name']}")
        if src.locator.get("row_start"):
            row = f"第{src.locator['row_start']}"
            if src.locator.get("row_end") and src.locator["row_end"] != src.locator["row_start"]:
                row += f"-{src.locator['row_end']}"
            location.append(f"{row}行")
        if src.locator.get("heading_path"):
            location.append(str(src.locator["heading_path"]))
        where = "｜".join(location) if location else "正文"
        header = f"[{src.rank}] 文档：{src.doc_title}｜位置：{where}\n"
        remaining = budget - consumed - len(header)
        if remaining <= 120:
            break
        body = src.content.strip()
        if len(body) > remaining:
            body = body[:remaining].rsplit("\n", 1)[0] + "…"
        block = header + body
        blocks.append(block)
        consumed += len(block)
        used.append(src)
        if consumed >= budget:
            break
    return "\n\n".join(blocks), used


def context_token_count(context: str) -> int:
    return approx_token_count(context)


def vector_to_list(vec: np.ndarray) -> list[float]:
    return vec.astype(float).tolist()
