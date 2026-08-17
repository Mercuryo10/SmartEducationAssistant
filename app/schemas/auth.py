"""鉴权接口模型（docs/04 §3）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """注册请求。"""

    username: str = Field(min_length=2, max_length=64, description="用户名")
    password: str = Field(min_length=6, max_length=128, description="密码")
    nickname: str | None = Field(default=None, max_length=64, description="昵称")


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str
    password: str


class UserOut(BaseModel):
    """用户信息（不含密码）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    """登录响应：token + 用户信息。"""

    token: str
    user: UserOut
