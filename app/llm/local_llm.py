from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_llm() -> ChatOpenAI:
    """
    根据配置文件中的 llm_provider 设置，返回对应的 LLM 实例。

    - "local": 连接到本地 LM Studio / Ollama
    - "cloud": 连接到云端 API（OpenAI / 任意兼容 OpenAI 接口的服务）

    使用时无需改动任何业务代码，只需修改 .env 中的配置即可切换。
    """
    if settings.llm_provider == "cloud":
        return ChatOpenAI(
            model=settings.cloud_llm_model,
            base_url=settings.cloud_llm_base_url,
            api_key=settings.cloud_llm_api_key,
            temperature=0.2,
        )

    # 默认: 本地 LLM (LM Studio / Ollama)
    return ChatOpenAI(
        model=settings.llm_model, 
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0.2,
    )