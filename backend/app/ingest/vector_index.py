"""
In-process vector + BM25 index per knowledge base.

The index is rebuilt lazily from SQLite when a KB version changes. For a
graduation-project scale corpus (tens of thousands of child chunks) a single
normalized numpy matrix gives millisecond cosine search, and rank_bm25 provides
Chinese keyword retrieval after jieba tokenization. The public methods mirror
what a pgvector/hybrid retriever would expose.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select

from app.db.models import Chunk, Document
from app.db.session import sync_session_scope
from app.rag.embeddings import decode_vector, get_embedding_provider, tokenize_chinese, tokenize_query

logger = logging.getLogger(__name__)


@dataclass
class KBIndex:
    kb_id: str
    version: int
    chunk_ids: np.ndarray
    matrix: np.ndarray
    contents: list[str] = field(default_factory=list)
    bm25: BM25Okapi | None = None
    id_to_pos: dict[int, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return int(self.chunk_ids.shape[0])


class VectorIndexManager:
    def __init__(self) -> None:
        self._indexes: dict[str, KBIndex] = {}
        self._lock = threading.RLock()

    def invalidate(self, kb_id: str) -> None:
        with self._lock:
            self._indexes.pop(kb_id, None)
        logger.info("vector index invalidated kb=%s", kb_id)

    def invalidate_all(self) -> None:
        with self._lock:
            self._indexes.clear()

    def _build(self, kb_id: str, version: int) -> KBIndex:
        provider_name = get_embedding_provider().name
        with sync_session_scope() as session:
            rows = session.execute(
                select(
                    Chunk.id,
                    Chunk.content,
                    Chunk.embedding,
                    Chunk.heading_path,
                    Document.title,
                )
                .join(Document, Document.id == Chunk.document_id)
                .where(
                    Chunk.kb_id == kb_id,
                    Chunk.chunk_type == "child",
                    Chunk.embedding.is_not(None),
                    Chunk.embedding_model == provider_name,
                    Document.deleted_at.is_(None),
                    Document.status == "ready",
                )
                .order_by(Chunk.id)
            ).all()

        ids: list[int] = []
        vectors: list[np.ndarray] = []
        contents: list[str] = []
        search_texts: list[str] = []
        for chunk_id, content, blob, heading_path, doc_title in rows:
            vec = decode_vector(blob)
            if vec.size == 0:
                continue
            ids.append(int(chunk_id))
            vectors.append(vec)
            contents.append(content or "")
            search_texts.append(f"{doc_title or ''} {heading_path or ''} {content or ''}")

        if not vectors:
            return KBIndex(
                kb_id=kb_id,
                version=version,
                chunk_ids=np.empty(0, dtype=np.int64),
                matrix=np.empty((0, 0), dtype=np.float32),
                contents=[],
                bm25=None,
                id_to_pos={},
            )

        dim = vectors[0].shape[0]
        matrix = np.vstack([v for v in vectors if v.shape[0] == dim]).astype(np.float32)
        # Normalize once at build time, then cosine == dot product.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms

        tokenized = [tokenize_chinese(text) for text in search_texts]
        bm25 = BM25Okapi(tokenized) if tokenized else None
        chunk_ids = np.asarray(ids[: matrix.shape[0]], dtype=np.int64)
        logger.info("vector index built kb=%s version=%s chunks=%d dim=%d", kb_id, version, len(ids), dim)
        return KBIndex(
            kb_id=kb_id,
            version=version,
            chunk_ids=chunk_ids,
            matrix=matrix,
            contents=contents,
            bm25=bm25,
            id_to_pos={cid: pos for pos, cid in enumerate(ids)},
        )

    def get_index(self, kb_id: str, version: int) -> KBIndex:
        with self._lock:
            index = self._indexes.get(kb_id)
            if index is not None and index.version == version:
                return index
            index = self._build(kb_id, version)
            self._indexes[kb_id] = index
            return index

    def stats(self) -> dict:
        with self._lock:
            return {
                kb_id: {"version": idx.version, "chunks": idx.size}
                for kb_id, idx in self._indexes.items()
            }


vector_index_manager = VectorIndexManager()


def _top_indices(scores: np.ndarray, k: int) -> list[int]:
    if scores.size == 0:
        return []
    k = min(k, scores.size)
    if k <= 0:
        return []
    if k == scores.size:
        order = np.argsort(-scores)
    else:
        part = np.argpartition(-scores, k - 1)[:k]
        order = part[np.argsort(-scores[part])]
    return [int(i) for i in order]


def hybrid_search(
    kb_versions: dict[str, int],
    query_vector: list[float],
    query_text: str,
    dense_k: int,
    sparse_k: int,
    rrf_k: int = 60,
) -> list[dict]:
    """Return fused candidates: [{chunk_id, dense, sparse, rrf, kb_id}]."""
    q = np.asarray(query_vector, dtype=np.float32)
    q_norm = float(np.linalg.norm(q))
    if q_norm == 0:
        return []
    q = q / q_norm
    q_tokens = tokenize_query(query_text)

    fused: dict[int, dict] = {}
    for kb_id, version in kb_versions.items():
        index = vector_index_manager.get_index(kb_id, version)
        if index.size == 0 or index.matrix.shape[1] != q.shape[0]:
            continue

        dense_scores = index.matrix @ q
        dense_idx = _top_indices(dense_scores, dense_k)

        sparse_scores = np.zeros(index.size, dtype=np.float32)
        if index.bm25 is not None and q_tokens:
            sparse_scores = np.asarray(index.bm25.get_scores(q_tokens), dtype=np.float32)
        sparse_idx = _top_indices(sparse_scores, sparse_k)

        for rank, pos in enumerate(dense_idx):
            cid = int(index.chunk_ids[pos])
            item = fused.setdefault(cid, {"chunk_id": cid, "kb_id": kb_id, "dense": 0.0, "sparse": 0.0, "rrf": 0.0})
            item["dense"] = max(item["dense"], float(dense_scores[pos]))
            item["rrf"] += 1.0 / (rrf_k + rank + 1)
        for rank, pos in enumerate(sparse_idx):
            cid = int(index.chunk_ids[pos])
            item = fused.setdefault(cid, {"chunk_id": cid, "kb_id": kb_id, "dense": 0.0, "sparse": 0.0, "rrf": 0.0})
            item["sparse"] = max(item["sparse"], float(sparse_scores[pos]))
            item["rrf"] += 0.8 / (rrf_k + rank + 1)

    candidates = list(fused.values())
    candidates.sort(key=lambda x: (x["rrf"], x["dense"]), reverse=True)
    return candidates
