"""练习生成接口（docs/04 §7.1 / docs/09 阶段五）。

- POST /exercises/generate：按知识点/难度/题型/数量参数化生成练习题（US-EX-*）。

出题走 exercise_agent 子图（docs/05 §5.4）：resolve_template → fill_params →
validate → polish；生成结果含 answer 与 explanation，答案可代入验算。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.exercise_agent import build_exercise_subgraph
from app.agents.state import AppState
from app.api.deps import get_current_user
from app.core.exceptions import EduMentorError, ModelCallError, ValidationError
from app.core.logging import get_logger
from app.schemas.exercise import ExerciseGenerateOut, ExerciseGenerateRequest
from app.storage.db import get_session
from app.storage.models import User

router = APIRouter(prefix="/exercises", tags=["exercises"])
logger = get_logger("exercises_api")


@router.post("/generate", response_model=ExerciseGenerateOut)
def generate_exercises(
    payload: ExerciseGenerateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ExerciseGenerateOut:
    """参数化生成练习题（docs/04 §7.1）：知识点 + 难度 + 题型 + 数量 → 题目列表。"""
    state = AppState(
        user_id=user.id,
        query="",
        exercise_payload=payload.model_dump(),
        session=session,
    )
    logger.info(
        "收到出题请求 user_id=%s kp=%s type=%s difficulty=%s count=%s",
        user.id, payload.knowledge_point_id, payload.question_type, payload.difficulty, payload.count,
    )
    try:
        final = build_exercise_subgraph().invoke(state)
    except EduMentorError:
        raise
    except Exception as exc:
        logger.exception("练习生成失败: %s", exc)
        session.rollback()
        raise ModelCallError("练习生成失败", detail=str(exc)) from exc

    if final.get("error"):
        raise ValidationError(final["error"])
    return ExerciseGenerateOut(**final["exercise_result"])
