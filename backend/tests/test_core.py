from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from app.ingest.chunker import chunk_blocks
from app.ingest.parsers import ParsedBlock
from app.rag.answer import compose_mock_answer
from app.rag.retriever import RetrievedSource
from app.services.storage import delete_file, safe_filename, save_bytes, write_text_snapshot


def test_password_hash_and_verify():
    hashed = hash_password("123456")
    assert hashed.startswith("$argon2")
    assert verify_password("123456", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_access_token_roundtrip_and_type():
    token, expires_in = create_access_token("u1", "demo", "user", 3)
    payload = decode_access_token(token)
    assert payload["sub"] == "u1"
    assert payload["role"] == "user"
    assert payload["ver"] == 3
    assert expires_in > 0


def test_refresh_token_is_opaque_and_hashed():
    token = new_refresh_token()
    assert len(token) > 40
    assert len(hash_refresh_token(token)) == 64
    assert hash_refresh_token(token) != token


def test_parent_child_chunking_keeps_locator():
    text = "星辰 X1 Pro 保修 1 年。\n" * 120
    drafts = chunk_blocks([ParsedBlock(text=text, page_no=3, heading_path="售后 › 保修")], "售后政策")
    parents = [d for d in drafts if d.chunk_type == "parent"]
    children = [d for d in drafts if d.chunk_type == "child"]
    assert parents and children
    assert all(c.chunk_type == "child" for c in children)
    assert all(c.page_no == 3 for c in drafts)
    assert all(c.heading_path == "售后 › 保修" for c in drafts)
    assert all(0 <= c.parent_index < len(parents) for c in children)
    assert "【售后政策 › 售后 › 保修】" in children[0].embedding_text


def _source(rank: int, content: str, title: str = "测试文档") -> RetrievedSource:
    return RetrievedSource(
        rank=rank,
        chunk_id=rank,
        parent_id=None,
        document_id="d1",
        kb_id="kb1",
        doc_title=title,
        kb_name="测试库",
        snippet=content,
        content=content,
        locator={},
        rerank_score=1.0 - rank * 0.1,
    )


def test_mock_answer_extracts_price_from_table_row():
    content = (
        "商品名称 | 型号 | 价格 | 库存\n"
        "商品名称: 星辰 X1 Pro；型号: X1 Pro；价格: 4299；芯片: 骁龙 8 Gen3\n"
        "商品名称: 星辰 X1；型号: X1；价格: 3299；芯片: 天玑 9300"
    )
    answer = compose_mock_answer("星辰 X1 Pro 多少钱？", [_source(1, content, "在售商品")])
    assert "4299" in answer
    assert "[1]" in answer


def test_mock_answer_prefers_warranty_sentence():
    content = (
        "星辰手机主机享受 1 年保修，电池、充电器等附件享受 6 个月保修。\n"
        "人为损坏、进水、私自拆修不在保修范围内。\n"
        "在“我的订单”中选择申请售后，上传照片并提交审核。"
    )
    answer = compose_mock_answer("星辰手机的保修期是多久？", [_source(1, content, "售后服务政策")])
    assert "1 年保修" in answer
    assert "[1]" in answer


def test_mock_answer_without_sources_is_grounded():
    answer = compose_mock_answer("有没有现货？", [])
    assert "未找到" in answer


# ---------- chunker 边界分支 ----------


def test_chunk_blocks_skips_blank_blocks():
    drafts = chunk_blocks(
        [ParsedBlock(text="   \n  "), ParsedBlock(text="星辰 X9 售价 8888 元。")],
        "商品手册",
    )
    assert drafts
    assert all(d.content.strip() for d in drafts)
    assert len([d for d in drafts if d.chunk_type == "parent"]) == 1


def test_chunk_blocks_exceeding_max_children_raises_value_error():
    with pytest.raises(ValueError, match="文档分块超过"):
        chunk_blocks([ParsedBlock(text="a" * 700)], "超大文档", max_children=1)


# ---------- token 校验 ----------


def test_decode_access_token_garbage_token_raises():
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token("not-a-jwt")


def test_decode_access_token_refresh_type_token_raises():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "u1",
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_needs_rehash_fresh_hash_returns_false():
    assert needs_rehash(hash_password("123456")) is False


# ---------- storage ----------


def test_safe_filename_replaces_unsafe_characters():
    assert safe_filename("报告/最终版: v2?.txt") == "报告_最终版_v2_.txt"


def test_safe_filename_blank_or_all_unsafe_falls_back_to_file():
    assert safe_filename("???") == "file"
    assert safe_filename("") == "file"


def test_save_bytes_writes_file_and_returns_sha256():
    data = "商品文档内容".encode("utf-8")
    path, sha = save_bytes(data, "商品.txt")
    assert path.parent == settings.uploads_dir
    assert path.read_bytes() == data
    assert sha == hashlib.sha256(data).hexdigest()


def test_write_text_snapshot_writes_file_and_returns_sha256():
    text = "<html>快照</html>"
    path, sha = write_text_snapshot(text, suffix=".html")
    assert path.suffix == ".html"
    assert path.read_text(encoding="utf-8") == text
    assert sha == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_delete_file_removes_file_inside_uploads():
    path, _ = save_bytes(b"to-delete", "del-me.txt")
    assert path.is_file()
    delete_file(str(path))
    assert not path.exists()


def test_delete_file_outside_uploads_missing_or_none_is_noop(tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_bytes(b"keep")
    delete_file(str(outside))
    assert outside.exists()
    delete_file(None)
    delete_file(str(tmp_path / "missing.bin"))
