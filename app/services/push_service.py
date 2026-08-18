"""学习推送业务服务（docs/09 阶段六）：遗忘曲线计划、推送任务落库、日志查询。

独立于 LangGraph，供 push_agent / app/api/push.py / scheduler 复用：
- review_schedule：按遗忘曲线间隔 [1,2,4,7] 天从起始日起生成 4 个复习时间点（09:00）。
- create_push_tasks：把计划项写入 push_tasks（状态 pending，等待调度器触发）。
- list_push_logs：按用户分页查询推送日志（数据隔离，docs/01 §1）。

时间统一按 UTC（naive）存储，与 docs/03 §4 push_tasks/push_logs 表结构一致。
"""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.storage.repositories import PushRepository

logger = get_logger("push_service")


def to_utc_naive(dt: datetime) -> datetime:
    """把任意 datetime 归一化为 naive UTC（带时区则转 UTC 并去掉 tz，naive 视为 UTC）。"""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def review_intervals() -> list[int]:
    """遗忘曲线复习间隔（天），从 settings 解析（默认 1,2,4,7，docs/05 §5.5）。"""
    parsed = [int(x) for x in settings.push_review_intervals.split(",") if x.strip().isdigit()]
    return parsed or [1, 2, 4, 7]


def review_schedule(start_date: datetime, knowledge_point_name: str) -> list[dict]:
    """按遗忘曲线生成复习计划（docs/05 §5.5 / docs/04 §7.3）。

    Args:
        start_date: 起始日期（UTC；当日不安排，从次日开始累计间隔）。
        knowledge_point_name: 知识点名，写入 content 便于辨识。

    Returns:
        [{scheduled_at: datetime, content: str}]，间隔为 1/2/4/7 天，每日 09:00 触发。
    """
    base = to_utc_naive(start_date).date()
    items: list[dict] = []
    for idx, days in enumerate(review_intervals(), start=1):
        scheduled = datetime.combine(base + timedelta(days=days), time(settings.push_review_hour, 0, 0))
        items.append({"scheduled_at": scheduled, "content": f"复习：{knowledge_point_name}（第{idx}次）"})
    return items


def create_push_tasks(
    session: Session, user_id: int, items: list[dict], channel: str = "mock"
) -> list:
    """批量创建推送任务（docs/04 §7.2/§7.3），状态初始 pending。

    Args:
        session: 数据库会话。
        user_id: 任务归属用户。
        items: [{scheduled_at, content}] 计划项。
        channel: 分发渠道（默认 mock）。

    Returns:
        已落库（flush）的 PushTask 对象列表，含自增 id。
    """
    repo = PushRepository(session)
    tasks = [
        repo.create_task(
            user_id=user_id,
            content=item["content"],
            scheduled_at=to_utc_naive(item["scheduled_at"]),
            channel=channel,
        )
        for item in items
    ]
    logger.info("推送任务落库 %d 条 user_id=%s channel=%s", len(tasks), user_id, channel)
    return tasks


def list_push_logs(session: Session, user_id: int, page: int = 1, page_size: int = 20) -> dict:
    """分页查询某用户的推送日志（docs/04 §7.4），响应结构与 schema 一致。"""
    total, logs = PushRepository(session).list_logs_by_user(user_id, page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": logs}
