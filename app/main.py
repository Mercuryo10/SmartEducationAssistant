"""FastAPI 应用入口（docs/00 §5 / docs/09 阶段一）。

职责：
- 创建应用实例并挂载路由（前缀 /api/v1）。
- 注册全局异常处理器（docs/04 §8 统一错误结构）。
- 托管前端静态单页（app/static/index.html）。
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.exercises import router as exercises_router
from app.api.health import router as health_router
from app.api.homework import router as homework_router
from app.api.mistakes import knowledge_router, router as mistakes_router
from app.api.push import router as push_router
from app.core.config import settings
from app.core.exceptions import EduMentorError
from app.core.logging import get_logger, setup_logging
from app.services import scheduler

logger = get_logger("main")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期：初始化日志，启动学习推送调度器（docs/09 阶段六）。"""
    setup_logging()
    logger.info("%s v%s 启动（env=%s）", settings.app_name, settings.app_version, settings.app_env)
    scheduler.start_scheduler()
    yield
    scheduler.stop_scheduler()
    logger.info("%s 已关闭", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)


@app.exception_handler(EduMentorError)
async def edu_mentor_error_handler(_: Request, exc: EduMentorError) -> JSONResponse:
    """业务异常统一转为 `{"code","message","detail"}`（docs/04 §8）。"""
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """兜底异常：记日志并返回 INTERNAL_ERROR，避免泄露堆栈。"""
    logger.exception("未捕获异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "内部错误", "detail": str(exc)},
    )


# ---------- 路由 ----------
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(homework_router, prefix="/api/v1")
app.include_router(mistakes_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(exercises_router, prefix="/api/v1")
app.include_router(push_router, prefix="/api/v1")


# ---------- 前端静态页 ----------
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """返回前端单页入口。"""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
