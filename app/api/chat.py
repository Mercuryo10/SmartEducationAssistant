"""智能答疑与对话历史接口（docs/04 §4，核心 SSE 流式）。

- POST /chat：多模态智能答疑（multipart），SSE 事件流 meta/token/done/error。
- GET /conversations：会话列表。
- GET /conversations/{id}/messages：会话消息历史。

阶段七起 /chat 走 Supervisor 主图（docs/09 §7）：supervisor 意图分类 → 路由到
5 个子 Agent 之一 → 聚合。文字提问通常路由到 qa 子图并流式回答；路由到其他
子图且缺专用入参时，聚合节点给出引导文案。

流式实现：图在独立线程运行（asyncio.to_thread，不阻塞事件循环），
逐 token 经线程安全队列推送；本层异步生成器消费队列产出 SSE。
"""
import asyncio
import json
import queue
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agents.state import AppState
from app.agents.supervisor import build_graph
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.schemas.chat import (
    ConversationDetailOut,
    ConversationOut,
    DoneEvent,
    ErrorEvent,
    MessageOut,
    MetaEvent,
    SourceRef,
    TokenEvent,
)
from app.services import conversation_service
from app.storage.db import get_session
from app.storage.models import User

router = APIRouter(tags=["chat"])
logger = get_logger("chat_api")

# 允许的上传类型（docs/04 §1）：图片 jpg/png/webp，音频 wav/mp3，单文件 ≤10MB
_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_AUDIO_TYPES = {"audio/wav": ".wav", "audio/mp3": ".mp3"}
_MAX_FILE_SIZE = 10 * 1024 * 1024


def _sse(event: str, data: Any) -> str:
    """把事件模型序列化为 SSE 文本（docs/04 §4.1 事件格式）。"""
    payload = data.model_dump() if hasattr(data, "model_dump") else data
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _save_upload(file: UploadFile) -> tuple[str, str]:
    """校验并保存上传文件到 upload_dir，返回 (类型, 绝对路径)。

    Args:
        file: 上传的图片或音频文件。

    Returns:
        (att_type, path)；att_type 为 "image" 或 "audio"。
    """
    content_type = file.content_type or ""
    ext = _IMAGE_TYPES.get(content_type) or _AUDIO_TYPES.get(content_type)
    if not ext:
        raise ValidationError(
            f"不支持的文件类型：{content_type or '未知'}（仅支持 jpg/png/webp 图片与 wav/mp3 音频）"
        )
    content = file.file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise ValidationError("文件超过 10MB 限制")
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(content)
    att_type = "image" if content_type in _IMAGE_TYPES else "audio"
    logger.info("已保存上传文件 %s 类型=%s 大小=%dB", path.name, att_type, len(content))
    return att_type, str(path)


async def _event_stream(state: AppState, graph: Any) -> AsyncGenerator[str, None]:
    """SSE 事件生成器：消费图的 token 队列，产出 meta/token/done/error 事件。"""
    q: "queue.Queue[dict]" = state["token_queue"]
    task = asyncio.create_task(asyncio.to_thread(graph.invoke, state))
    meta_sent: dict | None = None
    try:
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                if task.done():
                    break
                await asyncio.sleep(0.02)
                continue
            if item["type"] == "meta":
                meta_sent = item
                yield _sse(
                    "meta",
                    MetaEvent(
                        conversation_id=item["conversation_id"],
                        message_id=item["message_id"],
                        task=state.get("task", "qa"),
                    ),
                )
            elif item["type"] == "token":
                yield _sse("token", TokenEvent(text=item["text"]))
            elif item["type"] == "eod":
                break
        final = await task
        qa = final.get("qa_result", {})
        message_id = meta_sent["message_id"] if meta_sent else final.get("assistant_message_id", 0)
        refs = [SourceRef(**r) for r in qa.get("source_refs", [])]
        yield _sse("done", DoneEvent(message_id=message_id, source_refs=refs))
    except Exception as exc:
        logger.exception("chat 流式处理失败: %s", exc)
        # 回滚本次请求的未完成事务，避免失败请求留下孤儿会话/空消息（get_session 随后 commit 为空操作）
        try:
            state["session"].rollback()
        except Exception:
            logger.warning("会话回滚失败（连接可能已断开）", exc_info=True)
        yield _sse(
            "error",
            ErrorEvent(
                code=getattr(exc, "code", "INTERNAL_ERROR"),
                message=getattr(exc, "message", "处理失败"),
                detail=getattr(exc, "detail", str(exc)),
            ),
        )


@router.post("/chat")
async def chat(
    message: str = Form(..., description="用户问题"),
    conversation_id: int | None = Form(default=None, description="续接会话 id，缺省新建"),
    file: UploadFile | None = File(default=None, description="图片或音频"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """发起多模态智能答疑，返回 SSE 事件流（docs/04 §4.1）。"""
    attachments: list[dict] = []
    if file is not None:
        att_type, path = _save_upload(file)
        attachments.append({"type": att_type, "path": path})

    state = AppState(
        user_id=user.id,
        conversation_id=conversation_id,
        query=message,
        attachments=attachments,
        history=[],
        session=session,
        token_queue=queue.Queue(),
    )
    graph = build_graph()
    logger.info("收到答疑请求 user_id=%s conv_id=%s msg=%.30s", user.id, conversation_id, message)
    return StreamingResponse(
        _event_stream(state, graph),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
def list_conversations(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[ConversationOut]:
    """当前用户会话列表（新→旧）。"""
    convs = conversation_service.list_user_conversations(session, user.id)
    return [ConversationOut.model_validate(c) for c in convs]


@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ConversationDetailOut:
    """会话消息历史（docs/04 §4.2）。"""
    msgs = conversation_service.get_conversation_messages(session, conversation_id, user.id)
    return ConversationDetailOut(
        conversation_id=conversation_id,
        messages=[MessageOut.model_validate(m) for m in msgs],
    )
