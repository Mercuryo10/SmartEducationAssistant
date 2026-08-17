"""faster-whisper 语音转写封装（docs/06 §4.2）：进程级单例 + 惰性加载。

重依赖（faster-whisper）仅在首次调用时 import，未安装时抛清晰的 ToolExecutionError；
关键链路记录转写耗时日志（docs/08 §6）。
"""
import time
from pathlib import Path

from app.core.exceptions import ToolExecutionError
from app.core.logging import get_logger

logger = get_logger("asr_service")

_model = None  # WhisperModel 单例


def get_model():
    """获取 faster-whisper 单例（惰性加载，CPU int8）。

    Returns:
        WhisperModel 实例；未安装时抛 ToolExecutionError。
    """
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ToolExecutionError(
                "语音转写引擎未就绪：请安装 faster-whisper（pip install faster-whisper）",
                detail=str(exc),
            )
        _model = WhisperModel("small", device="cpu", compute_type="int8")
        logger.info("faster-whisper 初始化完成（惰性加载，首次调用会下载模型）")
    return _model


def transcribe(audio_path: str, language: str = "zh") -> str:
    """把音频转写为文字。

    Args:
        audio_path: 音频文件路径。
        language: 语言，默认中文。

    Returns:
        转写文本；文件不存在或转写失败抛 ToolExecutionError。
    """
    path = Path(audio_path)
    if not path.exists():
        raise ToolExecutionError(f"音频文件不存在：{audio_path}")
    t0 = time.perf_counter()
    try:
        segments, _info = get_model().transcribe(str(path), language=language)
        text = "".join(s.text for s in segments).strip()
    except ToolExecutionError:
        raise
    except Exception as exc:
        logger.exception("语音转写失败: %s", exc)
        raise ToolExecutionError("语音转写失败", detail=str(exc))
    logger.info("ASR 转写 audio=%s chars=%d cost=%.2fs", path.name, len(text), time.perf_counter() - t0)
    return text
