"""FastAPI application entry point and cross-cutting middleware."""

import logging
import secrets
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.documents import router as documents_router
from app.api.rag import router as rag_router
from app.api.conversations import router as conversations_router
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# 创建一个FastAPI应用实例，设置应用的标题为"Local RAG System"和版本号为"0.1.0"
app = FastAPI(
    title="Local RAG System",
    version="0.1.0",
)
@app.middleware("http")
async def request_identity_and_optional_api_key(request: Request, call_next):
    """Attach a request ID and enforce the optional local API key.

    Authentication remains disabled when ``APP_API_KEY`` is blank, preserving
    the trusted single-user local workflow. Health endpoints stay available to
    container orchestrators without credentials.
    """
    request_id = request.headers.get("X-Request-ID", "")
    if not request_id or len(request_id) > 128:
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id

    path = request.url.path
    is_public_health = path in {"/", "/health", "/health/ready"}
    if settings.app_api_key and not is_public_health:
        supplied_key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(supplied_key, settings.app_api_key):
            return JSONResponse(
                {"detail": "Invalid or missing API key"},
                status_code=401,
                headers={"X-Request-ID": request_id},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Register CORS after the custom middleware so it remains the outer layer and
# also decorates early 401 responses returned by API-key enforcement.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(rag_router)
app.include_router(conversations_router)

# 定义一个根路径的GET请求处理函数，当访问根路径时返回一个JSON响应，表示Local RAG System正在运行
@app.get("/")
def root():
    return {"message": "Local RAG System 正在运行"}
