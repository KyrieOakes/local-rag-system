from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Local RAG System"
    app_env: str = "development"

    # ── LLM Provider 选择 ──
    # 可选值: "local" (本地 LM Studio/Ollama) 或 "cloud" (云端 API)
    llm_provider: str = "cloud"

    # ── 本地 LLM 配置 ──
    llm_base_url: str = "http://127.0.0.1:1234/v1"
    llm_model: str = "qwen/qwen3-v1-8b"
    llm_api_key: str = "lm-studio"

    # ── 云端 LLM 配置（仅在 llm_provider="cloud" 时使用） ──
    cloud_llm_base_url: str = "https://api.deepseek.com"
    cloud_llm_model: str = "deepseek-v4-flash"
    cloud_llm_api_key: str = "sk-595f9fce6d5245cfa00168b760217d40"

    # ── Embedding 配置 ──
    embedding_base_url: str = "http://127.0.0.1:1234/v1"
    embedding_model: str = "text-embedding-bge-small-zh-v1.5"
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