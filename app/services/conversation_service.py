"""会话与消息服务（docs/04 §4）：隔离 api 层与 storage，供 chat 接口调用。"""
from app.core.exceptions import ResourceNotFoundError, UnauthorizedError
from app.storage.repositories import ConversationRepository


def list_user_conversations(session, user_id: int) -> list:
    """列出某用户会话（新→旧）。

    Args:
        session: 数据库会话。
        user_id: 用户 id。

    Returns:
        Conversation 对象列表。
    """
    return ConversationRepository(session).list_by_user(user_id)


def get_conversation_messages(session, conversation_id: int, user_id: int) -> list:
    """校验会话归属并返回消息（旧→新）。

    Args:
        session: 数据库会话。
        conversation_id: 会话 id。
        user_id: 当前用户 id（用于归属校验）。

    Returns:
        Message 对象列表；会话不存在或无权访问时抛对应异常。
    """
    repo = ConversationRepository(session)
    conv = repo.get_by_id(conversation_id)
    if conv is None:
        raise ResourceNotFoundError(f"会话不存在 id={conversation_id}")
    if conv.user_id != user_id:
        raise UnauthorizedError("无权访问该会话")
    return repo.list_messages_by_conversation(conversation_id)
