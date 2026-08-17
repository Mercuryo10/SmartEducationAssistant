"""图片 OCR 工具（docs/06 §4.1）：把图片提取为文字。"""
from langchain_core.tools import tool

from app.services import ocr_service


@tool
def ocr_extract(image_path: str) -> str:
    """把图片（题目照片/作业照片）识别为文字。
    image_path 为图片文件路径；返回识别出的文本。
    """
    return ocr_service.extract_text(image_path)


def register_tools() -> list:
    """返回本模块的全部工具，供 Agent 绑定。"""
    return [ocr_extract]
