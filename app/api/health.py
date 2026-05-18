"""
健康检查 API 路由模块。

提供 GET /health 端点，返回 {"status": "ok"}。
用于前端检测后端服务是否在线，前端启动时会自动调用此接口并显示连接状态。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    return {"status": "ok"}