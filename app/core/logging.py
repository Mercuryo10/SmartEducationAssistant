"""统一日志配置（docs/08 §6）。

根 logger 名：edumentor。格式：`2026-08-17 10:00:00 [INFO] [模块] 消息`。
关键链路（OCR/ASR/检索/LLM/路由）必须记耗时日志。
"""
import logging


def setup_logging(level: str = "INFO") -> None:
    """配置全局日志格式与级别，应用启动时调用一次。

    Args:
        level: 日志级别（INFO/DEBUG 等），默认 INFO。
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("edumentor").setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """获取带 `edumentor.` 前缀的模块级 logger。

    Args:
        name: 模块名（如 "qa_agent"），返回 logger 名为 "edumentor.qa_agent"。
    """
    return logging.getLogger(f"edumentor.{name}")
