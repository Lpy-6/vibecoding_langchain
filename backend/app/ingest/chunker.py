"""
Parent-child chunking with Chinese-aware separators.

Parents (~1200 chars) carry the generation context; children (~300 chars) are
embedded and matched, then mapped back to their parent. Locators are copied from
the parsed block so a citation can say "第 3 页" or "工作表 价格表 第 12-31 行".
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.ingest.parsers import ParsedBlock
from app.rag.embeddings import approx_token_count

SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


@dataclass
class ChunkDraft:
    content: str
    chunk_type: str
    ordinal: int
    parent_index: int | None
    page_no: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    heading_path: str | None
    content_hash: str
    token_count: int
    embedding_text: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_blocks(blocks: list[ParsedBlock], doc_title: str, max_children: int = 5000) -> list[ChunkDraft]:
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.parent_chunk_size,
        chunk_overlap=settings.parent_chunk_overlap,
        separators=SEPARATORS,
        keep_separator=True,
        length_function=len,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.child_chunk_size,
        chunk_overlap=settings.child_chunk_overlap,
        separators=SEPARATORS,
        keep_separator=True,
        length_function=len,
    )

    drafts: list[ChunkDraft] = []
    parent_ordinal = 0
    parent_count = 0
    child_ordinal = 0
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        parents = parent_splitter.split_text(text) or [text]
        for parent_text in parents:
            parent_text = parent_text.strip()
            if not parent_text:
                continue
            parent_index = parent_count
            parent_count += 1
            prefix = f"【{doc_title}"
            if block.heading_path:
                prefix += f" › {block.heading_path}"
            prefix += "】"
            drafts.append(
                ChunkDraft(
                    content=parent_text,
                    chunk_type="parent",
                    ordinal=parent_ordinal,
                    parent_index=None,
                    page_no=block.page_no,
                    sheet_name=block.sheet_name,
                    row_start=block.row_start,
                    row_end=block.row_end,
                    heading_path=block.heading_path,
                    content_hash=_hash(parent_text),
                    token_count=approx_token_count(parent_text),
                    embedding_text="",
                )
            )
            parent_ordinal += 1
            for child_text in child_splitter.split_text(parent_text) or [parent_text]:
                child_text = child_text.strip()
                if not child_text:
                    continue
                drafts.append(
                    ChunkDraft(
                        content=child_text,
                        chunk_type="child",
                        ordinal=child_ordinal,
                        parent_index=parent_index,
                        page_no=block.page_no,
                        sheet_name=block.sheet_name,
                        row_start=block.row_start,
                        row_end=block.row_end,
                        heading_path=block.heading_path,
                        content_hash=_hash(child_text),
                        token_count=approx_token_count(child_text),
                        embedding_text=f"{prefix}{child_text}",
                    )
                )
                child_ordinal += 1
                if child_ordinal > max_children:
                    raise ValueError(f"文档分块超过 {max_children} 个，请拆分后再上传")
    return drafts
