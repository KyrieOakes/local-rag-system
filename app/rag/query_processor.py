"""
查询预处理器 + RAG 路由门控模块。

在向量检索之前，通过 LLM 完成三项任务：
1. 路由决策（Routing）：判断查询是否需要检索文档库，还是可以直接回答
2. 意图检测（Intent Detection）：分类查询意图
3. 查询改写（Query Rewrite）：将模糊查询改写为适合向量检索的清晰表述

两层路由：
- Layer 0 — 关键词预过滤（零 LLM 调用）：问候语、致谢、告别、元问题直接返回
- Layer 1 — LLM 统一路由：单次 LLM 调用同时完成路由决策 + 意图检测 + 改写/直接回答

process_query() 返回：
{
    "needs_rag": bool,
    "intent": str,
    "rewritten_query": str | None,
    "direct_answer": str | None,
}
"""

import logging
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.llm.local_llm import get_llm

logger = logging.getLogger(__name__)

# Layer 0: 关键词预过滤 — 零成本拦截明显不需要 RAG 的查询
# Each tuple: (pattern, category) — category maps to GREETING_RESPONSES key
GREETING_RULES = [
    # category: "greeting"
    (r"^(hi|hello|hey|yo|sup|good morning|good evening|good afternoon)[\s!.,]*$", "greeting"),
    (r"^(how are you|what'?s up|howdy|how are things|how'?s it going)[\s!.?,]*$", "greeting"),
    (r"^(你好|您好|嗨|哈喽|早上好|晚上好|下午好)[\s!！。，]*$", "greeting"),
    # category: "thanks"
    (r"^(thanks|thank you|thx|ok|okay|got it|nice|great|cool|awesome|perfect)[\s!.?,]*$", "thanks"),
    (r"^(谢谢|多谢|感谢|好的|OK|明白了|知道了|懂了|收到)[\s!！。，]*$", "thanks"),
    # category: "goodbye"
    (r"^(bye|goodbye|see you|cya|later|good night|night)[\s!.?,]*$", "goodbye"),
    (r"^(再见|拜拜|回头见|晚安|明天见)[\s!！。，]*$", "goodbye"),
    # category: "meta"
    (r"^(who are you|what are you|what can you do|help|what do you do|how do you work|what are your capabilities)[\s!.?,]*$", "meta"),
    (r"^(你是谁|你能做什么|你有什么功能|你怎么用|帮助)[\s!！。，?？]*$", "meta"),
]

GREETING_RESPONSES = {
    "greeting": "Hello! I'm your local RAG assistant. I can help you search through your documents and answer questions based on their content. What would you like to know?",
    "thanks": "You're welcome! Let me know if you have more questions.",
    "goodbye": "Goodbye! Feel free to come back anytime you need to search your documents.",
    "meta": "I'm a local RAG (Retrieval-Augmented Generation) assistant. I can search through your uploaded documents and answer questions grounded in their content. Just ask me anything about your knowledge base!",
}

QUERY_PROCESSING_SYSTEM_PROMPT = """\
Analyze the user query for a RAG system. Perform routing first, then act accordingly.

ROUTING rules:
- YES: default choice. The query likely relates to content in the knowledge base (technical topics, documents, projects, concepts, facts, how-to questions, comparisons, explanations). When in doubt, route to RAG.
- NO: ONLY when the query is clearly NOT about any document content — pure greetings, simple chitchat ("how are you", "what's your name"), or meta-questions about the system itself ("what can you do", "who are you").

If ROUTING=YES, also classify INTENT: question_answering | summarization | comparison | fact_lookup, then rewrite the query for vector search (expand vague terms, add precise keywords).

If ROUTING=NO, provide a concise, helpful direct answer.

Output format:
ROUTING: YES|NO
[if YES] INTENT: <intent>
[if YES] QUERY: <rewritten query>
[if NO] ANSWER: <direct reply>"""

_query_processing_prompt = ChatPromptTemplate.from_messages([
    ("system", QUERY_PROCESSING_SYSTEM_PROMPT),
    ("human", "{question}"),
])


def _check_greeting(question: str) -> dict | None:
    """Layer 0: keyword pre-filter for obvious non-RAG queries. Returns None if no match."""
    normalized = question.strip().lower()
    for pattern, category in GREETING_RULES:
        if re.match(pattern, normalized, re.IGNORECASE):
            return {
                "needs_rag": False,
                "intent": "chitchat",
                "rewritten_query": None,
                "direct_answer": GREETING_RESPONSES[category],
            }
    return None


def _format_history(history: list) -> str:
    """Format recent conversation history for prompt injection."""
    if not history:
        return ""
    lines = []
    for msg in history:
        role_label = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{role_label}: {msg.content}")
    return "\n".join(lines)


def process_query(question: str, history: list | None = None) -> dict:
    """
    Process the user query — route, detect intent, rewrite or answer directly.

    Returns {"needs_rag": bool, "intent": str, "rewritten_query": str|None, "direct_answer": str|None}.
    """
    history = history or []

    # Layer 0: keyword pre-filter
    greeting_result = _check_greeting(question)
    if greeting_result:
        logger.info("Query routed by keyword pre-filter — no LLM call needed")
        return greeting_result

    try:
        llm = get_llm()
        chain = _query_processing_prompt | llm | StrOutputParser()

        history_text = _format_history(history)
        if history_text:
            invoke_input = {
                "question": f"Previous conversation:\n{history_text}\n\nCurrent question: {question}"
            }
        else:
            invoke_input = {"question": question}

        response = chain.invoke(invoke_input)

        needs_rag = False
        intent = "unknown"
        rewritten_query = None
        direct_answer = None

        for line in response.strip().split("\n"):
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("ROUTING:"):
                needs_rag = stripped.split(":", 1)[1].strip().upper() == "YES"
            elif upper.startswith("INTENT:"):
                intent = stripped.split(":", 1)[1].strip()
            elif upper.startswith("QUERY:"):
                rewritten_query = stripped.split(":", 1)[1].strip()
            elif upper.startswith("ANSWER:"):
                direct_answer = stripped.split(":", 1)[1].strip()

        if needs_rag and not rewritten_query:
            rewritten_query = question

        logger.info(
            "Query processed — needs_rag=%s, intent=%s, rewritten='%s'",
            needs_rag, intent, rewritten_query,
        )
        return {
            "needs_rag": needs_rag,
            "intent": intent,
            "rewritten_query": rewritten_query,
            "direct_answer": direct_answer,
        }

    except Exception as exc:
        logger.warning("Query processing failed, falling back to direct answer: %s", exc)
        return {
            "needs_rag": False,
            "intent": "unknown",
            "rewritten_query": question,
            "direct_answer": "Sorry, I encountered an error processing your query. Could you try again?",
        }
