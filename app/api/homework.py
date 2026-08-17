"""作业批改接口（docs/04 §5）。

- POST /homework/grade：上传作业图片（可多张），同步返回逐题批改明细。
- GET /homework/submissions/{submission_id}：查询历史批改结果（可复现）。

实现：路由只做「上传落盘 + 建提交 + 跑子图 + 打包响应」，批改逻辑在
grading_agent 子图与 grading_service 中；OCR 失败/异常时提交标记 failed 并返回
结构化错误，不阻塞其他请求（docs/09 §3 验收）。
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.agents.grading_agent import build_grading_subgraph
from app.agents.state import AppState
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import ModelCallError, ResourceNotFoundError, ValidationError
from app.core.logging import get_logger
from app.schemas.homework import HomeworkGradeResult, SubmissionOut
from app.services import grading_service
from app.storage.db import get_session
from app.storage.models import User

router = APIRouter(prefix="/homework", tags=["homework"])
logger = get_logger("homework_api")

# 允许的图片类型与大小（docs/04 §1）：jpg/png/webp，单文件 ≤10MB
_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_MAX_FILE_SIZE = 10 * 1024 * 1024


def _save_image(file: UploadFile) -> str:
    """校验并保存作业图片到 upload_dir，返回绝对路径。"""
    content_type = file.content_type or ""
    ext = _IMAGE_TYPES.get(content_type)
    if not ext:
        raise ValidationError(
            f"不支持的文件类型：{content_type or '未知'}（仅支持 jpg/png/webp 图片）"
        )
    content = file.file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise ValidationError("文件超过 10MB 限制")
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(content)
    logger.info("已保存作业图片 %s 大小=%dB", path.name, len(content))
    return str(path)


@router.post("/grade")
def grade_homework(
    file: list[UploadFile] = File(..., description="作业图片（可多张，字段名 file）"),
    answer_key: str | None = Form(default=None, description="参考答案文本，每行一条：题号+答案"),
    question_type_hint: str | None = Form(default=None, description="题型提示，如 choice+fill+solve"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HomeworkGradeResult:
    """提交作业图片并同步返回逐题批改明细（docs/04 §5.1）。"""
    if not file:
        raise ValidationError("请至少上传一张作业图片")
    paths = [_save_image(f) for f in file]

    # 先建提交记录（pending）并提交：即使后续失败，也能通过 GET 复现
    submission = grading_service.create_submission(session, user.id, paths, answer_key)
    session.commit()

    state = AppState(
        user_id=user.id,
        query="",
        attachments=[{"type": "image", "path": p} for p in paths],
        session=session,
        submission_id=submission.id,
        answer_key=answer_key,
        question_type_hint=question_type_hint,
    )
    graph = build_grading_subgraph()
    logger.info("收到作业批改请求 user_id=%s 图片=%d 提交=%s", user.id, len(paths), submission.id)
    try:
        final = graph.invoke(state)
    except ModelCallError:
        raise
    except Exception as exc:
        logger.exception("作业批改处理失败: %s", exc)
        session.rollback()
        grading_service.mark_submission_failed(session, submission.id)
        session.commit()
        raise ModelCallError("作业批改处理失败", detail=str(exc)) from exc

    return HomeworkGradeResult(**final["grading_result"])


@router.get("/submissions/{submission_id}")
def get_submission(
    submission_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SubmissionOut:
    """查询作业批改结果（docs/04 §5.2，可复现）。"""
    submission = grading_service.get_submission_for_user(session, user.id, submission_id)
    if submission is None:
        raise ResourceNotFoundError(f"作业提交不存在 id={submission_id}")
    return SubmissionOut(**grading_service.load_submission_result(session, submission))
