"""仓储基类：通用 CRUD 与分页查询（docs/03 §7）。

子类通过 `model` 属性绑定 ORM 模型，复用本类的通用操作。
"""
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


class BaseRepository:
    """仓储抽象基类：提供 get/create/update/delete/list 通用实现。"""

    model: type[ModelT] | None = None  # 子类必须指定

    def __init__(self, session: Session) -> None:
        """绑定一个 SQLAlchemy 会话（来自 db.get_session 依赖）。

        Args:
            session: 数据库会话。
        """
        self.session = session

    def get_by_id(self, obj_id: int) -> ModelT | None:
        """按主键取单条记录。"""
        return self.session.get(self.model, obj_id)

    def create(self, **fields: Any) -> ModelT:
        """创建一条记录并 flush（返回带主键的对象）。"""
        obj = self.model(**fields)
        self.session.add(obj)
        self.session.flush()
        return obj

    def update(self, obj: ModelT, **fields: Any) -> ModelT:
        """就地更新对象的指定字段并 flush。"""
        for key, value in fields.items():
            setattr(obj, key, value)
        self.session.flush()
        return obj

    def delete(self, obj: ModelT) -> None:
        """删除记录并 flush。"""
        self.session.delete(obj)
        self.session.flush()

    def list_all(self, order_by: str | None = None, **filters: Any) -> list[ModelT]:
        """按等值条件过滤查询，支持排序字段（如 `-created_at` 表示倒序）。"""
        stmt = select(self.model)
        for key, value in filters.items():
            if value is None:
                continue
            stmt = stmt.where(getattr(self.model, key) == value)
        if order_by:
            column = getattr(self.model, order_by.lstrip("-"))
            stmt = stmt.order_by(column.desc() if order_by.startswith("-") else column)
        return list(self.session.scalars(stmt))

    def list_page(
        self,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "-created_at",
        **filters: Any,
    ) -> tuple[int, list[ModelT]]:
        """分页查询，返回 (总数, 当前页记录列表)。"""
        count_stmt = select(func.count()).select_from(self.model)
        for key, value in filters.items():
            if value is None:
                continue
            count_stmt = count_stmt.where(getattr(self.model, key) == value)
        total = self.session.execute(count_stmt).scalar_one()
        stmt = select(self.model)
        for key, value in filters.items():
            if value is None:
                continue
            stmt = stmt.where(getattr(self.model, key) == value)
        column = getattr(self.model, order_by.lstrip("-"))
        stmt = stmt.order_by(column.desc() if order_by.startswith("-") else column)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        items = list(self.session.scalars(stmt))
        return total, items
