"""
Embedding providers.

- DashScopeEmbeddingProvider: text-embedding-v4 (real mode).
- HashingEmbeddingProvider: fully offline, deterministic char n-gram + jieba
  word hashing. Not semantic, but keeps the whole RAG pipeline demoable without
  an API key; swap in a key to get real vectors with zero code changes.
"""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

import jieba
import numpy as np

from app.core.config import settings
from app.llm import dashscope

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        vec[0] = 1.0
        return vec
    return vec / norm


def encode_vector(values: list[float]) -> bytes:
    return np.asarray(values, dtype=np.float32).tobytes()


def decode_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class EmbeddingProvider(ABC):
    name: str
    dim: int

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_texts_sync(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]:
        result = await self.embed_texts([text])
        return result[0]


class DashScopeEmbeddingProvider(EmbeddingProvider):
    def __init__(self) -> None:
        self.name = settings.embedding_model
        self.dim = settings.embedding_dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = await dashscope.embed_texts(texts)
        return [vec[: self.dim] for vec in vectors]

    def embed_texts_sync(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        return asyncio.run(self.embed_texts(texts))


class HashingEmbeddingProvider(EmbeddingProvider):
    name = "offline-hashing-v1"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embedding_dim

    def _vector(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        words = [w.strip() for w in jieba.lcut(text.lower()) if w.strip()]
        tokens: list[tuple[str, float]] = [(w, 1.0) for w in words if len(w) > 1 or _CJK.match(w)]
        compact = re.sub(r"\s+", "", text.lower())
        for i in range(len(compact) - 1):
            tokens.append((compact[i : i + 2], 0.55))
        for i in range(len(compact) - 2):
            tokens.append((compact[i : i + 3], 0.25))
        for token, weight in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            num = int.from_bytes(digest, "big")
            idx = num % self.dim
            sign = 1.0 if (num >> 63) & 1 else -1.0
            vec[idx] += sign * weight
        vec = _l2_normalize(vec)
        return vec.astype(float).tolist()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_texts_sync(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        _provider = DashScopeEmbeddingProvider() if settings.use_dashscope else HashingEmbeddingProvider()
    return _provider


def reset_embedding_provider() -> None:
    global _provider
    _provider = None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def tokenize_chinese(text: str) -> list[str]:
    """Search-mode tokenization: overlapping sub-words improve Chinese recall."""
    tokens: list[str] = []
    for word in jieba.cut_for_search((text or "").lower()):
        word = word.strip()
        if not word or word.isspace():
            continue
        if len(word) == 1 and not _CJK.match(word):
            continue
        tokens.append(word)
    return tokens


QUERY_SYNONYMS: dict[str, list[str]] = {
    "多少钱": ["价格", "售价", "优惠", "元"],
    "多少": ["价格", "售价", "元"],
    "钱": ["价格", "售价", "元"],
    "价格": ["售价", "多少钱", "优惠"],
    "保修": ["质保", "售后", "维修"],
    "质保": ["保修", "售后"],
    "退换": ["退货", "换货", "售后"],
    "退货": ["退款", "退回", "售后"],
    "换货": ["退换", "换新"],
    "发货": ["配送", "物流", "快递"],
    "配送": ["发货", "物流", "快递"],
    "物流": ["发货", "配送", "快递"],
    "运费": ["邮费", "费用"],
    "发票": ["开票", "票据"],
    "支付": ["付款", "微信", "支付宝", "银行卡"],
    "内存": ["存储", "容量"],
    "存储": ["内存", "容量"],
    "续航": ["电池", "充电"],
    "电池": ["续航", "充电"],
    "参数": ["配置", "规格", "屏幕", "芯片"],
}


def tokenize_query(text: str) -> list[str]:
    """Tokenize a query and add domain synonyms (offline retrieval boost)."""
    tokens = tokenize_chinese(text)
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(QUERY_SYNONYMS.get(token, []))
    # de-duplicate, keep order
    seen: set[str] = set()
    result: list[str] = []
    for token in expanded:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def approx_token_count(text: str) -> int:
    # Chinese-heavy heuristic: ~1.6 chars per token.
    return max(1, math.ceil(len(text) / 1.6))
