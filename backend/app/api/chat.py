"""Conversations, streaming RAG chat, citations and feedback."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.metrics import CACHE_HITS, FEEDBACK_COUNT, RAG_ANSWERS, RAG_STAGE_LATENCY
from app.core.rate_limit import limiter
from app.db.models import (
    Conversation,
    Feedback,
    Message,
    MessageCitation,
    User,
    utcnow,
)
from app.db.session import get_db
from app.rag.answer import stream_mock_answer
from app.rag.chain import stream_llm_answer
from app.rag.citations import extract_used_indices
from app.rag.embeddings import approx_token_count, get_embedding_provider
from app.rag.retriever import build_context, retrieve
from app.rag.rewrite import normalize_query, rewrite_query
from app.schemas import (
    ChatIn,
    CitationOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    FeedbackIn,
    MessageOut,
)
from app.services.cache import get_cached, put_cached, scope_key
from app.services.kb_access import resolve_query_kbs

router = APIRouter(tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _own_conversation(db: AsyncSession, user: User, conversation_id: str) -> Conversation:
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
        )
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return conv


# ---------------- conversation CRUD ----------------
@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kbs = await resolve_query_kbs(db, user, payload.kb_ids) if payload.kb_ids else []
    conv = Conversation(
        user_id=user.id,
        title=payload.title or "新会话",
        kb_ids=[kb.id for kb in kbs] if kbs else [],
    )
    db.add(conv)
    await db.commit()
    return conv


@router.get("/conversations")
async def list_conversations(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Conversation).where(Conversation.user_id == user.id, Conversation.deleted_at.is_(None))
    count_stmt = select(func.count(Conversation.id)).where(
        Conversation.user_id == user.id, Conversation.deleted_at.is_(None)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Conversation.title.like(like))
        count_stmt = count_stmt.where(Conversation.title.like(like))
    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(Conversation.last_message_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [ConversationOut.model_validate(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _own_conversation(db, user, conversation_id)
    if payload.title is not None:
        conv.title = payload.title.strip() or conv.title
    if payload.kb_ids is not None:
        kbs = await resolve_query_kbs(db, user, payload.kb_ids) if payload.kb_ids else []
        conv.kb_ids = [kb.id for kb in kbs]
    if payload.is_archived is not None:
        conv.is_archived = payload.is_archived
    conv.updated_at = utcnow()
    await db.commit()
    return conv


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _own_conversation(db, user, conversation_id)
    conv.deleted_at = utcnow()
    await db.commit()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _own_conversation(db, user, conversation_id)
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq, Message.created_at)
        )
    ).scalars().all()
    message_ids = [m.id for m in rows]
    citations_map: dict[str, list[MessageCitation]] = {}
    feedback_map: dict[str, int] = {}
    if message_ids:
        citation_rows = (
            await db.execute(
                select(MessageCitation)
                .where(MessageCitation.message_id.in_(message_ids))
                .order_by(MessageCitation.rank)
            )
        ).scalars().all()
        for c in citation_rows:
            citations_map.setdefault(c.message_id, []).append(c)
        feedback_rows = (
            await db.execute(
                select(Feedback.message_id, Feedback.rating).where(
                    Feedback.message_id.in_(message_ids), Feedback.user_id == user.id
                )
            )
        ).all()
        feedback_map = {mid: int(rating) for mid, rating in feedback_rows}

    items: list[MessageOut] = []
    for msg in rows:
        item = MessageOut.model_validate(msg)
        item.citations = [CitationOut.model_validate(c) for c in citations_map.get(msg.id, [])]
        item.feedback = feedback_map.get(msg.id)
        items.append(item)
    return {"conversation": ConversationOut.model_validate(conv), "items": items}


@router.get("/messages/{message_id}/citations", response_model=list[CitationOut])
async def message_citations(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    await _own_conversation(db, user, msg.conversation_id)
    rows = (
        await db.execute(
            select(MessageCitation).where(MessageCitation.message_id == message_id).order_by(MessageCitation.rank)
        )
    ).scalars().all()
    return [CitationOut.model_validate(c) for c in rows]


@router.post("/messages/{message_id}/feedback")
async def upsert_feedback(
    message_id: str,
    payload: FeedbackIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if not msg or msg.role != "assistant":
        raise HTTPException(status_code=404, detail="回答消息不存在")
    await _own_conversation(db, user, msg.conversation_id)
    existing = await db.scalar(
        select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user.id)
    )
    if existing:
        existing.rating = payload.rating
        existing.reason_code = payload.reason_code
        existing.comment = payload.comment
    else:
        db.add(
            Feedback(
                message_id=message_id,
                user_id=user.id,
                rating=payload.rating,
                reason_code=payload.reason_code,
                comment=payload.comment,
            )
        )
    await db.commit()
    FEEDBACK_COUNT.labels("up" if payload.rating == 1 else "down").inc()
    return {"ok": True}


@router.delete("/messages/{message_id}/feedback")
async def delete_feedback(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    await _own_conversation(db, user, msg.conversation_id)
    row = await db.scalar(
        select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user.id)
    )
    if row:
        await db.delete(row)
        await db.commit()
    return {"ok": True}


# ---------------- streaming chat ----------------
@router.post("/chat/stream")
async def chat_stream(
    payload: ChatIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await limiter.hit(f"chat:{user.id}", settings.rate_limit_chat_per_min)
    question = normalize_query(payload.question)
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    conv: Conversation | None = None
    if payload.conversation_id:
        conv = await _own_conversation(db, user, payload.conversation_id)

    requested_kbs = payload.kb_ids or (conv.kb_ids if conv else [])
    kbs = await resolve_query_kbs(db, user, requested_kbs)
    kb_ids = [kb.id for kb in kbs]
    kb_versions_map = {kb.id: kb.version for kb in kbs}

    if conv is not None:
        conv.kb_ids = kb_ids
    else:
        conv = Conversation(user_id=user.id, title="新会话", kb_ids=kb_ids)
        db.add(conv)
        await db.flush()

    history_rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.status.in_(["complete", "failed"]))
            .order_by(Message.seq.desc(), Message.created_at.desc())
            .limit(6)
        )
    ).scalars().all()
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(history_rows)
        if m.role in {"user", "assistant"} and m.content
    ]

    if conv.title in {"新会话", ""}:
        conv.title = question[:30]

    max_seq = int(await db.scalar(select(func.max(Message.seq)).where(Message.conversation_id == conv.id)) or 0)
    user_msg = Message(
        conversation_id=conv.id, role="user", content=question, status="complete", seq=max_seq + 1
    )
    assistant = Message(
        conversation_id=conv.id,
        role="assistant",
        content="",
        status="streaming",
        seq=max_seq + 2,
        model=settings.chat_model if settings.use_dashscope else "mock-extractive",
    )
    db.add(user_msg)
    db.add(assistant)
    conv.message_count += 2
    conv.last_message_at = utcnow()
    await db.flush()
    conv_id = conv.id
    user_msg_id = user_msg.id
    assistant_id = assistant.id
    await db.commit()

    async def generate():
        started = time.perf_counter()
        parts: list[str] = []
        sources_payload: list[dict] = []
        cache_hit = False
        try:
            yield _sse(
                "meta",
                {
                    "conversation_id": conv_id,
                    "conversation_title": conv.title,
                    "user_message_id": user_msg_id,
                    "message_id": assistant_id,
                    "kb_ids": kb_ids,
                    "llm_mode": settings.effective_llm_mode,
                    "cache_hit": False,
                },
            )
            yield _sse("stage", {"stage": "正在理解问题与检索知识库"})

            provider = get_embedding_provider()
            scope = scope_key(kb_ids)
            t_embed = time.perf_counter()
            original_vector = await provider.embed_query(question)
            RAG_STAGE_LATENCY.labels("embed_query").observe(time.perf_counter() - t_embed)

            cached = None
            if payload.use_cache:
                cached = await get_cached(db, scope, question, original_vector, kb_versions_map)
            if cached:
                cache_hit = True
                CACHE_HITS.labels("semantic").inc()
                answer = cached["answer"]
                sources_payload = cached["citations"]
                yield _sse(
                    "cache",
                    {
                        "hit": True,
                        "similarity": round(float(cached.get("similarity", 1.0)), 4),
                        "cached_question": cached.get("query_text", ""),
                    },
                )
                yield _sse("sources", {"sources": sources_payload, "rewritten_query": question, "from_cache": True})
                for i in range(0, len(answer), 12):
                    parts.append(answer[i : i + 12])
                    yield _sse("token", {"delta": answer[i : i + 12]})
                    await asyncio.sleep(0.004)
                used = [c.get("rank") for c in sources_payload if c.get("used")]
                await _persist_citations(db, assistant_id, sources_payload)
                await _finish_message(
                    db,
                    assistant_id=assistant_id,
                    conv_id=conv_id,
                    answer=answer,
                    model=cached.get("model") or settings.chat_model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    retrieval_meta={"cache_hit": True, "similarity": cached.get("similarity"), "llm_mode": "cache"},
                )
                RAG_ANSWERS.labels(mode="cache", cache_hit="true", status="ok").inc()
                yield _sse(
                    "usage",
                    {
                        "prompt_tokens": 0,
                        "completion_tokens": approx_token_count(answer),
                        "total_tokens": approx_token_count(answer),
                    },
                )
                yield _sse(
                    "done",
                    {
                        "message_id": assistant_id,
                        "conversation_id": conv_id,
                        "cache_hit": True,
                        "used_citations": used,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                        "llm_mode": "cache",
                    },
                )
                return

            t_rewrite = time.perf_counter()
            rewritten, keywords, did_rewrite = await rewrite_query(question, history)
            RAG_STAGE_LATENCY.labels("rewrite").observe(time.perf_counter() - t_rewrite)
            if rewritten == question:
                query_vector = original_vector
            else:
                query_vector = await provider.embed_query(rewritten)

            t_retrieve = time.perf_counter()
            sources, retrieval_meta = await retrieve(db, kb_versions_map, rewritten, query_vector)
            RAG_STAGE_LATENCY.labels("retrieve").observe(time.perf_counter() - t_retrieve)
            if did_rewrite:
                yield _sse("rewrite", {"rewritten_query": rewritten, "keywords": keywords})

            sources_payload = [s.to_citation_payload() for s in sources]
            context, used_sources = build_context(sources)
            yield _sse(
                "sources",
                {
                    "sources": sources_payload,
                    "rewritten_query": rewritten,
                    "keywords": keywords,
                    "retrieval_meta": retrieval_meta,
                },
            )
            yield _sse("stage", {"stage": "正在生成回答"})

            t_gen = time.perf_counter()
            if settings.use_dashscope and context:
                from app.rag.rewrite import _history_text

                stream = stream_llm_answer(question, context, _history_text(history))
            else:
                stream = stream_mock_answer(question, used_sources)
            async for delta in stream:
                if not delta:
                    continue
                parts.append(delta)
                yield _sse("token", {"delta": delta})
            RAG_STAGE_LATENCY.labels("generate").observe(time.perf_counter() - t_gen)

            answer = "".join(parts).strip()
            used_indices = extract_used_indices(answer, len(sources_payload))
            for item in sources_payload:
                item["used"] = item["rank"] in used_indices
            await _persist_citations(db, assistant_id, sources_payload)

            if sources and not retrieval_meta.get("rerank_degraded") and answer:
                await put_cached(
                    db, scope, question, original_vector, answer, sources_payload, kb_versions_map
                )

            prompt_tokens = approx_token_count(context) + approx_token_count(question)
            completion_tokens = approx_token_count(answer)
            await _finish_message(
                db,
                assistant_id=assistant_id,
                conv_id=conv_id,
                answer=answer,
                model=settings.chat_model if settings.use_dashscope else "mock-extractive",
                latency_ms=int((time.perf_counter() - started) * 1000),
                retrieval_meta={
                    "cache_hit": False,
                    "rewritten_query": rewritten,
                    "keywords": keywords,
                    "sources": len(sources),
                    "rerank_degraded": retrieval_meta.get("rerank_degraded", False),
                    "llm_mode": settings.effective_llm_mode,
                },
                usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            )
            RAG_ANSWERS.labels(mode=settings.effective_llm_mode, cache_hit="false", status="ok").inc()
            yield _sse(
                "usage",
                {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            )
            yield _sse(
                "done",
                {
                    "message_id": assistant_id,
                    "conversation_id": conv_id,
                    "cache_hit": False,
                    "used_citations": used_indices,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "llm_mode": settings.effective_llm_mode,
                    "rerank_degraded": retrieval_meta.get("rerank_degraded", False),
                },
            )
        except asyncio.CancelledError:
            await _fail_message(db, assistant_id, "".join(parts), "客户端已断开")
            RAG_ANSWERS.labels(mode=settings.effective_llm_mode, cache_hit=str(cache_hit).lower(), status="cancelled").inc()
            raise
        except Exception as exc:  # noqa: BLE001
            await _fail_message(db, assistant_id, "".join(parts), str(exc))
            RAG_ANSWERS.labels(mode=settings.effective_llm_mode, cache_hit=str(cache_hit).lower(), status="error").inc()
            yield _sse("error", {"message": f"生成回答失败：{exc}", "message_id": assistant_id})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _persist_citations(db: AsyncSession, message_id: str, sources: list[dict]) -> None:
    for item in sources:
        db.add(
            MessageCitation(
                message_id=message_id,
                chunk_id=item.get("chunk_id"),
                document_id=item.get("document_id"),
                kb_id=item.get("kb_id"),
                rank=int(item.get("rank", 0)),
                dense_score=item.get("dense_score"),
                sparse_score=item.get("sparse_score"),
                rerank_score=item.get("rerank_score"),
                snippet=item.get("snippet", ""),
                doc_title=item.get("doc_title", ""),
                locator=item.get("locator") or {},
                used=bool(item.get("used", False)),
            )
        )
    await db.flush()


async def _finish_message(
    db: AsyncSession,
    assistant_id: str,
    conv_id: str,
    answer: str,
    model: str,
    latency_ms: int,
    retrieval_meta: dict,
    usage: dict | None = None,
) -> None:
    msg = await db.get(Message, assistant_id)
    if msg:
        msg.content = answer
        msg.status = "complete"
        msg.model = model
        msg.latency_ms = latency_ms
        msg.retrieval_meta = retrieval_meta
        msg.token_usage = usage or {}
    conv = await db.get(Conversation, conv_id)
    if conv:
        conv.last_message_at = utcnow()
    await db.commit()


async def _fail_message(db: AsyncSession, assistant_id: str, partial: str, error: str) -> None:
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass
    try:
        msg = await db.get(Message, assistant_id)
        if msg:
            msg.content = partial
            msg.status = "failed"
            msg.retrieval_meta = {**(msg.retrieval_meta or {}), "error": error[:500]}
            await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
