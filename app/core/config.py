from pydantic_settings import BaseSettings, SettingsConfigDict

# 定义应用程序的配置类，继承自BaseSettings
class Settings(BaseSettings):
    app_name: str = "Local RAG System"
    app_env: str = "development"

    llm_base_url: str
    llm_model: str
    llm_api_key: str = "lm-studio"

    embedding_base_url: str
    embedding_model: str
    embedding_api_key: str = "lm-studio"

    qdrant_url: str
    qdrant_collection: str = "local_rag_docs"

    chunk_size: int = 800
    chunk_overlap: int = 120

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()