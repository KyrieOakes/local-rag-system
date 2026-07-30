"""Answer-generation chain consuming pre-budgeted memory and documents."""

import logging
import time

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from app.llm.local_llm import get_llm
from app.rag.context_manager import (
    format_documents_for_context,
    format_memory_for_prompt,
)
from app.rag.prompt import rag_prompt

logger = logging.getLogger(__name__)

def _build_chain_input(
    question: str,
    documents: list[Document],
    history: list,
    conversation_summary: str = "",
) -> dict:
    """Build the input dict for the LangChain RAG chain."""
    context = format_documents_for_context(documents)
    history_text = format_memory_for_prompt(conversation_summary, history)
    return {
        "question": question,
        "context": context,
        "history": history_text,
    }


def generate_answer(
    question: str,
    documents: list[Document],
    history: list | None = None,
    conversation_summary: str = "",
) -> str:
    history = history or []
    llm = get_llm()

    step4_start = time.perf_counter()
    logger.info("[RAG][STEP 4] prompt 构建开始")
    chain_input = _build_chain_input(
        question,
        documents,
        history,
        conversation_summary,
    )

    chain = rag_prompt | llm | StrOutputParser()
    logger.info("[RAG][STEP 4] prompt 构建完成，耗时 %.3fs", time.perf_counter() - step4_start)

    step5_start = time.perf_counter()
    logger.info("[RAG][STEP 5] LLM 调用开始")
    answer = chain.invoke(chain_input)
    logger.info("[RAG][STEP 5] LLM 调用完成，耗时 %.3fs", time.perf_counter() - step5_start)

    return answer


async def generate_answer_stream(
    question: str,
    documents: list[Document],
    history: list | None = None,
    conversation_summary: str = "",
):
    """Async generator that yields answer tokens one at a time via SSE."""
    history = history or []
    llm = get_llm()

    logger.info("[RAG][STEP 4] prompt 构建开始 (streaming)")
    chain_input = _build_chain_input(
        question,
        documents,
        history,
        conversation_summary,
    )

    chain = rag_prompt | llm | StrOutputParser()
    logger.info("[RAG][STEP 4] prompt 构建完成 (streaming)")

    logger.info("[RAG][STEP 5] LLM streaming 开始")
    async for token in chain.astream(chain_input):
        yield token
    logger.info("[RAG][STEP 5] LLM streaming 完成")
