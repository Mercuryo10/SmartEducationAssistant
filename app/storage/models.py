"""ORM 模型（docs/03 §4 全部表，字段名与 DDL 完全一致）。

约定：created_at 统一存 UTC（naive datetime），展示层再转本地时区。
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.storage.db import Base

# BIGINT UNSIGNED 主键/外键类型别名（对齐 DDL）
UID = BIGINT(unsigned=True)


def utcnow() -> datetime:
    """返回当前 UTC 时间（naive，入库使用）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """用户表（docs/03 §4.1）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="student", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")
    homework_submissions: Mapped[list["HomeworkSubmission"]] = relationship(back_populates="user")
    mistakes: Mapped[list["Mistake"]] = relationship(back_populates="user")
    generated_exercises: Mapped[list["GeneratedExercise"]] = relationship(back_populates="user")
    push_tasks: Mapped[list["PushTask"]] = relationship(back_populates="user")


class Conversation(Base):
    """会话表（docs/03 §4.2）。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="新对话", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    """消息表（docs/03 §4.2）。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(UID, ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant / tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs: Mapped[list | None] = mapped_column(JSON)  # [{doc_id, source, snippet}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (Index("idx_messages_conv", "conversation_id"),)


class KnowledgeDoc(Base):
    """知识库文档表（docs/03 §4.3）。分块文本存向量库元数据，本表仅记录文档。"""

    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class KnowledgePoint(Base):
    """知识点表（docs/03 §4.4）。"""

    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(32), default="math", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(UID, ForeignKey("knowledge_points.id"))

    children: Mapped[list["KnowledgePoint"]] = relationship(back_populates="parent")
    parent: Mapped["KnowledgePoint | None"] = relationship(
        back_populates="children", remote_side="KnowledgePoint.id"
    )
    mistakes: Mapped[list["Mistake"]] = relationship(back_populates="knowledge_point")
    exercises: Mapped[list["Exercise"]] = relationship(back_populates="knowledge_point")


class HomeworkSubmission(Base):
    """作业提交表（docs/03 §4.5）。"""

    __tablename__ = "homework_submissions"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey("users.id"), nullable=False)
    image_paths: Mapped[list] = mapped_column(JSON, nullable=False)  # JSON 数组
    ocr_text: Mapped[str | None] = mapped_column(Text)
    answer_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="homework_submissions")
    grading_results: Mapped[list["GradingResult"]] = relationship(back_populates="submission")


class GradingResult(Base):
    """批改结果表（docs/03 §4.5）。"""

    __tablename__ = "grading_results"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(UID, ForeignKey("homework_submissions.id"), nullable=False)
    question_no: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str | None] = mapped_column(String(16))  # objective / subjective
    question_text: Mapped[str | None] = mapped_column(Text)
    student_answer: Mapped[str | None] = mapped_column(Text)
    reference_answer: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool | None] = mapped_column(Integer)  # 客观题 0/1
    score: Mapped[float | None] = mapped_column(DECIMAL(5, 2))  # 0-100
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    submission: Mapped[HomeworkSubmission] = relationship(back_populates="grading_results")

    __table_args__ = (Index("idx_grading_sub", "submission_id"),)


class Mistake(Base):
    """错题表（docs/03 §4.6）。"""

    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey("users.id"), nullable=False)
    knowledge_point_id: Mapped[int | None] = mapped_column(UID, ForeignKey("knowledge_points.id"))
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    wrong_answer: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(32))
    source_image: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="mistakes")
    knowledge_point: Mapped[KnowledgePoint | None] = relationship(back_populates="mistakes")

    __table_args__ = (
        Index("idx_mistakes_user", "user_id"),
        Index("idx_mistakes_kp", "knowledge_point_id"),
    )


class Exercise(Base):
    """练习题模板表（docs/03 §4.7）。"""

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        UID, ForeignKey("knowledge_points.id"), nullable=False
    )
    question_type: Mapped[str] = mapped_column(String(16), nullable=False)  # choice/fill/solve
    difficulty: Mapped[str] = mapped_column(String(8), default="medium", nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    answer_template: Mapped[str] = mapped_column(Text, nullable=False)
    params_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # {a:[1,9],...}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    knowledge_point: Mapped[KnowledgePoint] = relationship(back_populates="exercises")


class GeneratedExercise(Base):
    """实际生成/下发给用户的练习题（docs/03 §4.7）。"""

    __tablename__ = "generated_exercises"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey("users.id"), nullable=False)
    exercise_id: Mapped[int | None] = mapped_column(UID, ForeignKey("exercises.id"))
    knowledge_point_id: Mapped[int] = mapped_column(UID, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="generated_exercises")


class PushTask(Base):
    """推送任务表（docs/03 §4.8）。"""

    __tablename__ = "push_tasks"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(16), default="mock", nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="push_tasks")
    push_logs: Mapped[list["PushLog"]] = relationship(back_populates="task")

    __table_args__ = (Index("idx_push_tasks_time", "status", "scheduled_at"),)


class PushLog(Base):
    """推送日志表（docs/03 §4.8）。"""

    __tablename__ = "push_logs"

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(UID, ForeignKey("push_tasks.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # success/failed
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    task: Mapped[PushTask] = relationship(back_populates="push_logs")
