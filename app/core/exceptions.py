"""统一异常体系（docs/08 §7）。

业务代码捕获底层异常后应记日志并转换为对应子类抛出；
路由层由全局异常处理器统一转为 `{"code","message","detail"}` JSON。
"""
from typing import Any


class EduMentorError(Exception):
    """业务异常基类，携带结构化错误码。"""

    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str = "内部错误", detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        """转换为 API 错误响应体（docs/04 §8）。"""
        return {"code": self.code, "message": self.message, "detail": self.detail}


class ToolExecutionError(EduMentorError):
    """工具执行失败（OCR/ASR/检索/批改等）。"""

    code = "TOOL_EXECUTION_ERROR"
    status_code = 502


class ModelCallError(EduMentorError):
    """上游模型调用失败（LLM / Embedding）。"""

    code = "LLM_ERROR"
    status_code = 502


class ResourceNotFoundError(EduMentorError):
    """资源不存在（数据库记录 / 文件等）。"""

    code = "NOT_FOUND"
    status_code = 404


class ValidationError(EduMentorError):
    """业务参数校验失败。"""

    code = "VALIDATION_ERROR"
    status_code = 400


class UnauthorizedError(EduMentorError):
    """未登录或凭证无效。"""

    code = "UNAUTHORIZED"
    status_code = 401
