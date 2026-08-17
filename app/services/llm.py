"""LLM 与 Embedding 客户端工厂（docs/00 §7 / docs/06 §4）。

统一走 OpenAI 兼容端点：
- 对话：ChatOpenAI（langchain_openai），开发 DeepSeek 云 / 生产本地 Ollama。
- 嵌入：OpenAICompatEmbeddings（原生 openai SDK），开发千问 text-embedding-v4 / 生产本地 bge-m3。

> 说明：Embedding 不使用 langchain_openai.OpenAIEmbeddings——其 1.5.1 版对中文
> 经 tiktoken 切词后把 `input` 发成「token ID 整数数组」，DashScope/本地 Ollama 均不
> 接受（只认字符串），会报 `contents is neither str nor list of str`。故用原生客户端
> 封装，请求体 `input` 保持纯字符串列表。业务层只调用工厂，接口不变。

业务代码只调用本工厂，禁止直接实例化客户端。
"""
from langchain_openai import ChatOpenAI

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


_EMBED_BATCH = 25  # 单次请求最多文本条数（千问 text-embedding-v4 上限）


class OpenAICompatEmbeddings:
    """OpenAI 兼容 Embedding 客户端（千问 text-embedding-v4 / 本地 bge-m3）。

    用原生 openai SDK 直连兼容端点，请求体 `input` 保持纯字符串列表，
    规避 langchain_openai 1.5.1 对中文切词成 token ID 的兼容问题。
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        """初始化。

        Args:
            base_url: OpenAI 兼容端点（千问 compatible-mode / Ollama /v1）。
            api_key: 密钥（本地 Ollama 用占位 key `ollama`）。
            model: 模型名（text-embedding-v4 / bge-m3）。
        """
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def embed_query(self, text: str) -> list[float]:
        """把单条文本转为向量（1024 维）。

        Args:
            text: 查询或待嵌入文本。

        Returns:
            向量列表。
        """
        resp = self._client.embeddings.create(model=self.model, input=[text])
        return list(resp.data[0].embedding)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """把多条文本批量转为向量（自动分批，保持入参顺序）。

        Args:
            texts: 待嵌入文本列表。

        Returns:
            与入参等长的向量列表。
        """
        if not texts:
            return []
        result: list[list[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH):
            batch = texts[i : i + _EMBED_BATCH]
            resp = self._client.embeddings.create(model=self.model, input=batch)
            ordered = sorted(resp.data, key=lambda d: d.index)
            result.extend(list(d.embedding) for d in ordered)
        return result


def get_embedding_client() -> OpenAICompatEmbeddings:
    """按 EMBEDDING_PROVIDER 返回 Embedding 客户端。

    Returns:
        OpenAICompatEmbeddings 实例（千问 text-embedding-v4 或本地 bge-m3，维度均 1024）。
    """
    if settings.embedding_provider == "local":
        return OpenAICompatEmbeddings(
            base_url=settings.local_embedding_base_url,
            api_key="ollama",
            model=settings.local_embedding_model,
        )
    if not settings.qwen_api_key:
        logger.warning("QWEN_API_KEY 未配置，调用千问 Embedding 将失败")
    return OpenAICompatEmbeddings(
        base_url=settings.qwen_base_url,
        api_key=settings.qwen_api_key,
        model=settings.qwen_embedding_model,
    )
