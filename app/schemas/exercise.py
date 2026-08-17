"""练习生成接口模型（docs/04 §7.1）。"""
from pydantic import BaseModel, Field


class ExerciseGenerateRequest(BaseModel):
    """生成练习题请求。"""

    knowledge_point_id: int
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    question_type: str = Field(default="solve", pattern="^(choice|fill|solve)$")
    count: int = Field(default=3, ge=1, le=10)


class ExerciseItem(BaseModel):
    """单道练习题。"""

    question_text: str
    answer: str
    explanation: str
    difficulty: str
    knowledge_point_id: int


class ExerciseGenerateOut(BaseModel):
    """生成练习题响应。"""

    items: list[ExerciseItem] = Field(default_factory=list)
