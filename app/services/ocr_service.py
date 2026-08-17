"""OCR 服务（docs/06 §4.1）：进程级单例 + 惰性加载 + 引擎回退。

主后端为 PaddleOCR（docs/00 §3 技术栈）；Windows 安装困难时（其依赖 stringzilla
需本机编译，常失败，见 docs/09 §11 风险表）自动回退到 RapidOCR —— 同为
PP-OCRv4 模型、ONNX Runtime 推理，接口与效果近似。两个引擎都是首次调用才加载，
避免拖慢应用启动；关键链路记录耗时日志（docs/08 §6）。
业务层只调用本文件的 `extract_text`，不感知后端引擎。
"""
import time
from pathlib import Path

from app.core.exceptions import ToolExecutionError
from app.core.logging import get_logger

logger = get_logger("ocr_service")

_engine = None      # 已加载的 OCR 引擎实例
_engine_name = None  # 当前引擎名：paddleocr / rapidocr


def _load_paddleocr():
    """加载 PaddleOCR 引擎（原生产后端，PP-OCRv4）。"""
    from paddleocr import PaddleOCR

    return PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)


def _load_rapidocr():
    """加载 RapidOCR 引擎（轻量回退，ONNX 版 PP-OCRv4）。"""
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


# 引擎候选（按优先级）：PaddleOCR 安装成功则优先使用，否则回退 RapidOCR
_BACKENDS = [
    ("paddleocr", _load_paddleocr),
    ("rapidocr", _load_rapidocr),
]


def get_ocr():
    """获取 OCR 引擎单例（惰性加载，按可用性选引擎）。

    Returns:
        OCR 引擎实例；所有引擎均不可用（未安装）时抛 ToolExecutionError。
    """
    global _engine, _engine_name
    if _engine is None:
        for name, loader in _BACKENDS:
            try:
                _engine = loader()
                _engine_name = name
                logger.info("OCR 引擎就绪：%s（惰性加载，首次调用加载/下载模型）", name)
                return _engine
            except ImportError:
                logger.warning("OCR 引擎 %s 未安装，尝试下一个", name)
            except Exception as exc:  # 模型加载/下载失败也继续尝试下一个引擎
                logger.warning("OCR 引擎 %s 加载失败：%s", name, exc)
        raise ToolExecutionError(
            "OCR 引擎未就绪：请安装 paddleocr（pip install 'paddleocr>=2.7,<3.0'）或 rapidocr_onnxruntime"
        )
    return _engine


def _run_engine(engine, engine_name: str, image_path: str) -> list[str]:
    """按引擎分派识别调用，返回文本行列表。"""
    if engine_name == "paddleocr":
        res = engine.ocr(image_path, cls=True)
        return [line[1][0] for block in res for line in (block or [])]
    result, _elapse = engine(image_path)  # rapidocr 返回 (结果, 耗时)
    if not result:
        return []
    return [str(item[1]) for item in result]


def extract_text(image_path: str) -> str:
    """从图片中提取文字。

    Args:
        image_path: 图片文件路径。

    Returns:
        识别出的文本（按行拼接、去空行）；文件不存在或识别失败抛 ToolExecutionError。
    """
    path = Path(image_path)
    if not path.exists():
        raise ToolExecutionError(f"图片文件不存在：{image_path}")
    t0 = time.perf_counter()
    try:
        lines = _run_engine(get_ocr(), _engine_name, str(path))
    except ToolExecutionError:
        raise
    except Exception as exc:
        logger.exception("OCR 识别失败: %s", exc)
        raise ToolExecutionError("OCR 识别失败", detail=str(exc))
    text = "\n".join(ln for ln in lines if ln and ln.strip()).strip()
    logger.info(
        "OCR 识别 image=%s 引擎=%s chars=%d cost=%.2fs",
        path.name, _engine_name, len(text), time.perf_counter() - t0,
    )
    return text
