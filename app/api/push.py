"""学习推送接口（docs/04 §7.2~7.4 / docs/09 阶段六）。

- POST /push/create：创建单条推送任务（直接指定触发时间）。
- POST /push/plan：按遗忘曲线（间隔 1/2/4/7 天）生成复习计划并落库。
- GET /push/logs：当前用户的推送日志列表（数据隔离，docs/01 §1）。

create/plan 走 push_agent 子图（docs/05 §5.5：parse_plan → persist_tasks）；
logs 为纯查询直调 push_service。任务到点触发由后台调度器完成（scheduler.py）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents.push_agent import build_push_subgraph
from app.agents.state import AppState
from app.api.deps import get_current_user
from app.core.exceptions import EduMentorError, ModelCallError, ValidationError
from app.core.logging import get_logger
from app.schemas.push import (
    PushCreateRequest,
    PushLogListOut,
    PushPlanOut,
    PushPlanRequest,
    PushTaskOut,
)
from app.services import push_service
from app.storage.db import get_session
from app.storage.models import User

router = APIRouter(prefix="/push", tags=["push"])
logger = get_logger("push_api")


@router.post("/create", response_model=PushTaskOut, status_code=201)
def create_push_task(
    payload: PushCreateRequest,
    session: Session = Depends(get_session),
) -> PushTaskOut:
    """创建单条推送任务（docs/04 §7.2）；到时由调度器渠道分发。"""
    state = AppState(
        user_id=payload.user_id,
        query="",
        push_action="create",
        push_payload=payload.model_dump(),
        session=session,
    )
    logger.info(
        "收到创建推送任务 user_id=%s scheduled_at=%s",
        payload.user_id, payload.scheduled_at,
    )
    try:
        final = build_push_subgraph().invoke(state)
    except EduMentorError:
        raise
    except Exception as exc:
        logger.exception("创建推送任务失败: %s", exc)
        session.rollback()
        raise ModelCallError("创建推送任务失败", detail=str(exc)) from exc

    if final.get("error"):
        raise ValidationError(final["error"])
    return PushTaskOut(**final["push_result"])


@router.post("/plan", response_model=PushPlanOut)
def review_plan(
    payload: PushPlanRequest,
    session: Session = Depends(get_session),
) -> PushPlanOut:
    """按遗忘曲线生成复习计划（docs/04 §7.3，间隔 1/2/4/7 天）并落库推送任务。"""
    state = AppState(
        user_id=payload.user_id,
        query="",
        push_action="plan",
        push_payload=payload.model_dump(),
        session=session,
    )
    logger.info(
        "收到复习计划请求 user_id=%s kp=%s start=%s",
        payload.user_id, payload.knowledge_point_id, payload.start_date,
    )
    try:
        final = build_push_subgraph().invoke(state)
    except EduMentorError:
        raise
    except Exception as exc:
        logger.exception("生成复习计划失败: %s", exc)
        session.rollback()
        raise ModelCallError("生成复习计划失败", detail=str(exc)) from exc

    if final.get("error"):
        raise ValidationError(final["error"])
    return PushPlanOut(**final["push_result"])


@router.get("/logs", response_model=PushLogListOut)
def list_push_logs(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> PushLogListOut:
    """当前用户的推送日志列表（docs/04 §7.4，数据隔离）。"""
    data = push_service.list_push_logs(session, user.id, page=page, page_size=page_size)
    return PushLogListOut(**data)
