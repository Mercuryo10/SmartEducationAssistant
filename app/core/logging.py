"""统一日志配置（docs/08 §6）。

- 控制台：输出到 stderr（开发调试直观）。
- 文件：同时写入 `logs/app.log`，RotatingFileHandler 按大小滚动（1MB × 5 份）。
- 应用自己的 logger 统一挂在 `edumentor.` 前缀下（如 `edumentor.qa_agent`）。
- 关键链路（OCR/ASR/检索/LLM/路由）必须记耗时日志。

日志目录 `logs/` 已加入 .gitignore，不会提交进仓库。
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "app.log"
_LOG_MAX_BYTES = 1_048_576  # 单个文件 1MB
_LOG_BACKUP_COUNT = 5  # 保留 5 个滚动文件
_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """配置全局日志：控制台（stderr）+ 文件（logs/app.log，滚动）。

    幂等：重复调用不会重复添加 handler（应用启动与脚本 main 各调一次）。

    Args:
        level: 日志级别（INFO/DEBUG 等），默认 INFO。
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    # 根 logger：保证有一个控制台 handler（记录 uvicorn / sqlalchemy 等库日志）
    root = logging.getLogger()
    root.setLevel(log_level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    # edumentor logger：追加文件 handler，应用日志同时落盘
    app_logger = logging.getLogger("edumentor")
    app_logger.setLevel(log_level)
    if not any(isinstance(h, RotatingFileHandler) for h in app_logger.handlers):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        app_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """获取带 `edumentor.` 前缀的模块级 logger。

    Args:
        name: 模块名（如 "qa_agent"），返回 logger 名为 "edumentor.qa_agent"。
    """
    return logging.getLogger(f"edumentor.{name}")
