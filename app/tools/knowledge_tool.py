"""知识点分类工具（docs/06 §4.7）：文本 → 知识点自动关联。

供错题分析子图（mistake_agent）在录入时自动打知识点标签；也可被 Supervisor
作为工具绑定（自建短会话读取内置知识点列表，无请求上下文依赖）。
"""
from langchain_core.tools import tool

from app.services import mistake_service


@tool
def classify_knowledge_point(text: str) -> dict:
    """根据错题文本自动关联最匹配的内置知识点。
    text 为错题题干（可含错误答案等上下文）；
    返回 {"knowledge_point_id": int|None, "knowledge_point_name": str|None, "confidence": float}。
    """
    return mistake_service.classify_knowledge_point(text)


def register_tools() -> list:
    """返回本模块的全部工具，供 Agent 绑定。"""
    return [classify_knowledge_point]
