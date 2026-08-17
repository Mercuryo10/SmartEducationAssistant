"""知识库检索工具（docs/06 §4.3）：供 qa_agent 的 retrieve 节点调用。"""
from langchain_core.tools import tool

from app.services import rag_service


@tool
def retrieve_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """从知识库检索与问题最相关的片段，用于 RAG 回答。
    返回列表，每项含 text/source/doc_id/chunk_index/score。
    """
    return rag_service.get_rag_service().retrieve(query, top_k=top_k)


def register_tools() -> list:
    """返回本模块的全部工具，供 Agent 绑定。"""
    return [retrieve_knowledge]
