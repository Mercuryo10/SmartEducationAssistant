"""学习推送接口模型（docs/04 §7.2~7.4）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PushCreateRequest(BaseModel):
    """创建推送任务请求。"""

    user_id: int
    content: str
    scheduled_at: datetime
    channel: str = Field(default="mock", pattern="^(mock|email|wechat|sms)$")


class PushTaskOut(BaseModel):
    """推送任务响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    scheduled_at: datetime


class PushPlanRequest(BaseModel):
    """遗忘曲线复习计划请求。"""

    user_id: int
    knowledge_point_id: int
    start_date: datetime


class PushPlanItem(BaseModel):
    """单个复习点。"""

    scheduled_at: datetime
    content: str


class PushPlanOut(BaseModel):
    """遗忘曲线复习计划响应（间隔 1/2/4/7 天）。"""

    items: list[PushPlanItem] = Field(default_factory=list)


class PushLogOut(BaseModel):
    """推送日志项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    status: str
    detail: str | None = None
    created_at: datetime


class PushLogListOut(BaseModel):
    """推送日志列表响应。"""

    total: int
    items: list[PushLogOut] = Field(default_factory=list)
