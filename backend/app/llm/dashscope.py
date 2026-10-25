"""
Thin async clients for DashScope (Bailian) native APIs: embeddings, rerank, OCR.
Chat runs through LangChain's ChatOpenAI (OpenAI-compatible endpoint) instead.
"""
from __future__ import annotations

import asyncio
import base64
import html as html_lib
import logging
import re
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}


def clean_ocr_text(text: str) -> str:
    """qwen-vl-ocr may return HTML/tables inside code fences; normalize to text."""
    text = text.strip()
    text = re.sub(r"^```(?:html|markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if "<" in text and ">" in text:
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</(p|div|tr|li|h\d|table)>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</t[dh]>", " | ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html_lib.unescape(text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t\u3000]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


async def _post_with_retry(url: str, payload: dict, timeout: float = 60.0, retries: int = 3) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in _RETRY_STATUS:
                last_error = RuntimeError(f"DashScope HTTP {resp.status_code}: {resp.text[:300]}")
                await asyncio.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries - 1:
                break
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError(f"DashScope 请求失败: {last_error}")


async def embed_texts(texts: list[str], batch_size: int | None = None) -> list[list[float]]:
    """Embed texts with text-embedding-v4 (native API, batches of 10)."""
    if not texts:
        return []
    batch_size = batch_size or settings.embedding_batch_size
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        payload = {
            "model": settings.embedding_model,
            "input": {"texts": batch},
            "parameters": {"dimension": settings.embedding_dim, "output_type": "dense"},
        }
        data = await _post_with_retry(
            f"{settings.dashscope_native_url}/services/embeddings/text-embedding/text-embedding",
            payload,
            timeout=60.0,
        )
        items = data.get("output", {}).get("embeddings", [])
        items.sort(key=lambda x: x.get("text_index", 0))
        if len(items) != len(batch):
            raise RuntimeError("Embedding 返回数量与请求不一致")
        vectors.extend([item["embedding"] for item in items])
    return vectors


async def rerank(query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
    """Return [(original_index, relevance_score)] from gte-rerank-v2."""
    if not documents:
        return []
    payload = {
        "model": settings.rerank_model,
        "input": {"query": query, "documents": documents},
        "parameters": {"return_documents": False, "top_n": min(top_n, len(documents))},
    }
    data = await _post_with_retry(
        f"{settings.dashscope_native_url}/services/rerank/text-rerank/text-rerank",
        payload,
        timeout=15.0,
        retries=2,
    )
    results = data.get("output", {}).get("results", [])
    return [(int(item["index"]), float(item.get("relevance_score", 0.0))) for item in results]


async def ocr_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """OCR an image with qwen-vl-ocr (multimodal generation API)."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    payload: dict[str, Any] = {
        "model": settings.ocr_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": data_url},
                        {"text": "请提取图片中的全部文字，保持原有段落与表格结构，不要添加解释。"},
                    ],
                }
            ]
        },
        "parameters": {"temperature": 0.01},
    }
    data = await _post_with_retry(
        f"{settings.dashscope_native_url}/services/aigc/multimodal-generation/generation",
        payload,
        timeout=120.0,
        retries=2,
    )
    choices = data.get("output", {}).get("choices", [])
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, str):
        return clean_ocr_text(content)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
        return clean_ocr_text("\n".join(parts))
    return clean_ocr_text(str(content))
