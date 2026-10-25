"""
Query normalization and multi-turn query rewriting.

Rewriting only kicks in when it is likely to help (short query, pronouns,
multi-turn). This keeps the common case at one embedding + one chat call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata

import jieba.analyse
from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_PRONOUNS = re.compile(r"(这个|那个|它|它们|上面|刚才|前面|继续|还有|这种|该|此|其)")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

REWRITE_PROMPT = """你是电商知识库检索助手。请把用户的最新问题改写成一个可独立检索的完整问题，并抽取检索关键词。
规则：
1. 结合最近对话补全指代（如“这个”、“它”、“刚才说的”）。
2. 不要回答用户，只输出 JSON。
3. JSON 格式：{{"standalone_query": "...", "keywords": ["...", "..."]}}
4. keywords 3-8 个，保留商品型号、价格、政策名词。

最近对话：
{history}

用户最新问题：{question}
"""


def normalize_query(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = _CONTROL.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]


def extract_keywords(text: str, top_k: int = 8) -> list[str]:
    try:
        return list(jieba.analyse.extract_tags(text, topK=top_k))
    except Exception:
        return []


def needs_rewrite(question: str, history: list[dict]) -> bool:
    if not history:
        return False
    if _PRONOUNS.search(question):
        return True
    if history and len(question) <= 6:
        return True
    return False


def _heuristic_rewrite(question: str, history: list[dict]) -> str:
    last_user = ""
    for item in reversed(history):
        if item.get("role") == "user" and item.get("content"):
            last_user = item["content"].strip()
            break
    if last_user and needs_rewrite(question, history):
        return f"{last_user[:200]} {question}".strip()
    return question


def _history_text(history: list[dict], limit: int = 4) -> str:
    lines = []
    for item in history[-limit:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = (item.get("content") or "").strip().replace("\n", " ")
        if content:
            lines.append(f"{role}：{content[:200]}")
    return "\n".join(lines) or "无"


async def rewrite_query(question: str, history: list[dict]) -> tuple[str, list[str], bool]:
    """Return (standalone_query, keywords, rewritten)."""
    if not needs_rewrite(question, history) or not settings.use_dashscope:
        standalone = _heuristic_rewrite(question, history)
        return standalone, extract_keywords(standalone), standalone != question

    try:
        llm = ChatOpenAI(
            model=settings.chat_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            temperature=0.0,
            timeout=10,
            max_retries=0,
        )
        prompt = REWRITE_PROMPT.format(history=_history_text(history), question=question)
        result = await asyncio.wait_for(llm.ainvoke(prompt), timeout=12.0)
        raw = (result.content or "").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        standalone = normalize_query(str(data.get("standalone_query") or question))
        keywords = [str(k) for k in data.get("keywords", []) if str(k).strip()][:8]
        if not keywords:
            keywords = extract_keywords(standalone)
        return standalone, keywords, standalone != question
    except Exception as exc:  # noqa: BLE001
        logger.warning("query rewrite failed, using heuristic: %s", exc)
        standalone = _heuristic_rewrite(question, history)
        return standalone, extract_keywords(standalone), standalone != question
