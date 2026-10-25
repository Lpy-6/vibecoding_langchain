from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.db.models import (
    Base,
    Chunk,
    Document,
    KBPermission,
    KnowledgeBase,
    SemanticCache,
    User,
    utcnow,
)
from app.services import cache as cache_service
from app.services import kb_access, kb_stats
from app.services.cache import cache_key, config_hash, scope_key


@pytest.mark.asyncio
async def test_sliding_window_limiter_blocks_third_request():
    limiter = SlidingWindowLimiter()
    await limiter.hit("unit-test-key", limit=2)
    await limiter.hit("unit-test-key", limit=2)
    with pytest.raises(HTTPException) as exc:
        await limiter.hit("unit-test-key", limit=2)
    assert exc.value.status_code == 429
    assert "Retry-After" in (exc.value.headers or {})

    # Different keys have independent buckets.
    await limiter.hit("another-key", limit=1)


def test_scope_key_is_order_independent():
    assert scope_key(["kb-a", "kb-b"]) == scope_key(["kb-b", "kb-a"])
    assert scope_key(["kb-a"]) != scope_key(["kb-b"])


def test_cache_key_includes_kb_versions():
    base = cache_key("scope", "星辰 X9 多少钱", {"kb-a": 1, "kb-b": 2})
    reordered = cache_key("scope", "星辰 X9 多少钱", {"kb-b": 2, "kb-a": 1})
    stale = cache_key("scope", "星辰 X9 多少钱", {"kb-a": 2, "kb-b": 2})
    assert base == reordered
    assert base != stale


def test_config_hash_is_stable_sha256():
    first = config_hash()
    second = config_hash()
    assert first == second
    assert len(first) == 64


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def make_user(username: str, role: str = "user") -> User:
    return User(username=username, password_hash="test-hash", role=role)


def make_kb(name: str, is_public: bool = True) -> KnowledgeBase:
    return KnowledgeBase(name=name, is_public=is_public)


def make_doc(kb_id: str, status: str = "ready", deleted: bool = False) -> Document:
    return Document(
        kb_id=kb_id,
        title="文档",
        content_hash=uuid4().hex,
        status=status,
        deleted_at=utcnow() if deleted else None,
    )


def make_chunk(kb_id: str, document_id: str, chunk_type: str = "child") -> Chunk:
    return Chunk(
        kb_id=kb_id,
        document_id=document_id,
        chunk_type=chunk_type,
        ordinal=0,
        content="内容",
        content_hash=uuid4().hex,
    )


# ---------- rate limiter: 其余分支 ----------


@pytest.mark.asyncio
async def test_sliding_window_limiter_within_limit_passes():
    limiter = SlidingWindowLimiter()
    for _ in range(3):
        await limiter.hit("within-limit-key", limit=3)


@pytest.mark.asyncio
async def test_sliding_window_limiter_zero_limit_disables_limiter():
    limiter = SlidingWindowLimiter()
    for _ in range(20):
        await limiter.hit("zero-limit-key", limit=0)


@pytest.mark.asyncio
async def test_sliding_window_limiter_expired_events_are_pruned(monkeypatch):
    limiter = SlidingWindowLimiter()
    real_monotonic = __import__("time").monotonic
    clock = {"now": real_monotonic()}
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: clock["now"])

    await limiter.hit("expire-key", limit=1, window_seconds=60)
    clock["now"] = real_monotonic() + 61
    # 旧事件滑出窗口后应重新放行，且 Retry-After 依据最早事件计算
    await limiter.hit("expire-key", limit=1, window_seconds=60)


@pytest.mark.asyncio
async def test_sliding_window_limiter_retry_after_counts_oldest_event(monkeypatch):
    import time as time_module

    limiter = SlidingWindowLimiter()
    real_monotonic = time_module.monotonic
    clock = {"now": real_monotonic()}
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: clock["now"])

    await limiter.hit("retry-key", limit=1, window_seconds=60)
    clock["now"] = real_monotonic() + 30
    with pytest.raises(HTTPException) as exc:
        await limiter.hit("retry-key", limit=1, window_seconds=60)
    assert exc.value.status_code == 429
    assert "请求过于频繁" in exc.value.detail
    assert int(exc.value.headers["Retry-After"]) == 30


# ---------- kb_access.visible_kb_ids ----------


@pytest.mark.asyncio
async def test_visible_kb_ids_admin_returns_all_kbs(db):
    # Given
    public_kb = make_kb("公开库-admin-all")
    private_kb = make_kb("私有库-admin-all", is_public=False)
    admin = make_user("root-all", role="admin")
    db.add_all([public_kb, private_kb, admin])
    await db.flush()

    # When
    actual_ids = await kb_access.visible_kb_ids(db, admin)

    # Then
    assert set(actual_ids) == {public_kb.id, private_kb.id}


@pytest.mark.asyncio
async def test_visible_kb_ids_user_returns_public_and_granted_only(db):
    # Given
    public_kb = make_kb("公开库-user-visible")
    granted_kb = make_kb("已授权库-user-visible", is_public=False)
    denied_kb = make_kb("未授权库-user-visible", is_public=False)
    revoked_kb = make_kb("被撤销库-user-visible", is_public=False)
    user = make_user("alice-visible")
    db.add_all([public_kb, granted_kb, denied_kb, revoked_kb, user])
    await db.flush()
    db.add_all(
        [
            KBPermission(kb_id=granted_kb.id, user_id=user.id, can_read=True),
            KBPermission(kb_id=revoked_kb.id, user_id=user.id, can_read=False),
        ]
    )
    await db.flush()

    # When
    actual_ids = set(await kb_access.visible_kb_ids(db, user))

    # Then: can_read=False 的授权不产生可见性
    assert actual_ids == {public_kb.id, granted_kb.id}


# ---------- kb_access.assert_kb_visible ----------


@pytest.mark.asyncio
async def test_assert_kb_visible_missing_kb_raises_404(db):
    # Given
    user = make_user("nobody-404")
    db.add(user)
    await db.flush()

    # When / Then
    with pytest.raises(HTTPException) as exc:
        await kb_access.assert_kb_visible(db, user, "missing-kb-id")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_assert_kb_visible_admin_on_private_kb_returns_kb(db):
    # Given
    private_kb = make_kb("私有库-admin-pass", is_public=False)
    admin = make_user("root-pass", role="admin")
    db.add_all([private_kb, admin])
    await db.flush()

    # When
    actual_kb = await kb_access.assert_kb_visible(db, admin, private_kb.id)

    # Then
    assert actual_kb.id == private_kb.id


@pytest.mark.asyncio
async def test_assert_kb_visible_user_on_public_kb_returns_kb(db):
    # Given
    public_kb = make_kb("公开库-user-pass")
    user = make_user("bob-public")
    db.add_all([public_kb, user])
    await db.flush()

    # When
    actual_kb = await kb_access.assert_kb_visible(db, user, public_kb.id)

    # Then
    assert actual_kb.id == public_kb.id


@pytest.mark.asyncio
async def test_assert_kb_visible_user_without_grant_raises_403(db):
    # Given
    private_kb = make_kb("私有库-user-403", is_public=False)
    user = make_user("carol-403")
    db.add_all([private_kb, user])
    await db.flush()

    # When / Then
    with pytest.raises(HTTPException) as exc:
        await kb_access.assert_kb_visible(db, user, private_kb.id)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_kb_visible_user_with_grant_returns_kb(db):
    # Given
    private_kb = make_kb("私有库-user-granted", is_public=False)
    user = make_user("dave-granted")
    db.add_all([private_kb, user])
    await db.flush()
    db.add(KBPermission(kb_id=private_kb.id, user_id=user.id, can_read=True))
    await db.flush()

    # When
    actual_kb = await kb_access.assert_kb_visible(db, user, private_kb.id)

    # Then
    assert actual_kb.id == private_kb.id


# ---------- kb_access.resolve_query_kbs ----------


@pytest.mark.asyncio
async def test_resolve_query_kbs_filters_requested_to_allowed(db):
    # Given
    public_kb = make_kb("公开库-resolve-filter")
    granted_kb = make_kb("已授权库-resolve-filter", is_public=False)
    denied_kb = make_kb("未授权库-resolve-filter", is_public=False)
    user = make_user("eve-filter")
    db.add_all([public_kb, granted_kb, denied_kb, user])
    await db.flush()
    db.add(KBPermission(kb_id=granted_kb.id, user_id=user.id, can_read=True))
    await db.flush()

    # When
    actual_kbs = await kb_access.resolve_query_kbs(db, user, [granted_kb.id, denied_kb.id, public_kb.id])

    # Then: 未授权的库被过滤，且保持请求顺序
    assert [kb.id for kb in actual_kbs] == [granted_kb.id, public_kb.id]


@pytest.mark.asyncio
async def test_resolve_query_kbs_empty_request_returns_all_allowed(db):
    # Given
    public_kb = make_kb("公开库-resolve-empty")
    user = make_user("frank-empty")
    db.add_all([public_kb, user])
    await db.flush()

    # When
    actual_kbs = await kb_access.resolve_query_kbs(db, user, [])

    # Then
    assert [kb.id for kb in actual_kbs] == [public_kb.id]


@pytest.mark.asyncio
async def test_resolve_query_kbs_no_allowed_kbs_raises_403(db):
    # Given
    private_kb = make_kb("私有库-resolve-403", is_public=False)
    user = make_user("grace-403")
    db.add_all([private_kb, user])
    await db.flush()

    # When / Then
    with pytest.raises(HTTPException) as exc:
        await kb_access.resolve_query_kbs(db, user, [])
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_kb_versions_maps_kb_id_to_version(db):
    # Given
    kb = make_kb("版本库-versions")
    db.add(kb)
    await db.flush()

    # When
    actual_versions = await kb_access.kb_versions(db, [kb])

    # Then
    assert actual_versions == {kb.id: kb.version}


# ---------- kb_stats.recalc_kb_counts ----------


@pytest.mark.asyncio
async def test_recalc_kb_counts_counts_ready_docs_and_child_chunks(db):
    # Given
    kb = make_kb("统计库-recalc")
    db.add(kb)
    await db.flush()
    ready_doc = make_doc(kb.id, status="ready")
    ready_doc2 = make_doc(kb.id, status="ready")
    pending_doc = make_doc(kb.id, status="pending")
    deleted_doc = make_doc(kb.id, status="ready", deleted=True)
    db.add_all([ready_doc, ready_doc2, pending_doc, deleted_doc])
    await db.flush()
    db.add_all(
        [
            make_chunk(kb.id, ready_doc.id, chunk_type="child"),
            make_chunk(kb.id, ready_doc.id, chunk_type="child"),
            make_chunk(kb.id, ready_doc.id, chunk_type="parent"),
            make_chunk(kb.id, pending_doc.id, chunk_type="child"),
        ]
    )
    await db.flush()
    original_version = kb.version
    original_updated_at = kb.updated_at

    # When
    await kb_stats.recalc_kb_counts(db, kb)

    # Then: 只统计 ready 且未软删除的文档；只统计 child 分块
    assert kb.doc_count == 2
    assert kb.chunk_count == 3
    assert kb.version == original_version + 1
    assert kb.updated_at != original_updated_at


# ---------- cache: put/get ----------

SCOPE = scope_key(["kb1"])


@pytest.mark.asyncio
async def test_get_cached_exact_hit_returns_answer_and_counts_hit(db):
    # Given
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "8888 元", [{"rank": 1}], {"kb1": 2})

    # When
    actual = await cache_service.get_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], {"kb1": 2})

    # Then
    assert actual["answer"] == "8888 元"
    assert actual["similarity"] == pytest.approx(1.0)
    assert actual["citations"] == [{"rank": 1}]
    row = (await db.execute(select(SemanticCache))).scalar_one()
    assert row.hit_count == 1
    assert row.last_hit_at is not None


@pytest.mark.asyncio
async def test_get_cached_fuzzy_hit_within_threshold(db):
    # Given: 相同向量、不同问题文本 → 精确键未命中，走模糊匹配
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "8888 元", [], {"kb1": 2})

    # When
    actual = await cache_service.get_cached(db, SCOPE, "X9的价格是多少", [1.0, 0.0], {"kb1": 2})

    # Then
    assert actual is not None
    assert actual["answer"] == "8888 元"
    assert actual["similarity"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_get_cached_skips_rows_with_different_kb_versions(db):
    # Given
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "8888 元", [], {"kb1": 2})

    # When: kb 版本不一致的候选行必须被跳过
    actual = await cache_service.get_cached(db, SCOPE, "X9的价格是多少", [1.0, 0.0], {"kb1": 3})

    # Then
    assert actual is None


@pytest.mark.asyncio
async def test_get_cached_expired_entry_returns_none(db):
    # Given
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "8888 元", [], {"kb1": 2})
    row = (await db.execute(select(SemanticCache))).scalar_one()
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    await db.flush()

    # When
    actual = await cache_service.get_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], {"kb1": 2})

    # Then
    assert actual is None


@pytest.mark.asyncio
async def test_get_cached_returns_none_when_cache_disabled(db, monkeypatch):
    # Given
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "8888 元", [], {"kb1": 2})
    monkeypatch.setattr(settings, "cache_enabled", False)

    # When
    actual = await cache_service.get_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], {"kb1": 2})

    # Then
    assert actual is None


@pytest.mark.asyncio
async def test_put_cached_blank_answer_not_stored(db):
    # When
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "   ", [], {"kb1": 2})

    # Then
    rows = (await db.execute(select(SemanticCache))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_put_cached_duplicate_key_stores_once(db):
    # When
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "第一次", [], {"kb1": 2})
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "第二次", [], {"kb1": 2})

    # Then
    rows = (await db.execute(select(SemanticCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].answer == "第一次"


# ---------- cache: maintenance ----------


@pytest.mark.asyncio
async def test_purge_expired_removes_only_expired(db):
    # Given
    await cache_service.put_cached(db, SCOPE, "有效问题", [1.0, 0.0], "有效答案", [], {"kb1": 2})
    await cache_service.put_cached(db, SCOPE, "过期问题", [0.0, 1.0], "过期答案", [], {"kb1": 2})
    rows = (await db.execute(select(SemanticCache))).scalars().all()
    expired_row = next(row for row in rows if row.query_text == "过期问题")
    expired_row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    await db.flush()

    # When
    actual_removed = await cache_service.purge_expired(db)

    # Then
    assert actual_removed == 1
    remaining = (await db.execute(select(SemanticCache))).scalars().all()
    assert [row.query_text for row in remaining] == ["有效问题"]


@pytest.mark.asyncio
async def test_clear_all_removes_everything(db):
    # Given
    await cache_service.put_cached(db, SCOPE, "问题一", [1.0, 0.0], "答案一", [], {"kb1": 2})
    await cache_service.put_cached(db, SCOPE, "问题二", [0.0, 1.0], "答案二", [], {"kb1": 2})

    # When
    actual_removed = await cache_service.clear_all(db)

    # Then
    assert actual_removed == 2
    rows = (await db.execute(select(SemanticCache))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_cache_stats_returns_entries_and_hits(db):
    # Given: 一条记录，命中一次
    await cache_service.put_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], "8888 元", [], {"kb1": 2})
    await cache_service.get_cached(db, SCOPE, "星辰X9多少钱", [1.0, 0.0], {"kb1": 2})

    # When
    actual_stats = await cache_service.cache_stats(db)

    # Then
    assert actual_stats == {"entries": 1, "hits": 1}
