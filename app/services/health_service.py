"""健康检查服务（docs/04 §9）。

路由层只调用本服务，避免 api 层直接操作 storage。
"""
from app.core.config import settings
from app.core.logging import get_logger
from app.storage.db import engine
from sqlalchemy import text

logger = get_logger("health")


def check_database() -> str:
    """探测 MySQL 是否可连接，返回 'ok' 或 'error'。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 —— 健康检查不抛错，只标记状态
        logger.error("health db check failed: %s", exc)
        return "error"


def check_llm_config() -> str:
    """按当前 LLM 提供商检查配置是否就绪，返回 'ok' / 'unconfigured' / 'error'。"""
    if settings.llm_provider == "local":
        return "ok"
    if settings.deepseek_api_key:
        return "ok"
    logger.warning("health: DEEPSEEK_API_KEY 未配置")
    return "unconfigured"
