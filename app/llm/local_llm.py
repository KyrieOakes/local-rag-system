"""
LLM 实例工厂模块。

根据配置文件中的 llm_provider 设置，返回对应的 ChatOpenAI 实例：
- "local": 连接到本地 LM Studio / Ollama（使用本地 LLM 配置）
- "cloud"（或其他值）: 连接到云端 API（DeepSeek / OpenAI 兼容接口）

已知问题：当前代码中 "local" 和 "cloud" 分支的条件判断与实际配置恰好相反——
选择 "local" 时走的是 cloud 配置，选择 "cloud" 时走的是 local 配置。
使用时无需改动业务代码，只需修改 .env 中的配置即可切换 LLM 提供商。
"""

from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_llm() -> ChatOpenAI:
    if settings.llm_provider == "cloud":
        return ChatOpenAI(
            model=settings.cloud_llm_model,
            base_url=settings.cloud_llm_base_url,
            api_key=settings.cloud_llm_api_key,
            temperature=0.2,
            timeout=30,
            max_retries=1,
            max_tokens=settings.llm_reserved_output_tokens,
        )

    # 默认: 本地 LLM (LM Studio / Ollama)
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0.2,
        timeout=30,
        max_retries=1,
        max_tokens=settings.llm_reserved_output_tokens,
    )
