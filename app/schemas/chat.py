"""智能答疑接口模型（docs/04 §4）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceRef(BaseModel):
    """溯源引用。"""

    doc_id: int
    source: str
    snippet: str


class ChatRequest(BaseModel):
    """发起对话请求（multipart 表单字段的 JSON 视图）。"""

    message: str = Field(description="用户问题")
    conversation_id: int | None = Field(default=None, description="续接会话 id，缺省新建")


class ConversationOut(BaseModel):
    """会话列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime


class MessageOut(BaseModel):
    """会话消息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    source_refs: list[SourceRef] | None = None
    created_at: datetime


class ConversationDetailOut(BaseModel):
    """会话历史响应（docs/04 §4.2）。"""

    conversation_id: int
    messages: list[MessageOut]


# ---------- SSE 事件（docs/04 §4.1） ----------


class MetaEvent(BaseModel):
    """`meta` 事件：会话与消息标识。"""

    conversation_id: int
    message_id: int
    task: str = "qa"


class TokenEvent(BaseModel):
    """`token` 事件：流式文本增量。"""

    text: str


class DoneEvent(BaseModel):
    """`done` 事件：流结束，携带溯源。"""

    message_id: int
    source_refs: list[SourceRef] = []


class ErrorEvent(BaseModel):
    """`error` 事件：出错后关闭流。"""

    code: str
    message: str
    detail: object | None = None
