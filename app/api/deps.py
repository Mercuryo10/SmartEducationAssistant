"""API 通用依赖（docs/04 §1 鉴权简化约定）。"""
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.services.auth_service import resolve_current_user
from app.storage.db import get_session
from app.storage.models import User


def get_current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    """解析当前用户（依赖注入）。

    带 Bearer token 则校验并返回对应用户；
    `APP_ENV=dev` 下无 token 默认返回 demo 用户（docs/04 §1）。
    """
    return resolve_current_user(session, authorization)
