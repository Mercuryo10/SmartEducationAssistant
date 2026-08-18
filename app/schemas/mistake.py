"""错题分析接口模型（docs/04 §6）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MistakeCreate(BaseModel):
    """录入错题请求。"""

    question_text: str = Field(description="题干")
    wrong_answer: str = Field(description="错误答案")
    correct_answer: str | None = Field(default=None, description="正确答案")
    knowledge_point_name: str | None = Field(default=None, description="知识点名，缺省由 AI 自动关联")


class MistakeOut(BaseModel):
    """错题列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    question_text: str
    wrong_answer: str
    correct_answer: str | None = None
    error_type: str | None = None
    knowledge_point_id: int | None = None
    knowledge_point_name: str | None = None
    created_at: datetime


class MistakeCreateOut(BaseModel):
    """录入成功响应（docs/04 §6.1）。"""

    id: int
    knowledge_point_id: int | None = None
    knowledge_point_name: str | None = None
    created_at: datetime


class MistakeListOut(BaseModel):
    """错题列表响应（docs/04 §6.2）。"""

    total: int
    page: int
    page_size: int
    items: list[MistakeOut] = Field(default_factory=list)


class MistakeAnalysisOut(BaseModel):
    """错题讲解响应（docs/04 §6.3）。"""

    mistake_id: int
    knowledge_point: str | None = None
    analysis: str = ""
    explanation: str = ""
    common_mistakes: list[str] = Field(default_factory=list)
    variant_exercise: str = ""


class WeakPointOut(BaseModel):
    """薄弱知识点统计项（docs/09 §4 验收 US-MS-3：错误次数真实统计）。"""

    knowledge_point_id: int
    knowledge_point_name: str
    mistake_count: int


class WeakPointListOut(BaseModel):
    """薄弱知识点 TopN 响应。"""

    items: list[WeakPointOut] = Field(default_factory=list)


class KnowledgePointOut(BaseModel):
    """知识点列表项（docs/04 §6.4 GET /knowledge-points）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: str = "math"
    description: str | None = None


class KnowledgePointListOut(BaseModel):
    """知识点列表响应。"""

    items: list[KnowledgePointOut] = Field(default_factory=list)
