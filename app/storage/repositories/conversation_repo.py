"""会话与消息仓储（docs/03 §7，覆盖 conversations + messages 两张表）。"""
from sqlalchemy import select

from app.storage.models import Conversation, Message
from app.storage.repositories.base import BaseRepository


class ConversationRepository(BaseRepository):
    """会话 + 消息的数据访问。"""

    model = Conversation

    def create_conversation(self, user_id: int, title: str = "新对话") -> Conversation:
        """新建会话。"""
        return self.create(user_id=user_id, title=title)

    def list_by_user(self, user_id: int) -> list[Conversation]:
        """列出某用户的会话（新→旧）。"""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
        )
        return list(self.session.scalars(stmt))

    def create_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        source_refs: list | None = None,
    ) -> Message:
        """在会话中追加一条消息（role: user/assistant/tool）。"""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            source_refs=source_refs,
        )
        self.session.add(msg)
        self.session.flush()
        return msg

    def list_messages_by_conversation(self, conversation_id: int) -> list[Message]:
        """列出会话全部消息（旧→新）。"""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        return list(self.session.scalars(stmt))
