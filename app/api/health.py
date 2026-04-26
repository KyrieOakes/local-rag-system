from fastapi import APIRouter

# 定义一个APIRouter实例，设置路由的前缀为"/health"和标签为"Health"，用于处理与健康检查相关的API请求
router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    return {"status": "ok"}