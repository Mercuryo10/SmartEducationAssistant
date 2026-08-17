"""作业批改接口模型（docs/04 §5）。"""
from pydantic import BaseModel, Field


class GradingItem(BaseModel):
    """单题批改明细。"""

    question_no: int
    question_type: str = "objective"  # objective / subjective
    question_text: str = ""
    student_answer: str = ""
    reference_answer: str = ""
    is_correct: bool | None = None
    score: float | None = None
    comment: str = ""
    is_ai_scored: bool = False


class GradingSummary(BaseModel):
    """批改汇总。"""

    total: int
    correct: int
    objective_score: float


class HomeworkGradeResult(BaseModel):
    """批改响应（docs/04 §5.1）。"""

    submission_id: int
    status: str = "done"
    summary: GradingSummary | None = None
    items: list[GradingItem] = Field(default_factory=list)


class SubmissionOut(BaseModel):
    """提交结果查询响应（docs/04 §5.2）。"""

    submission_id: int
    status: str
    summary: GradingSummary | None = None
    items: list[GradingItem] = Field(default_factory=list)
