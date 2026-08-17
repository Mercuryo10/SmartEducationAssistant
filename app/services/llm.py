"""LLM 与 Embedding 客户端工厂（docs/00 §7 / docs/06 §4）。

统一走 OpenAI 兼容端点（ChatOpenAI / OpenAIEmbeddings）：
- 开发期：DeepSeek 云 API + 千问 Embedding（LLM_PROVIDER=deepseek / EMBEDDING_PROVIDER=qwen）。
- 生产期：本地 Ollama（LLM_PROVIDER=local / EMBEDDING_PROVIDER=local，占位 key `ollama`）。

业务代码只调用本工厂，禁止直接实例化客户端。
"""
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("llm")


def get_chat_llm(temperature: float = 0.3) -> ChatOpenAI:
    """按 LLM_PROVIDER 返回对话模型客户端。

    Args:
        temperature: 生成温度，默认 0.3（答疑追求稳定）。

    Returns:
        ChatOpenAI 实例（DeepSeek 或本地 Ollama 的 OpenAI 兼容端点）。
    """
    if settings.llm_provider == "local":
        return ChatOpenAI(
            model=settings.local_llm_model,
            base_url=settings.local_llm_base_url,
            api_key="ollama",
            temperature=temperature,
        )
    if not settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY 未配置，调用 DeepSeek 将失败")
    return ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=temperature,
    )


def get_embedding_client() -> OpenAIEmbeddings:
    """按 EMBEDDING_PROVIDER 返回 Embedding 客户端。

    Returns:
        OpenAIEmbeddings 实例（千问 text-embedding-v4 或本地 bge-m3，维度均 1024）。
    """
    if settings.embedding_provider == "local":
        return OpenAIEmbeddings(
            model=settings.local_embedding_model,
            base_url=settings.local_embedding_base_url,
            api_key="ollama",
        )
    if not settings.qwen_api_key:
        logger.warning("QWEN_API_KEY 未配置，调用千问 Embedding 将失败")
    return OpenAIEmbeddings(
        model=settings.qwen_embedding_model,
        base_url=settings.qwen_base_url,
        api_key=settings.qwen_api_key,
    )
