"""客观题判分工具单测（docs/08 §10：grade_objective 各题型边界）。

纯规则判分，不依赖 DB/LLM，可离线运行。
"""
import pytest

from app.tools.grading_tool import grade_objective


def _grade(student_answer: str, reference_answer: str) -> dict:
    """以 LangChain 工具调用方式触发判分。"""
    return grade_objective.invoke(
        {"student_answer": student_answer, "reference_answer": reference_answer}
    )


class TestChoice:
    """选择题：字母归一化（大小写 / 括号 / 「选」「答案：」前缀）。"""

    def test_letter_case_insensitive(self) -> None:
        r = _grade("b", "B")
        assert r["is_correct"] and r["score"] == 100

    def test_optional_format_accepted(self) -> None:
        assert _grade("答案：A", "(a)")["is_correct"]
        assert _grade("选C", "c")["is_correct"]
        assert _grade("D、", "D.")["is_correct"]

    def test_wrong_letter(self) -> None:
        r = _grade("A", "B")
        assert not r["is_correct"] and r["score"] == 0
        assert "参考答案" in r["comment"]

    def test_empty_input_fails(self) -> None:
        assert not _grade("", "B")["is_correct"]
        assert not _grade("B", "")["is_correct"]


class TestBoolean:
    """判断题：对/错/√/×/正确/错误 语义归一化。"""

    @pytest.mark.parametrize("student,ref", [("√", "对"), ("是", "正确"), ("正确", "是")])
    def test_true_synonyms(self, student: str, ref: str) -> None:
        assert _grade(student, ref)["is_correct"]

    @pytest.mark.parametrize("student,ref", [("×", "错"), ("错误", "否"), ("否", "×")])
    def test_false_synonyms(self, student: str, ref: str) -> None:
        assert _grade(student, ref)["is_correct"]

    @pytest.mark.parametrize("student,ref", [("对", "错"), ("√", "×"), ("正确", "错误")])
    def test_true_vs_false(self, student: str, ref: str) -> None:
        assert not _grade(student, ref)["is_correct"]


class TestFill:
    """填空题：空白/全半角归一化，多空按 | 或 ； 逐空比对。"""

    def test_full_width_and_space_normalized(self) -> None:
        assert _grade("Transformer", "transformer ")["is_correct"]

    def test_multi_blank_all_match(self) -> None:
        assert _grade("Q|K|V", "Q；K；V")["is_correct"]

    def test_multi_blank_partial_fails(self) -> None:
        assert not _grade("Q|K", "Q；K；V")["is_correct"]

    def test_exact_string_mismatch(self) -> None:
        assert not _grade("attention", "attention mechanism")["is_correct"]
