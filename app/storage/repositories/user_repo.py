"""用户仓储（docs/03 §7）。"""
from app.storage.models import User
from app.storage.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    """用户表数据访问。"""

    model = User

    def get_by_username(self, username: str) -> User | None:
        """按用户名取用户（唯一）。"""
        return self.session.query(User).filter(User.username == username).first()

    def create_user(
        self, username: str, password_hash: str, nickname: str | None = None, role: str = "student"
    ) -> User:
        """创建用户，返回 ORM 对象。"""
        return self.create(
            username=username, password_hash=password_hash, nickname=nickname, role=role
        )
