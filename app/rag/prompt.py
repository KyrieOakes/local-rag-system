from langchain_core.prompts import ChatPromptTemplate


RAG_SYSTEM_PROMPT = """
You are a helpful RAG assistant.

Use ONLY the provided context to answer the user's question.
If the answer is not in the context, say you don't know based on the provided documents.

Requirements:
- Answer in the same language as the user question.
- Be concise but accurate.
- Do not make up facts.
- Mention relevant source names when useful.

Context:
{context}
"""

# 定义RAG系统提示模板
rag_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", RAG_SYSTEM_PROMPT),
        ("human", "{question}"),# 这里是用户输入的问题占位符
    ]
)