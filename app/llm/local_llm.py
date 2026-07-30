"""Create OpenAI-compatible chat clients for local or cloud inference."""

from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_llm(max_tokens: int | None = None) -> ChatOpenAI:
    """Return a configured chat model.

    ``max_tokens`` lets routing and summary calls reserve a smaller output
    budget than final answer generation while sharing the same provider.
    """
    output_tokens = max_tokens or settings.llm_reserved_output_tokens
    if settings.llm_provider == "cloud":
        return ChatOpenAI(
            model=settings.cloud_llm_model,
            base_url=settings.cloud_llm_base_url,
            api_key=settings.cloud_llm_api_key,
            temperature=0.2,
            timeout=30,
            max_retries=1,
            max_tokens=output_tokens,
        )

    # 默认: 本地 LLM (LM Studio / Ollama)
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0.2,
        timeout=30,
        max_retries=1,
        max_tokens=output_tokens,
    )
