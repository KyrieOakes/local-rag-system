"""
RAG 答案生成模块（Chain）。

负责 RAG 流水线的第 4-5 步：
1. format_documents_for_context() — 将检索到的文档列表格式化为 LLM 提示词所需的上下文字符串
2. _format_history() — 将对话历史格式化为提示词所需的历史字符串（最多 2048 token 预算）
3. generate_answer() — 构建 LangChain 链（rag_prompt | llm | StrOutputParser），调用 LLM 生成答案
"""

import logging
import time

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from app.llm.local_llm import get_llm
from app.rag.prompt import rag_prompt

logger = logging.getLogger(__name__)

MAX_HISTORY_TOKENS = 2048


def format_documents_for_context(documents: list[Document]) -> str:
    """Format retrieved documents into a context string with source headers."""
    formatted_chunks = []

    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("source", "unknown")
        page = document.metadata.get("page")

        header = f"[Source {index}] source={source}"
        if page is not None:
            header += f", page={page}"

        formatted_chunks.append(f"{header}\n{document.page_content}")

    return "\n\n".join(formatted_chunks)


def _format_history(history: list) -> str:
    """Format conversation history for the RAG prompt, capped at ~2048 tokens."""
    if not history:
        return ""

    formatted = []
    token_estimate = 0

    for msg in reversed(history):
        role_label = "User" if msg.role == "user" else "Assistant"
        line = f"{role_label}: {msg.content}"
        estimated = len(line) // 3  # rough char-to-token heuristic
        if token_estimate + estimated > MAX_HISTORY_TOKENS:
            break
        formatted.insert(0, line)
        token_estimate += estimated

    return "Previous conversation:\n" + "\n".join(formatted)


def _build_chain_input(question: str, documents: list[Document], history: list) -> dict:
    """Build the input dict for the LangChain RAG chain."""
    context = format_documents_for_context(documents)
    history_text = _format_history(history)
    return {
        "question": question,
        "context": context,
        "history": history_text,
    }


def generate_answer(question: str, documents: list[Document], history: list | None = None) -> str:
    history = history or []
    llm = get_llm()

    step4_start = time.perf_counter()
    logger.info("[RAG][STEP 4] prompt 构建开始")
    chain_input = _build_chain_input(question, documents, history)

    chain = rag_prompt | llm | StrOutputParser()
    logger.info("[RAG][STEP 4] prompt 构建完成，耗时 %.3fs", time.perf_counter() - step4_start)

    step5_start = time.perf_counter()
    logger.info("[RAG][STEP 5] LLM 调用开始")
    answer = chain.invoke(chain_input)
    logger.info("[RAG][STEP 5] LLM 调用完成，耗时 %.3fs", time.perf_counter() - step5_start)

    return answer


async def generate_answer_stream(question: str, documents: list[Document], history: list | None = None):
    """Async generator that yields answer tokens one at a time via SSE."""
    history = history or []
    llm = get_llm()

    logger.info("[RAG][STEP 4] prompt 构建开始 (streaming)")
    chain_input = _build_chain_input(question, documents, history)

    chain = rag_prompt | llm | StrOutputParser()
    logger.info("[RAG][STEP 4] prompt 构建完成 (streaming)")

    logger.info("[RAG][STEP 5] LLM streaming 开始")
    async for token in chain.astream(chain_input):
        yield token
    logger.info("[RAG][STEP 5] LLM streaming 完成")
