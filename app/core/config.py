"""
应用配置模块。

使用 pydantic-settings 从 .env 文件加载所有配置项，提供类型安全的设置访问。
配置项分组：
- LLM Provider 选择：local（LM Studio/Ollama）vs cloud（云端 API）
- 本地 LLM 配置：base_url、model、api_key
- 云端 LLM 配置：base_url、model、api_key
- Embedding 配置：嵌入模型的服务地址和模型名
- Qdrant 配置：向量数据库地址和集合名称
- 文本切分配置：chunk_size（分块大小）和 chunk_overlap（重叠大小）

全局单例 settings 在模块底部创建，所有模块通过 `from app.core.config import settings` 引用。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Local RAG System"
    app_env: str = "development"

    # ── LLM Provider 选择 ──
    # 可选值: "local" (本地 LM Studio/Ollama) 或 "cloud" (云端 API)
    llm_provider: str = "local"

    # ── 本地 LLM 配置 ──
    llm_base_url: str = "http://10.0.0.59:1234/v1"
    llm_model: str = "qwen3-8b-mlx"
    llm_api_key: str = "lm-studio"

    # ── 云端 LLM 配置（仅在 llm_provider="cloud" 时使用） ──
    cloud_llm_base_url: str = "https://api.deepseek.com"
    cloud_llm_model: str = "deepseek-v4-flash"
    cloud_llm_api_key: str = ""

    # ── Embedding 配置 ──
    embedding_base_url: str = "http://10.0.0.59:1234/v1"
    embedding_model: str = "text-embedding-qwen3-embedding-4b"
    embedding_api_key: str = "lm-studio"

    # ── Qdrant 配置 ──
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "local_rag_docs"

    # ── 文本切分配置 ──
    chunk_size: int = 800
    chunk_overlap: int = 120

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()