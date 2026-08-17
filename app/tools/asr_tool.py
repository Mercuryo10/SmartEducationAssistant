"""语音转文字工具（docs/06 §4.2）：把音频转写为文本。"""
from langchain_core.tools import tool

from app.services import asr_service


@tool
def speech_to_text(audio_path: str) -> str:
    """把音频文件（语音提问）转写为文字。
    audio_path 为音频文件路径；返回转写文本。
    """
    return asr_service.transcribe(audio_path)


def register_tools() -> list:
    """返回本模块的全部工具，供 Agent 绑定。"""
    return [speech_to_text]
