"""鉴权接口（docs/04 §3）：注册 / 登录 / 当前用户。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.services import auth_service
from app.storage.db import get_session
from app.storage.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(body: RegisterRequest, session: Session = Depends(get_session)) -> UserOut:
    """注册新用户（用户名唯一）。"""
    user = auth_service.register_user(session, body.username, body.password, body.nickname)
    return UserOut.model_validate(user)


@router.post("/login")
def login(body: LoginRequest, session: Session = Depends(get_session)) -> TokenOut:
    """登录：校验密码并返回 JWT token。"""
    user = auth_service.login_user(session, body.username, body.password)
    token = auth_service.create_token(user.id)
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> UserOut:
    """当前登录用户信息。"""
    return UserOut.model_validate(user)
