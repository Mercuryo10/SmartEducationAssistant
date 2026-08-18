"""错题仓储（docs/03 §7，mistakes 表）。

覆盖：错题增查 + 按知识点过滤分页（预加载知识点名）+ 薄弱点 TopN 统计（docs/09 §4 验收 US-MS-*）。
"""
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.storage.models import KnowledgePoint, Mistake
from app.storage.repositories.base import BaseRepository


class MistakeRepository(BaseRepository):
    """错题数据访问。"""

    model = Mistake

    def create_mistake(
        self,
        user_id: int,
        question_text: str,
        wrong_answer: str,
        correct_answer: str | None = None,
        knowledge_point_id: int | None = None,
        error_type: str | None = None,
        source_image: str | None = None,
    ) -> Mistake:
        """录入一条错题。"""
        return self.create(
            user_id=user_id,
            question_text=question_text,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            knowledge_point_id=knowledge_point_id,
            error_type=error_type,
            source_image=source_image,
        )

    def get_mistake_for_user(self, mistake_id: int, user_id: int) -> Mistake | None:
        """按 id + 用户取错题（校验归属，防止越权查询）。"""
        stmt = select(Mistake).where(
            Mistake.id == mistake_id,
            Mistake.user_id == user_id,
        )
        return self.session.scalar(stmt)

    def list_by_user(
        self,
        user_id: int,
        knowledge_point_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[Mistake]]:
        """分页列出某用户错题，可按知识点过滤。返回 (总数, 列表)。"""
        return self.list_page(
            page=page, page_size=page_size, user_id=user_id, knowledge_point_id=knowledge_point_id
        )

    def list_by_user_with_knowledge(
        self,
        user_id: int,
        knowledge_point_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[Mistake]]:
        """分页列出错题（预加载知识点，避免 N+1），可按知识点过滤。返回 (总数, 列表)。"""
        filters: dict[str, int] = {"user_id": user_id}
        if knowledge_point_id is not None:
            filters["knowledge_point_id"] = knowledge_point_id

        count_stmt = select(func.count()).select_from(Mistake)
        for key, value in filters.items():
            count_stmt = count_stmt.where(getattr(Mistake, key) == value)
        total = self.session.execute(count_stmt).scalar_one()

        stmt = (
            select(Mistake)
            .options(selectinload(Mistake.knowledge_point))
            .where(*[getattr(Mistake, key) == value for key, value in filters.items()])
            .order_by(Mistake.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.session.scalars(stmt))
        return total, items

    def count_by_knowledge_point(self, user_id: int, limit: int = 10) -> list[dict]:
        """统计某用户各知识点的错题数（薄弱点 TopN，docs/09 §4 验收），按次数降序。

        Args:
            user_id: 用户 id。
            limit: 返回条数上限。

        Returns:
            [{knowledge_point_id, knowledge_point_name, mistake_count}]，按错题数降序；
            仅统计已关联知识点的错题（知识点的数据必须真实，不虚构）。
        """
        stmt = (
            select(KnowledgePoint.name, Mistake.knowledge_point_id, func.count(Mistake.id))
            .join(KnowledgePoint, Mistake.knowledge_point_id == KnowledgePoint.id)
            .where(Mistake.user_id == user_id, Mistake.knowledge_point_id.is_not(None))
            .group_by(Mistake.knowledge_point_id, KnowledgePoint.name)
            .order_by(func.count(Mistake.id).desc(), KnowledgePoint.name.asc())
            .limit(limit)
        )
        return [
            {"knowledge_point_id": row[1], "knowledge_point_name": row[0], "mistake_count": int(row[2])}
            for row in self.session.execute(stmt)
        ]
