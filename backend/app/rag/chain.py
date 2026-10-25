"""
LangChain LCEL answer chain with streaming.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.rag.prompts import HUMAN_TEMPLATE, NO_CONTEXT_ANSWER, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def get_chat_model(streaming: bool = True) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        temperature=0.2,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
        streaming=streaming,
    )


def build_rag_chain():
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", HUMAN_TEMPLATE),
        ]
    )
    return prompt | get_chat_model(streaming=True) | StrOutputParser()


async def stream_llm_answer(question: str, context: str, history_text: str) -> AsyncIterator[str]:
    if not context.strip():
        yield NO_CONTEXT_ANSWER
        return
    chain = build_rag_chain()
    async for delta in chain.astream(
        {"question": question, "context": context, "history": history_text},
        config={"run_name": "rag_answer"},
    ):
        if delta:
            yield str(delta)
