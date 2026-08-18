"""错题分析与知识点接口（docs/04 §6 / docs/09 阶段四）。

- POST /mistakes：录入错题（自动关联知识点）。
- GET /mistakes：错题列表（可按知识点过滤）。
- GET /mistakes/weak-points：薄弱知识点 TopN（US-MS-3，统计真实）。
- POST /mistakes/{mistake_id}/analyze：错题结构化解讲（US-MS-4）。
- GET /knowledge-points：内置知识点列表。

录入与讲解走 mistake_agent 子图（docs/05 §5.3）；列表/统计为纯查询直调
mistake_service。错题归属一律取当前登录用户（docs/01 §1 数据隔离）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agents.mistake_agent import build_mistake_subgraph
from app.agents.state import AppState
from app.api.deps import get_current_user
from app.core.exceptions import EduMentorError, ModelCallError, ValidationError
from app.core.logging import get_logger
from app.schemas.mistake import (
    KnowledgePointListOut,
    KnowledgePointOut,
    MistakeAnalysisOut,
    MistakeCreate,
    MistakeCreateOut,
    MistakeListOut,
    WeakPointListOut,
)
from app.services import mistake_service
from app.storage.db import get_session
from app.storage.models import User

router = APIRouter(prefix="/mistakes", tags=["mistakes"])
knowledge_router = APIRouter(prefix="/knowledge-points", tags=["mistakes"])
logger = get_logger("mistakes_api")


@router.post("", response_model=MistakeCreateOut, status_code=201)
def create_mistake(
    payload: MistakeCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MistakeCreateOut:
    """录入错题并自动关联知识点（docs/04 §6.1；knowledge_point_name 缺省由 AI 关联）。"""
    state = AppState(
        user_id=user.id,
        query=payload.question_text,
        mistake_action="ingest",
        mistake_payload=payload.model_dump(),
        session=session,
    )
    logger.info("收到错题录入 user_id=%s 题干=%.30s", user.id, payload.question_text)
    try:
        final = build_mistake_subgraph().invoke(state)
    except EduMentorError:
        raise
    except Exception as exc:
        logger.exception("错题录入失败: %s", exc)
        session.rollback()
        raise ModelCallError("错题录入失败", detail=str(exc)) from exc

    if final.get("error"):
        raise ValidationError(final["error"])
    return MistakeCreateOut(**final["mistake_result"])


@router.get("", response_model=MistakeListOut)
def list_mistakes(
    knowledge_point_id: int | None = Query(default=None, description="按知识点过滤"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MistakeListOut:
    """错题列表，可按知识点过滤（docs/04 §6.2）。"""
    data = mistake_service.list_mistakes(
        session, user.id, knowledge_point_id=knowledge_point_id, page=page, page_size=page_size
    )
    return MistakeListOut(**data)


@router.get("/weak-points", response_model=WeakPointListOut)
def weak_points(
    limit: int = Query(default=10, ge=1, le=50, description="返回条数上限"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> WeakPointListOut:
    """薄弱知识点 TopN：按错误次数降序（US-MS-3，统计真实）。"""
    items = mistake_service.weak_points_topn(session, user.id, limit=limit)
    return WeakPointListOut(items=items)


@router.post("/{mistake_id}/analyze", response_model=MistakeAnalysisOut)
def analyze_mistake(
    mistake_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MistakeAnalysisOut:
    """生成单题结构化解讲（docs/04 §6.3：错误模式/讲解/常见错误/变式题）。"""
    state = AppState(
        user_id=user.id,
        query="",
        mistake_action="explain",
        mistake_id=mistake_id,
        session=session,
    )
    logger.info("收到错题讲解请求 user_id=%s mistake_id=%s", user.id, mistake_id)
    try:
        final = build_mistake_subgraph().invoke(state)
    except EduMentorError:
        raise
    except Exception as exc:
        logger.exception("错题讲解失败: %s", exc)
        session.rollback()
        raise ModelCallError("错题讲解失败", detail=str(exc)) from exc
    return MistakeAnalysisOut(**final["mistake_result"])


@knowledge_router.get("", response_model=KnowledgePointListOut)
def list_knowledge_points(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> KnowledgePointListOut:
    """内置知识点列表（docs/04 §6.4，供前端与错题/出题引用）。"""
    kps = mistake_service.list_knowledge_points(session)
    return KnowledgePointListOut(items=[KnowledgePointOut.model_validate(kp) for kp in kps])
