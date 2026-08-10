"""Type-safe application configuration loaded from environment variables."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Local RAG System"
    app_env: str = "development"
    app_api_key: str = ""
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]:5173",
    ]
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    dependency_check_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    background_task_workers: int = Field(default=4, ge=1, le=32)
    background_task_queue_size: int = Field(default=256, ge=1, le=10_000)
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)

    # ── LLM Provider 选择 ──
    # 可选值: "local" (本地 LM Studio/Ollama) 或 "cloud" (云端 API)
    llm_provider: Literal["local", "cloud"] = "local"

    # ── 本地 LLM 配置 ──
    llm_base_url: str = "http://127.0.0.1:1234/v1"
    llm_model: str = "qwen3-8b-mlx"
    llm_api_key: str = "lm-studio"

    # ── 云端 LLM 配置（仅在 llm_provider="cloud" 时使用） ──
    cloud_llm_base_url: str = "https://api.deepseek.com"
    cloud_llm_model: str = "deepseek-chat"
    # Never provide a real cloud credential as a source-code default.
    # Set CLOUD_LLM_API_KEY in the ignored local .env file or process environment.
    cloud_llm_api_key: str = ""

    # ── Embedding 配置 ──
    embedding_base_url: str = "http://127.0.0.1:1234/v1"
    embedding_model: str = "text-embedding-qwen3-embedding-4b"
    embedding_revision: str = ""
    embedding_api_key: str = "lm-studio"
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    embedding_max_concurrency: int = Field(default=2, ge=1, le=16)
    upload_ingestion_concurrency: int = Field(default=2, ge=1, le=8)

    # ── Qdrant 配置 ──
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "local_rag_docs"

    # ── Retrieval index/query strategy ──
    # ``dense`` keeps the legacy unnamed-vector collection fully compatible.
    # ``hybrid`` stores named dense + BM25 sparse vectors in the same point.
    retrieval_index_schema: Literal["dense", "hybrid"] = "dense"
    retrieval_mode: Literal["dense", "bm25", "hybrid"] = "dense"
    dense_vector_name: str = Field(default="dense", min_length=1)
    sparse_vector_name: str = Field(default="bm25", min_length=1)
    bm25_model: str = Field(default="qdrant/bm25", min_length=1)
    bm25_tokenizer: Literal[
        "prefix",
        "whitespace",
        "word",
        "multilingual",
    ] = "multilingual"
    bm25_language: str = Field(default="none", min_length=1)
    hybrid_fusion: Literal["rrf", "dbsf"] = "rrf"
    hybrid_prefetch_top_n: int = Field(default=40, ge=1, le=1000)

    # ── 文本切分配置 ──
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)
    top_k: int = Field(default=5, ge=1, le=100)

    # ── Rerank 配置 ──
    reranker_type: Literal["none", "cross_encoder", "hybrid"] = "none"
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_candidate_top_n: int = Field(default=20, ge=1, le=500)
    reranker_final_top_k: int = Field(default=5, ge=1, le=100)
    reranker_max_chars: int = Field(default=1500, ge=64)
    reranker_device: Literal["cpu", "mps", "cuda"] = "cpu"
    reranker_trust_remote_code: bool = False

    # ── LLM 上下文窗口与会话记忆 ──
    llm_context_window: int = Field(default=32768, ge=512)
    llm_reserved_output_tokens: int = Field(default=2048, ge=1)
    context_safety_margin_tokens: int = Field(default=512, ge=0)
    # "offline_multilingual" never needs network; a cached tiktoken encoding
    # (for example "cl100k_base") can be selected for matching providers.
    context_tokenizer_encoding: str = "offline_multilingual"
    context_routing_output_tokens: int = Field(default=512, ge=1)
    context_routing_history_max_tokens: int = Field(default=4096, ge=0)
    context_history_max_tokens: int = Field(default=8192, ge=0)
    context_document_min_tokens: int = Field(default=4096, ge=0)
    # Short-term memory is a turn-aware sliding window. A turn is one complete
    # user + assistant exchange; both the count and token ceilings must hold.
    context_short_term_max_turns: int = Field(default=6, ge=0, le=100)
    context_short_term_max_tokens: int = Field(default=4096, ge=0)
    context_pending_memory_max_tokens: int = Field(default=2048, ge=0)
    context_summary_enabled: bool = True
    context_summary_max_tokens: int = Field(default=1024, ge=64)
    context_summary_input_tokens: int = Field(default=6144, ge=256)
    context_summary_batch_turns: int = Field(default=4, ge=1, le=100)
    context_summary_trigger_tokens: int = Field(default=2048, ge=128)

    # ── Durable conversation-memory worker ──
    memory_worker_enabled: bool = True
    memory_job_max_attempts: int = Field(default=5, ge=1, le=100)
    memory_job_retry_base_seconds: float = Field(default=2.0, gt=0, le=3600)
    memory_job_lease_seconds: float = Field(default=60.0, gt=1, le=3600)
    memory_job_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    memory_job_debounce_seconds: float = Field(default=2.0, ge=0, le=300)

    @model_validator(mode="after")
    def validate_cross_field_constraints(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if (
            self.llm_reserved_output_tokens + self.context_safety_margin_tokens
            >= self.llm_context_window
        ):
            raise ValueError(
                "LLM_RESERVED_OUTPUT_TOKENS + CONTEXT_SAFETY_MARGIN_TOKENS "
                "must be smaller than LLM_CONTEXT_WINDOW"
            )
        if self.context_routing_output_tokens >= self.llm_context_window:
            raise ValueError(
                "CONTEXT_ROUTING_OUTPUT_TOKENS must be smaller than LLM_CONTEXT_WINDOW"
            )
        if self.reranker_final_top_k > self.reranker_candidate_top_n:
            raise ValueError(
                "RERANKER_FINAL_TOP_K cannot exceed RERANKER_CANDIDATE_TOP_N"
            )
        if self.dense_vector_name == self.sparse_vector_name:
            raise ValueError(
                "DENSE_VECTOR_NAME and SPARSE_VECTOR_NAME must be different"
            )
        if (
            self.retrieval_mode in {"bm25", "hybrid"}
            and self.retrieval_index_schema != "hybrid"
        ):
            raise ValueError(
                "BM25/hybrid retrieval requires RETRIEVAL_INDEX_SCHEMA=hybrid"
            )
        if self.llm_provider == "cloud" and not self.cloud_llm_api_key:
            raise ValueError(
                "CLOUD_LLM_API_KEY is required when LLM_PROVIDER=cloud"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
