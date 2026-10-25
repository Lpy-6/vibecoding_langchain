"""
Offline extractive answer generator used when no DashScope key is configured.

It composes a grounded, cited answer from the retrieved blocks so the full
product (streaming, citations, feedback, admin) can be demonstrated without
network access to a model.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from app.rag.embeddings import tokenize_query
from app.rag.retriever import RetrievedSource

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；])")
_STOPWORDS = {
    "支持", "哪些", "什么", "怎么", "如何", "多少", "多久", "可以", "需要", "是否",
    "那", "那么", "它", "它们", "这个", "那个", "上面", "刚才", "继续", "还有",
    "的", "了", "吗", "呢", "有", "和", "与", "是", "请", "介绍", "一下", "关于",
}


def _meaningful_tokens(text: str) -> set[str]:
    result: set[str] = set()
    for token in tokenize_query(text):
        if token in _STOPWORDS or not token.strip():
            continue
        if len(token) == 1 and not (token.isdigit() or token in {"元", "块", "寸"}):
            continue
        result.add(token)
    return result


def _segments(text: str) -> list[str]:
    """Split into candidate snippets, keeping table rows intact."""
    segments: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line or line.count(":") + line.count("：") >= 2:
            segments.append(line)
            continue
        for part in _SENTENCE_SPLIT.split(line):
            part = part.strip(" -•\t")
            if part:
                segments.append(part)
    return segments


def _model_phrases(question: str) -> list[str]:
    text = question.lower()
    phrases = re.findall(r"[a-z]+\s?\d+(?:\s?[a-z]+)?", text)
    result: list[str] = []
    for phrase in phrases:
        phrase = phrase.strip()
        if len(phrase.replace(" ", "")) >= 2 and phrase not in result:
            result.append(phrase)
    return sorted(result, key=len, reverse=True)


def _pick_sentences(text: str, question: str, limit: int = 2, max_chars: int = 320) -> str:
    segments = _segments(text)
    if not segments:
        return ""
    q_tokens = _meaningful_tokens(question)
    model_phrases = _model_phrases(question)
    wants_rules = bool(re.search(r"(条件|要求|规则|怎么|如何|多久|几天|多少)", question))
    scored: list[tuple[float, int, str]] = []
    for idx, segment in enumerate(segments):
        lower = segment.lower()
        d_tokens = set(tokenize_query(segment))
        matched = q_tokens & d_tokens
        score = sum(len(token) for token in matched)
        if re.search(r"\d", segment):
            score += 1.2
        if wants_rules and re.search(r"(可申请|需|条件|规则|应当|期限内)", segment):
            score += 1.8
        for phrase in model_phrases:
            if phrase in lower:
                score += 2.5 * len(phrase.split())
                break
        scored.append((score, idx, segment))
    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    best = scored[0][2]
    # For tabular rows, one precise row beats a whole block of sibling products.
    if ("；" in best or "|" in best) and (":" in best or "：" in best):
        limit = 1
    picked = sorted(scored[:limit], key=lambda x: x[1])
    out: list[str] = []
    total = 0
    for _, _, segment in picked:
        if out and total + len(segment) > max_chars:
            continue
        out.append(segment)
        total += len(segment)
    return " ".join(out)


def _source_relevance(source: RetrievedSource, q_tokens: set[str]) -> int:
    heading = source.locator.get("heading_path") or ""
    text = f"{source.doc_title} {heading} {source.content}"
    return len(q_tokens & set(tokenize_query(text)))


def compose_mock_answer(question: str, sources: list[RetrievedSource]) -> str:
    if not sources:
        return (
            "知识库中未找到与您问题直接相关的信息。"
            "您可以换一种问法，补充商品名称或型号，或联系人工客服进一步确认。"
        )
    q_tokens = _meaningful_tokens(question)
    ranked = sorted(sources, key=lambda s: (s.rerank_score, _source_relevance(s, q_tokens)), reverse=True)
    relevant = [s for s in ranked if _source_relevance(s, q_tokens) > 0]
    selected = (relevant or ranked)[:3]

    lines: list[str] = ["根据知识库中的商品资料，整理如下：", ""]
    for idx, source in enumerate(selected):
        excerpt = _pick_sentences(source.content, question, limit=3 if idx == 0 else 2)
        if not excerpt:
            continue
        lines.append(f"- {excerpt} [{source.rank}]")
    if len(lines) <= 2:
        return "知识库中有相关内容，但暂时无法提取有效信息，请换个问法或联系人工客服。"
    lines.append("")
    lines.append("以上信息来自商品知识库，如需了解更细节的规格或售后政策，可以继续提问。")
    return "\n".join(lines)


async def stream_mock_answer(question: str, sources: list[RetrievedSource]) -> AsyncIterator[str]:
    answer = compose_mock_answer(question, sources)
    step = 6
    for i in range(0, len(answer), step):
        yield answer[i : i + step]
        await asyncio.sleep(0.012)
