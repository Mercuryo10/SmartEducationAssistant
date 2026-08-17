"""错题仓储（docs/03 §7，mistakes 表）。"""
from app.storage.models import Mistake
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
