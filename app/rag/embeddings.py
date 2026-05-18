"""
嵌入模型模块。

提供 LoggingOpenAIEmbeddings 类（继承自 LangChain 的 OpenAIEmbeddings），
在 embed_query() 调用时自动记录耗时日志。

get_embedding_model() 工厂函数返回配置好的嵌入模型实例，
连接地址和模型名从 settings 读取（默认指向本地 LM Studio 的 text-embedding-qwen3-embedding-4b）。
"""

import logging
import time

from langchain_openai import OpenAIEmbeddings

from app.core.config import settings

logger = logging.getLogger(__name__)


class LoggingOpenAIEmbeddings(OpenAIEmbeddings):
    def embed_query(self, text: str) -> list[float]:
        step2_start = time.perf_counter()
        logger.info("[RAG][STEP 2] embedding 开始")
        embedded = super().embed_query(text)
        logger.info("[RAG][STEP 2] embedding 完成，耗时 %.3fs", time.perf_counter() - step2_start)
        return embedded

# 获取嵌入模型实例
def get_embedding_model() -> OpenAIEmbeddings:
    return LoggingOpenAIEmbeddings(
        # 根据配置文件中的设置来初始化嵌入模型
        model=settings.embedding_model,
        # base_url和api_key也是从配置文件中获取的，确保模型能够正确连接到API服务
        base_url=settings.embedding_base_url,
        # api_key也是从配置文件中获取的，确保模型能够正确连接到API服务
        api_key=settings.embedding_api_key,
        # check_embedding_ctx_length参数设置为False，表示在生成嵌入时不检查上下文长度，这可能是为了避免在处理较长文本时出现问题
        check_embedding_ctx_length=False,
    )