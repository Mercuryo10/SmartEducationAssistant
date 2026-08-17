"""通用模型：错误响应、分页。"""
from pydantic import BaseModel


class ErrorOut(BaseModel):
    """统一错误响应体（docs/04 §8）。"""

    code: str
    message: str
    detail: object | None = None


class PageParams(BaseModel):
    """分页请求参数。"""

    page: int = 1
    page_size: int = 20
