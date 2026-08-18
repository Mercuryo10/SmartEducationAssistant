"""练习生成工具（docs/06 §4.5）：按模板程序化生成可解的练习题。

供练习生成子图（exercise_agent）在 fill 阶段使用，也可被 Supervisor 作为工具绑定
（数据全部由入参提供，无请求上下文依赖）。核心是「模板填充 + 可解校验」，
答案唯一、可代入验算；LLM 难度解析由 agent 的 polish 节点负责（docs/05 §5.4）。
"""
from langchain_core.tools import tool

from app.services import exercise_service


@tool
def generate_exercise(template: dict, params_schema: dict, difficulty: str) -> dict:
    """按模板程序化生成一道可解的练习题（含参考答案与解析）。
    template 为 exercises 表行：含 question_type/template/answer_template/id；
    params_schema 为该知识点的标准陈述库 {"facts": [...]}（保证答案唯一可解）；
    difficulty 为 easy / medium / hard。
    返回 {"question_text", "answer", "explanation"}。
    """
    draft = exercise_service.generate_item(template, params_schema, difficulty)
    return {
        "question_text": draft["question_text"],
        "answer": draft["answer"],
        "explanation": draft["explanation"],
    }


def register_tools() -> list:
    """返回本模块的全部工具，供 Agent 绑定。"""
    return [generate_exercise]
