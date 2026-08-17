"""客观题判分工具（docs/06 §4.4）：纯规则实现，不消耗 LLM。

供作业批改子图（grading_agent）使用；也可独立调用验证。
"""
import re

from langchain_core.tools import tool

# 判断题布尔归一化集合
_BOOL_TRUE = {"对", "正确", "是", "√", "✓", "t", "true", "yes", "y"}
_BOOL_FALSE = {"错", "错误", "否", "×", "✗", "x", "false", "no", "n"}


def _norm(s: str) -> str:
    """文本归一化：去空白、全角转半角、统一小写。"""
    s = s.strip().lower()
    s = re.sub(r"[！-～]", lambda m: chr(ord(m.group()) - 0xFEE0), s)
    return re.sub(r"\s+", "", s)


def _choice_letter(s: str) -> str | None:
    """提取单选选项字母（b / (b) / 选b / 答案：b）。"""
    m = re.match(r"^(?:选|答案\s*[:：]?\s*)?[（(]?([a-h])[）)]?[.、．:]?$", s)
    return m.group(1) if m else None


@tool
def grade_objective(student_answer: str, reference_answer: str) -> dict:
    """客观题规则判分：比对学生答案与参考答案，返回是否判对。
    支持三种题型：
    - 选择题：取选项字母（A/B/C...）比对；
    - 判断题：对/错/√/×/T/F/正确/错误 归一化后比对；
    - 填空题：去除空白与全半角差异后整串比对，多空答案按 | 或 ； 分隔逐空比对。
    返回 {"is_correct": bool, "score": int(0 或 100), "comment": str}
    """
    if not student_answer or not reference_answer:
        return {"is_correct": False, "score": 0, "comment": "缺少学生答案或参考答案，无法判分"}
    ref = _norm(reference_answer)
    stu = _norm(student_answer)

    # 1) 判断题：布尔语义归一化后比较
    if ref in _BOOL_TRUE or ref in _BOOL_FALSE:
        correct = (stu in _BOOL_TRUE) == (ref in _BOOL_TRUE)
    # 2) 选择题：提取选项字母比较
    elif _choice_letter(ref):
        correct = _choice_letter(stu) == _choice_letter(ref)
    # 3) 填空题：多空逐空比对，否则整串比对
    else:
        ref_parts = [p for p in re.split(r"[|；;]", ref) if p]
        stu_parts = [p for p in re.split(r"[|；;]", stu) if p]
        if ref_parts and len(ref_parts) == len(stu_parts):
            correct = all(rp == sp for rp, sp in zip(ref_parts, stu_parts))
        else:
            correct = ref == stu

    comment = "" if correct else f"参考答案：{reference_answer}"
    return {"is_correct": correct, "score": 100 if correct else 0, "comment": comment}


def register_tools() -> list:
    """返回本模块的全部工具，供 Agent 绑定。"""
    return [grade_objective]
