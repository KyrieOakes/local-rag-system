"""
查询预处理器模块（RAG 流水线第 2 步前半部分）。

在向量检索之前，通过 LLM 对用户原始查询进行两项处理：
1. 意图检测（Intent Detection）：分类为 question_answering / summarization /
   comparison / fact_lookup 之一
2. 查询改写（Query Rewrite）：将模糊/口语化的查询改写为更适合向量检索的清晰表述，
   扩展模糊术语，使用文档中可能出现的精确关键词

process_query() 返回 {"intent": str, "rewritten_query": str}。
如果 LLM 调用失败，回退到原始查询（intent="unknown", rewritten_query=原始问题）。
"""

import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.llm.local_llm import get_llm

logger = logging.getLogger(__name__)

QUERY_PROCESSING_SYSTEM_PROMPT = """
You are a query processing assistant for a RAG (Retrieval-Augmented Generation) system.

Analyze the user's query and perform two tasks:

1. Intent Detection: classify the query into one of these categories:
   - question_answering: asking a specific question
   - summarization: requesting a summary or overview
   - comparison: comparing topics, documents, or ideas
   - fact_lookup: looking up a specific fact or piece of information

2. Query Rewrite: rewrite the original query to be clearer and more suitable for vector database retrieval.
   - Expand vague or ambiguous terms
   - Use specific keywords likely to appear in documents
   - Preserve the original meaning and language

Output exactly two lines (no extra text):
INTENT: <intent>
QUERY: <rewritten query>
"""

_query_processing_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", QUERY_PROCESSING_SYSTEM_PROMPT),
        ("human", "{question}"),
    ]
)


def process_query(question: str) -> dict:
    """
    Process the user query before retrieval — detect intent and rewrite.

    Returns {"intent": str, "rewritten_query": str}.
    Falls back to the original query on any failure.
    """
    try:
        llm = get_llm()
        chain = _query_processing_prompt | llm | StrOutputParser()
        response = chain.invoke({"question": question})

        intent = "unknown"
        rewritten_query = question

        for line in response.strip().split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith("INTENT:"):
                intent = stripped.split(":", 1)[1].strip()
            elif stripped.upper().startswith("QUERY:"):
                rewritten_query = stripped.split(":", 1)[1].strip()

        if not rewritten_query:
            rewritten_query = question

        logger.info(
            "Query processed — intent=%s, rewritten='%s'",
            intent,
            rewritten_query,
        )
        return {"intent": intent, "rewritten_query": rewritten_query}

    except Exception as exc:
        logger.warning(
            "Query processing failed, falling back to original query: %s",
            exc,
        )
        return {"intent": "unknown", "rewritten_query": question}
