"""RAG 检索服务（docs/09 阶段二 / docs/06 §5）。

职责（只依赖 VectorStore 接口与 Embedding 工厂，不触碰后端实现）：
- 文档切分、向量化、写入向量库（供 scripts/build_kb.py 使用）。
- 在线检索：问题向量化 → vector_store.search → 溯源组装。
- 组装 RAG 提示词（docs/05 §5.1 的 Prompt 草稿）。

关键链路（嵌入/检索）必须记录耗时日志（docs/08 §6）。
"""
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm import get_embedding_client
from app.storage.vector_store import VectorStore, get_vector_store

logger = get_logger("rag_service")

# RAG 系统提示词（docs/05 §5.1）
RAG_SYSTEM_TEMPLATE = """你是 EduMentor 智能答疑助手，面向学习大模型/Agent 的大学生，基于提供的知识库片段回答问题。
规则：
1. 只依据【知识库片段】回答；片段不足以作答时，明确说“知识库中未找到该内容”。
2. 回答需给出解释，语言简洁、通俗，适合初学大模型的大学生理解。
3. 不要编造知识库中不存在的事实。
{context}"""


class RAGService:
    """知识库检索服务：封装切分 / 嵌入 / 向量读写 / 提示词组装。"""

    def __init__(self, vector_store: VectorStore | None = None, embedding: Any | None = None) -> None:
        """初始化。

        Args:
            vector_store: 向量库实现，缺省走 get_vector_store() 工厂（faiss/milvus 按配置）。
            embedding: Embedding 客户端，缺省走 get_embedding_client() 工厂（千问/本地）。
        """
        self.store = vector_store or get_vector_store()
        self.embedding = embedding or get_embedding_client()

    # ---------- 文档切分 ----------

    def split_text(self, text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
        """把文档切分为重叠分块（按字符数，适合中文）。

        Args:
            text: 原始文本。
            chunk_size: 每块字符数，默认 settings.chunk_size。
            overlap: 相邻块重叠字符数，默认 settings.chunk_overlap。

        Returns:
            分块文本列表。
        """
        size = chunk_size or settings.chunk_size
        ov = overlap or settings.chunk_overlap
        step = max(size - ov, 1)
        chunks: list[str] = []
        n = len(text)
        start = 0
        while start < n:
            chunks.append(text[start : start + size])
            if start + size >= n:
                break
            start += step
        # 去除纯空白块
        return [c.strip() for c in chunks if c and c.strip()]

    # ---------- 嵌入 ----------

    def embed_query(self, query: str) -> list[float]:
        """把查询文本转为向量（1024 维）。"""
        return list(self.embedding.embed_query(query))

    # ---------- 知识库写入 / 删除 ----------

    def add_document(self, doc_id: int, title: str, source: str, content: str) -> int:
        """切分并写入一篇文档到向量库。

        Args:
            doc_id: 对应 knowledge_docs.id。
            title: 文档标题。
            source: 文档来源（如 demo_data/rag_principles.md）。
            content: 文档全文。

        Returns:
            写入的分块数量。
        """
        chunks = self.split_text(content)
        if not chunks:
            return 0
        t0 = time.perf_counter()
        vectors = self.embedding.embed_documents(chunks)
        items = [
            {
                "doc_id": doc_id,
                "title": title,
                "source": source,
                "chunk_index": i,
                "text": chunk,
                "vector": list(vectors[i]),
            }
            for i, chunk in enumerate(chunks)
        ]
        self.store.add(items)
        logger.info("写入文档 doc_id=%s chunks=%d embed_cost=%.2fs", doc_id, len(chunks), time.perf_counter() - t0)
        return len(chunks)

    def delete_document(self, doc_id: int) -> None:
        """删除某文档在向量库中的全部分块。"""
        self.store.delete_by_doc(doc_id)
        logger.info("删除文档分块 doc_id=%s", doc_id)

    # ---------- 在线检索 ----------

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        """检索与问题最相关的知识片段。

        Args:
            query: 用户问题。
            top_k: 返回条数，默认 settings.retrieve_top_k（5）。

        Returns:
            片段列表，每项含 text/source/doc_id/title/chunk_index/score。
        """
        k = top_k or settings.retrieve_top_k
        t0 = time.perf_counter()
        query_vector = self.embed_query(query)
        results = self.store.search(query_vector, top_k=k)
        logger.info("检索 query=%.18s top_k=%d hits=%d cost=%.3fs", query, k, len(results), time.perf_counter() - t0)
        return results

    def build_source_refs(self, results: list[dict], snippet_len: int = 200) -> list[dict]:
        """把检索结果组装为溯源引用（docs/04 §4 done.source_refs）。

        Args:
            results: retrieve() 返回的片段列表。
            snippet_len: 溯源摘要截断长度。

        Returns:
            [{doc_id, source, snippet}]。
        """
        refs: list[dict] = []
        for r in results:
            refs.append(
                {
                    "doc_id": r["doc_id"],
                    "source": r.get("source", ""),
                    "snippet": (r.get("text") or "")[:snippet_len],
                }
            )
        return refs

    # ---------- 提示词组装 ----------

    def build_messages(self, query: str, context: list[dict], history: list[dict] | None = None) -> list:
        """组装 RAG 问答消息列表（System + 历史 + Human）。

        Args:
            query: 用户问题（含附件转写文本）。
            context: retrieve() 检索到的片段列表。
            history: 近期对话 [{role, content}]，可为空。

        Returns:
            langchain 消息列表。
        """
        ctx_lines = [f"[{i + 1}] {r.get('text', '')}（来源：{r.get('source', '')}）" for i, r in enumerate(context)]
        context_block = "【知识库片段】\n" + ("\n\n".join(ctx_lines) if ctx_lines else "（无相关片段）")
        system = SystemMessage(content=RAG_SYSTEM_TEMPLATE.format(context=context_block))

        messages: list = [system]
        for h in (history or [])[-10:]:
            if h.get("role") == "user":
                messages.append(HumanMessage(content=h.get("content", "")))
            else:
                messages.append(AIMessage(content=h.get("content", "")))
        messages.append(HumanMessage(content=f"【学生问题】\n{query}"))
        return messages


def get_rag_service() -> RAGService:
    """RAG 服务工厂（惰性单例）：业务层统一从这里取，避免重复建索引。"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


_rag_service: RAGService | None = None
