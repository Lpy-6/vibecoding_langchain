from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.core.config import settings
from app.rag import rewrite
from app.rag.embeddings import (
    HashingEmbeddingProvider,
    encode_vector,
    decode_vector,
    tokenize_chinese,
    tokenize_query,
)
from app.rag.rewrite import extract_keywords, needs_rewrite, normalize_query, rewrite_query
from app.rag.citations import citation_coverage, extract_used_indices


def test_normalize_query_fullwidth_and_whitespace():
    assert normalize_query("  星辰Ｘ１　Ｐｒｏ   多少钱？ ") == "星辰X1 Pro 多少钱?"


def test_hashing_embeddings_are_normalized_and_deterministic():
    provider = HashingEmbeddingProvider(dim=256)
    vec1 = np.asarray(provider._vector("星辰 X1 Pro 保修政策"), dtype=np.float32)
    vec2 = np.asarray(provider._vector("星辰 X1 Pro 保修政策"), dtype=np.float32)
    assert np.allclose(vec1, vec2)
    assert abs(float(np.linalg.norm(vec1)) - 1.0) < 1e-5
    assert vec1.shape[0] == 256


def test_tokenize_query_adds_synonyms():
    tokens = tokenize_query("这款手机多少钱")
    assert "价格" in tokens or "售价" in tokens
    tokens2 = tokenize_query("保修多久")
    assert "质保" in tokens2 or "售后" in tokens2
    assert all(t.strip() for t in tokenize_chinese("退货 政策\n七天"))


def test_needs_rewrite_only_for_context_dependent_questions():
    history = [{"role": "user", "content": "星辰 X1 Pro 多少钱"}, {"role": "assistant", "content": "4299 元"}]
    assert needs_rewrite("那它支持哪些支付方式？", history) is True
    assert needs_rewrite("保修多久", history) is True  # short follow-up
    assert needs_rewrite("星辰 X1 Pro 多少钱？", history) is False
    assert needs_rewrite("那它支持哪些支付方式？", []) is False


def test_extract_used_indices_validates_range_and_dedupes():
    answer = "保修 1 年 [1]，电池 6 个月 [2]，另见 [2][9][0]。"
    assert extract_used_indices(answer, 3) == [1, 2]
    assert extract_used_indices(answer, 0) == []


def test_vector_blob_roundtrip():
    values = [0.1, 0.2, -0.3]
    blob = encode_vector(values)
    decoded = decode_vector(blob)
    assert decoded.dtype == np.float32
    assert np.allclose(decoded, np.asarray(values, dtype=np.float32))


# ---------- normalize_query / extract_keywords ----------


def test_normalize_query_removes_control_chars_and_truncates():
    assert normalize_query("星\x00辰\x0bX9") == "星 辰 X9"
    long_text = "问" * 3000
    assert len(normalize_query(long_text)) == 2000


def test_extract_keywords_respects_top_k_and_empty_text():
    actual = extract_keywords("星辰 X9 手机的保修政策", top_k=3)
    assert len(actual) <= 3
    assert all(isinstance(k, str) and k for k in actual)
    assert extract_keywords("") == []


# ---------- rewrite_query ----------


async def test_rewrite_query_without_history_returns_question_unchanged():
    standalone, keywords, rewritten = await rewrite_query("星辰 X9 多少钱", [])
    assert standalone == "星辰 X9 多少钱"
    assert rewritten is False
    assert isinstance(keywords, list)


async def test_rewrite_query_short_followup_prepends_last_user_question():
    # Given: mock 模式（use_dashscope=False）走启发式改写
    history = [
        {"role": "user", "content": "星辰 X9 Pro 多少钱"},
        {"role": "assistant", "content": "4299 元"},
    ]

    # When
    standalone, _keywords, rewritten = await rewrite_query("那保修呢", history)

    # Then
    assert standalone == "星辰 X9 Pro 多少钱 那保修呢"
    assert rewritten is True


class _FakeChatLLM:
    def __init__(self, content: str | None = None, error: Exception | None = None, **_kwargs) -> None:
        self._content = content
        self._error = error

    async def ainvoke(self, _prompt: str):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(content=self._content)


def _force_dashscope(monkeypatch):
    monkeypatch.setattr(type(settings), "use_dashscope", property(lambda self: True))


async def test_rewrite_query_llm_json_response_parses_standalone_and_keywords(monkeypatch):
    _force_dashscope(monkeypatch)
    llm_response = '```json\n{"standalone_query": "星辰X9手机的价格是多少", "keywords": ["星辰X9", "价格"]}\n```'
    monkeypatch.setattr(rewrite, "ChatOpenAI", lambda **_kwargs: _FakeChatLLM(content=llm_response))
    history = [{"role": "user", "content": "星辰 X9 Pro 多少钱"}]

    standalone, keywords, rewritten = await rewrite_query("它多少钱", history)

    assert standalone == "星辰X9手机的价格是多少"
    assert keywords == ["星辰X9", "价格"]
    assert rewritten is True


async def test_rewrite_query_llm_empty_keywords_falls_back_to_jieba(monkeypatch):
    _force_dashscope(monkeypatch)
    llm_response = '{"standalone_query": "星辰X9手机的价格是多少", "keywords": []}'
    monkeypatch.setattr(rewrite, "ChatOpenAI", lambda **_kwargs: _FakeChatLLM(content=llm_response))
    history = [{"role": "user", "content": "星辰 X9 Pro 多少钱"}]

    _standalone, keywords, _rewritten = await rewrite_query("它多少钱", history)

    assert isinstance(keywords, list)
    assert all(isinstance(k, str) and k for k in keywords)


async def test_rewrite_query_llm_failure_falls_back_to_heuristic(monkeypatch):
    _force_dashscope(monkeypatch)
    monkeypatch.setattr(rewrite, "ChatOpenAI", lambda **_kwargs: _FakeChatLLM(error=RuntimeError("boom")))
    history = [{"role": "user", "content": "星辰 X9 的保修政策"}]

    standalone, _keywords, rewritten = await rewrite_query("它多少钱", history)

    assert standalone == "星辰 X9 的保修政策 它多少钱"
    assert rewritten is True


# ---------- citations ----------


def test_citation_coverage_partial_and_full_and_none():
    assert citation_coverage("见 [1] 与 [2]。", 4) == 0.5
    assert citation_coverage("见 [1][2][3][4]。", 4) == 1.0
    assert citation_coverage("没有引用的答案。", 4) == 0.0


def test_citation_coverage_zero_sources_returns_zero():
    assert citation_coverage("答案 [1]。", 0) == 0.0


def test_extract_used_indices_two_digit_and_overlong_patterns():
    answer = "共 [9][10] 两处。"
    assert extract_used_indices(answer, 10) == [9, 10]
    assert extract_used_indices(answer, 9) == [9]
    assert extract_used_indices("[123]", 99) == []
