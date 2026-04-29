import logging
import time

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from app.llm.local_llm import get_llm
from app.rag.prompt import rag_prompt

logger = logging.getLogger(__name__)

# 格式化文档列表为RAG系统提示所需的上下文字符串
def format_documents_for_context(documents: list[Document]) -> str:
    formatted_chunks = []

    # 为每个文档添加来源信息和内容，构建上下文字符串
    for index, document in enumerate(documents, start=1):
        # 从文档的metadata中提取source和page信息，如果没有则使用默认值
        source = document.metadata.get("source", "unknown")
        page = document.metadata.get("page")

        # 构建每个文档的上下文块，包含来源信息和文档内容
        header = f"[Source {index}] source={source}"
        if page is not None:
            header += f", page={page}"

        # 将文档的上下文块添加到格式化列表中
        formatted_chunks.append(
            f"{header}\n{document.page_content}"
        )

    return "\n\n".join(formatted_chunks)


def generate_answer(question: str, documents: list[Document]) -> str:
    # 获取本地部署的LLM模型实例
    llm = get_llm()
    # 将文档列表格式化为RAG系统提示所需的上下文字符串
    step4_start = time.perf_counter()
    logger.info("[RAG][STEP 4] prompt 构建开始")
    context = format_documents_for_context(documents)

    # 构建RAG系统提示链，将提示模板、LLM模型和输出解析器组合在一起
    chain = rag_prompt | llm | StrOutputParser()
    logger.info("[RAG][STEP 4] prompt 构建完成，耗时 %.3fs", time.perf_counter() - step4_start)

    # 调用链来生成答案，传入用户问题和格式化后的上下文字符串
    step5_start = time.perf_counter()
    logger.info("[RAG][STEP 5] LLM 调用开始")
    answer = chain.invoke(
        {
            "question": question,
            "context": context,
        }
    )
    logger.info("[RAG][STEP 5] LLM 调用完成，耗时 %.3fs", time.perf_counter() - step5_start)

    return answer