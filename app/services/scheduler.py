"""学习推送后台调度（docs/05 §5.5 / docs/09 阶段六）：APScheduler 每 30s 扫描到期任务。

独立于 LangGraph 与请求上下文：调度器每次扫描自建 SessionLocal，把到期 pending
任务逐条渠道分发（app/tools/push_tool.dispatch_push），成功后更新任务状态并写
push_log（success/failed）。

- 任务与日志持久化在 MySQL（push_tasks / push_logs），服务重启后从 DB 恢复
  （docs/09 §6 验收：重启后任务恢复）。
- start_scheduler / stop_scheduler 由 FastAPI lifespan 调用（app/main.py）。
- 扫描间隔取 settings.push_scan_interval（默认 30s，可经 .env 调整）。
"""
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.logging import get_logger
from app.storage.db import SessionLocal
from app.storage.repositories import PushRepository
from app.tools.push_tool import dispatch_push

logger = get_logger("push_scheduler")

_scheduler = AsyncIOScheduler()


def _now_utc() -> datetime:
    """当前 UTC 时间（naive，与 models.utcnow 存储口径一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scan_due_tasks() -> None:
    """扫描并触发到期推送任务（由调度器按 interval 调用）。

    一次扫描内逐个分发：分发成功 → 任务状态 success + push_log success；
    分发失败 → 任务状态 failed + push_log failed。所有变更统一 commit。
    """
    with SessionLocal() as session:
        repo = PushRepository(session)
        due = repo.list_pending_due(_now_utc())
        if not due:
            return
        for task in due:
            ok = dispatch_push({"content": task.content, "channel": task.channel})
            status = "success" if ok else "failed"
            repo.update_task_status(task.id, status)
            repo.create_log(task.id, status, detail="mock 触达" if ok else "渠道分发失败")
            logger.info("推送任务 %s 已触发 status=%s", task.id, status)
        session.commit()
        logger.info("本次扫描触发推送任务 %d 条", len(due))


def start_scheduler() -> None:
    """启动 APScheduler：注册每 push_scan_interval 秒的扫描任务（幂等，仅启动一次）。"""
    if _scheduler.running:
        return
    _scheduler.add_job(
        scan_due_tasks,
        "interval",
        seconds=settings.push_scan_interval,
        id="scan_due_tasks",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("学习推送调度器已启动（每 %ss 扫描到期任务）", settings.push_scan_interval)


def stop_scheduler() -> None:
    """停止 APScheduler（服务关闭时调用，不等待进行中的任务）。"""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    logger.info("学习推送调度器已停止")
