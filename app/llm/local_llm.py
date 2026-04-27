from langchain_openai import ChatOpenAI

from app.core.config import settings

# 加载本地部署的LLM模型
def get_local_llm() -> ChatOpenAI:
    return ChatOpenAI(
        # 加载预存的LLM模型，使用本地部署的模型参数
        model=settings.llm_model, 
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0.2,
    )