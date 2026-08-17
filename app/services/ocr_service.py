"""PaddleOCR 封装（docs/06 §4.1）：进程级单例 + 惰性加载。

重依赖（paddleocr）仅在首次调用时 import，未安装时抛清晰的 ToolExecutionError，
不影响应用启动；关键链路记录 OCR 耗时日志（docs/08 §6）。
"""
import time
from pathlib import Path

from app.core.exceptions import ToolExecutionError
from app.core.logging import get_logger

logger = get_logger("ocr_service")

_ocr = None  # PaddleOCR 单例


def get_ocr():
    """获取 PaddleOCR 单例（惰性加载，首次调用才初始化）。

    Returns:
        PaddleOCR 实例；未安装时抛 ToolExecutionError。
    """
    global _ocr
    if _ocr is None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ToolExecutionError(
                "OCR 引擎未就绪：请安装 paddleocr（pip install 'paddleocr>=2.7,<3.0'）",
                detail=str(exc),
            )
        _ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        logger.info("PaddleOCR 初始化完成（惰性加载，首次调用会下载模型）")
    return _ocr


def extract_text(image_path: str) -> str:
    """从图片中提取文字。

    Args:
        image_path: 图片文件路径。

    Returns:
        识别出的文本（按行拼接）；文件不存在或识别失败抛 ToolExecutionError。
    """
    path = Path(image_path)
    if not path.exists():
        raise ToolExecutionError(f"图片文件不存在：{image_path}")
    t0 = time.perf_counter()
    try:
        res = get_ocr().ocr(str(path), cls=True)
    except ToolExecutionError:
        raise
    except Exception as exc:
        logger.exception("OCR 识别失败: %s", exc)
        raise ToolExecutionError("OCR 识别失败", detail=str(exc))
    lines = [line[1][0] for block in res for line in (block or [])]
    text = "\n".join(lines).strip()
    logger.info("OCR 识别 image=%s chars=%d cost=%.2fs", path.name, len(text), time.perf_counter() - t0)
    return text
