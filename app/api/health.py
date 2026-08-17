"""健康检查接口（docs/04 §9）。"""
from fastapi import APIRouter

from app.core.config import settings
from app.services.health_service import check_database, check_llm_config

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check() -> dict:
    """健康检查：返回应用、数据库与 LLM 配置状态。

    返回：
        {"status", "app", "version", "db", "llm"}；db 异常时状态降级为 degraded。
    """
    db_status = check_database()
    llm_status = check_llm_config()
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "db": db_status,
        "llm": llm_status,
    }
