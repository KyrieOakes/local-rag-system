from langchain_openai import OpenAIEmbeddings

from app.core.config import settings

# 获取嵌入模型实例
def get_embedding_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        # 根据配置文件中的设置来初始化嵌入模型
        model=settings.embedding_model,
        # base_url和api_key也是从配置文件中获取的，确保模型能够正确连接到API服务
        base_url=settings.embedding_base_url,
        # api_key也是从配置文件中获取的，确保模型能够正确连接到API服务
        api_key=settings.embedding_api_key,
        # check_embedding_ctx_length参数设置为False，表示在生成嵌入时不检查上下文长度，这可能是为了避免在处理较长文本时出现问题
        check_embedding_ctx_length=False,
    )