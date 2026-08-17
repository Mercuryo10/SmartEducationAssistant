"""鉴权服务（docs/04 §3）：JWT 签发/校验、注册、登录、当前用户解析。

约定（docs/04 §1）：Bearer token 可选；`APP_ENV=dev` 下无 token 时默认返回 demo 用户。
"""
import time

import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError, ValidationError
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.storage.models import User
from app.storage.repositories import UserRepository

logger = get_logger("auth_service")


def _now() -> int:
    """当前时间戳（秒）。"""
    return int(time.time())


def create_token(user_id: int) -> str:
    """签发 JWT（HS256，有效期 settings.jwt_expire_seconds）。"""
    payload = {"sub": str(user_id), "exp": _now() + settings.jwt_expire_seconds}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> int:
    """校验 JWT 并返回 user_id；非法/过期抛 UnauthorizedError。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return int(payload["sub"])
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("凭证无效或已过期", detail=str(exc))


def register_user(session, username: str, password: str, nickname: str | None = None) -> User:
    """注册用户（用户名查重）。"""
    repo = UserRepository(session)
    if repo.get_by_username(username):
        raise ValidationError(f"用户名已存在：{username}")
    user = repo.create_user(username, hash_password(password), nickname)
    logger.info("新用户注册：%s (id=%s)", username, user.id)
    return user


def login_user(session, username: str, password: str) -> User:
    """校验用户名密码，返回用户。"""
    repo = UserRepository(session)
    user = repo.get_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("用户名或密码错误")
    return user


def resolve_current_user(session, authorization: str | None) -> User:
    """从 Authorization 头解析当前用户。

    Args:
        session: 数据库会话。
        authorization: `Bearer <token>` 头，可为空。

    Returns:
        用户；token 校验失败或非 dev 且未登录时抛 UnauthorizedError。
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        user_id = decode_token(token)
        user = UserRepository(session).get_by_id(user_id)
        if user is None:
            raise UnauthorizedError("用户不存在")
        return user
    if settings.app_env == "dev":
        user = UserRepository(session).get_by_username("demo")
        if user is not None:
            return user
    raise UnauthorizedError("未登录：请先登录获取 token")
