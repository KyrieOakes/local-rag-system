from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.documents import router as documents_router
from app.api.rag import router as rag_router

# 创建一个FastAPI应用实例，设置应用的标题为"Local RAG System"和版本号为"0.1.0"
app = FastAPI(
    title="Local RAG System",
    version="0.1.0",
)

# 将健康检查路由和文档相关的路由注册到FastAPI应用中，使得这些路由能够处理相应的API请求
app.include_router(health_router)
# 将文档相关的路由注册到FastAPI应用中，使得这些路由能够处理相应的API请求
app.include_router(documents_router)
# 将RAG相关的路由注册到FastAPI应用中，使得这些路由能够处理相应的API请求
app.include_router(rag_router)

# 定义一个根路径的GET请求处理函数，当访问根路径时返回一个JSON响应，表示Local RAG System正在运行
@app.get("/")
def root():
    return {"message": "Local RAG System 正在运行"}