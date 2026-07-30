"""Liveness and dependency-readiness endpoints."""

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from qdrant_client import QdrantClient

from app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    """Process liveness only; intentionally does not touch dependencies."""
    return {"status": "ok"}


def _check_qdrant() -> None:
    client = QdrantClient(
        url=settings.qdrant_url,
        timeout=settings.dependency_check_timeout_seconds,
    )
    try:
        client.get_collections()
    finally:
        client.close()


def _check_openai_compatible_endpoint(base_url: str, api_key: str) -> None:
    request = Request(
        f"{base_url.rstrip('/')}/models",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urlopen(request, timeout=settings.dependency_check_timeout_seconds) as response:
        if response.status >= 400:
            raise RuntimeError(f"endpoint returned HTTP {response.status}")
        response.read(1)


def _dependency_status(check) -> dict:
    try:
        check()
        return {"status": "ok"}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        return {
            "status": "unavailable",
            "error": type(exc).__name__,
        }
    except Exception as exc:  # dependency clients expose provider-specific exceptions
        return {
            "status": "unavailable",
            "error": type(exc).__name__,
        }


@router.get("/ready")
def readiness_check():
    """Check Qdrant plus the configured LLM and embedding endpoints."""
    if settings.llm_provider == "cloud":
        llm_base_url = settings.cloud_llm_base_url
        llm_api_key = settings.cloud_llm_api_key
    else:
        llm_base_url = settings.llm_base_url
        llm_api_key = settings.llm_api_key

    dependencies = {
        "qdrant": _dependency_status(_check_qdrant),
        "llm": _dependency_status(
            lambda: _check_openai_compatible_endpoint(llm_base_url, llm_api_key)
        ),
        "embedding": _dependency_status(
            lambda: _check_openai_compatible_endpoint(
                settings.embedding_base_url,
                settings.embedding_api_key,
            )
        ),
    }
    ready = all(item["status"] == "ok" for item in dependencies.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "dependencies": dependencies,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)
