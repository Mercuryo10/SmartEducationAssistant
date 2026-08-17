"""仓储层：所有数据库访问统一走本层（docs/03 §7）。

约定：方法命名 get_*/create_*/update_*/delete_*/list_*，返回 ORM 对象或字典，不返回 SQL。
"""
from app.storage.repositories.base import BaseRepository
from app.storage.repositories.conversation_repo import ConversationRepository
from app.storage.repositories.exercise_repo import ExerciseRepository
from app.storage.repositories.homework_repo import HomeworkRepository
from app.storage.repositories.knowledge_repo import KnowledgeRepository
from app.storage.repositories.mistake_repo import MistakeRepository
from app.storage.repositories.push_repo import PushRepository
from app.storage.repositories.user_repo import UserRepository

__all__ = [
    "BaseRepository",
    "UserRepository",
    "ConversationRepository",
    "KnowledgeRepository",
    "HomeworkRepository",
    "MistakeRepository",
    "ExerciseRepository",
    "PushRepository",
]
