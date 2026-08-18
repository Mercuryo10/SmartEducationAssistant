"""学习推送仓储（docs/03 §7，覆盖 push_tasks + push_logs）。"""
from datetime import datetime

from sqlalchemy import func, select

from app.storage.models import PushLog, PushTask
from app.storage.repositories.base import BaseRepository


class PushRepository(BaseRepository):
    """推送任务与日志的数据访问。"""

    model = PushTask

    def create_task(
        self,
        user_id: int,
        content: str,
        scheduled_at: datetime,
        channel: str = "mock",
    ) -> PushTask:
        """创建推送任务（初始状态 pending）。"""
        return self.create(
            user_id=user_id, content=content, scheduled_at=scheduled_at, channel=channel, status="pending"
        )

    def get_task(self, task_id: int) -> PushTask | None:
        """按 id 取推送任务。"""
        return self.get_by_id(task_id)

    def list_pending_due(self, now: datetime) -> list[PushTask]:
        """列出到期且待触发的任务（status=pending 且 scheduled_at <= now）。"""
        stmt = (
            select(PushTask)
            .where(PushTask.status == "pending", PushTask.scheduled_at <= now)
            .order_by(PushTask.scheduled_at)
        )
        return list(self.session.scalars(stmt))

    def update_task_status(self, task_id: int, status: str) -> PushTask:
        """更新任务状态（success/failed）。"""
        task = self.get_by_id(task_id)
        if task is None:
            raise ValueError(f"push_tasks 不存在 id={task_id}")
        return self.update(task, status=status)

    def create_log(self, task_id: int, status: str, detail: str | None = None) -> PushLog:
        """写一条推送日志（status: success/failed）。"""
        log = PushLog(task_id=task_id, status=status, detail=detail)
        self.session.add(log)
        self.session.flush()
        return log

    def list_logs(self, page: int = 1, page_size: int = 20) -> tuple[int, list[PushLog]]:
        """分页列出推送日志（新→旧）。"""
        return self.list_page(page=page, page_size=page_size, order_by="-created_at")

    def list_logs_by_user(
        self, user_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[int, list[PushLog]]:
        """分页列出某用户的推送日志（关联 push_tasks 归属，新→旧，docs/01 数据隔离）。"""
        count_stmt = (
            select(func.count())
            .select_from(PushLog)
            .join(PushTask, PushLog.task_id == PushTask.id)
            .where(PushTask.user_id == user_id)
        )
        total = self.session.execute(count_stmt).scalar_one()
        stmt = (
            select(PushLog)
            .join(PushTask, PushLog.task_id == PushTask.id)
            .where(PushTask.user_id == user_id)
            .order_by(PushLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return total, list(self.session.scalars(stmt))
