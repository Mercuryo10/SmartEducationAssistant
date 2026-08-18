"""练习生成单测（docs/08 §10：exercise 参数生成的可解性）。

用合成模板 + 标准陈述库测试 generate_item / validate_item / verify_item，
校验「答案唯一、选项不重复、可代入验算」（docs/09 §5 验收）。不依赖 DB/LLM。
"""
import pytest

from app.core.exceptions import ValidationError
from app.services import exercise_service

# 标准陈述库（大模型/Agent 领域，保证答案唯一可解）
FACT = {
    "concept": "注意力机制",
    "true_statements": [
        "自注意力通过 Q/K/V 三个矩阵计算各位置的加权表示",
        "多头注意力让模型同时关注不同子空间的信息",
        "注意力权重经过 softmax 归一化后加权求和",
    ],
    "distractors": [
        "自注意力只能处理单个位置",
        "Q 与 V 相乘得到注意力权重",
        "注意力权重不需要归一化",
    ],
    "false_statement": "自注意力只需要 Q 和 K，不需要 V",
    "fill_question": "自注意力的输入通过____、____、____三个矩阵进行变换。",
    "fill_answer": "Q、K、V",
}

CHOICE_TEMPLATE = {
    "id": 1,
    "question_type": "choice",
    "template": "下列关于{concept}的说法，正确的是（  ）",
    "answer_template": "{letter}. {statement}",
}
FILL_TEMPLATE = {
    "id": 2,
    "question_type": "fill",
    "template": "填空题：{fill_question}",
    "answer_template": "{fill_answer}",
}
SOLVE_TEMPLATE = {
    "id": 3,
    "question_type": "solve",
    "template": "简答题：请阐述{concept}的核心原理。",
    "answer_template": "{points}",
}
SCHEMA = {"facts": [FACT]}


class TestChoice:
    """选择题：正确项唯一、选项不重复、可代入验算。"""

    @pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
    def test_solvable_all_difficulties(self, difficulty: str) -> None:
        for _ in range(5):
            draft = exercise_service.generate_item(CHOICE_TEMPLATE, SCHEMA, difficulty)
            assert exercise_service.validate_item(draft), f"{difficulty} 未通过可解校验"
            assert exercise_service.verify_item(draft), f"{difficulty} 答案代入验算失败"
            assert len(set(draft["options"])) == len(draft["options"])

    def test_repeated_generation_varies(self) -> None:
        texts = {
            exercise_service.generate_item(CHOICE_TEMPLATE, SCHEMA, "medium")["question_text"]
            for _ in range(6)
        }
        assert len(texts) >= 2, "多次生成题目应存在差异（选项乱序）"

    def test_hard_targets_false_statement(self) -> None:
        draft = exercise_service.generate_item(CHOICE_TEMPLATE, SCHEMA, "hard")
        assert FACT["false_statement"] in draft["answer_statement"]


class TestFillAndSolve:
    """填空 / 简答：题干与答案非空即可解。"""

    def test_fill_solvable(self) -> None:
        draft = exercise_service.generate_item(FILL_TEMPLATE, SCHEMA, "easy")
        assert exercise_service.validate_item(draft)
        assert draft["answer"] == FACT["fill_answer"]

    def test_solve_solvable(self) -> None:
        draft = exercise_service.generate_item(SOLVE_TEMPLATE, SCHEMA, "medium")
        assert exercise_service.validate_item(draft)
        assert FACT["concept"] in draft["question_text"]


class TestErrorPaths:
    """缺标准陈述库 / 坏模板必须抛结构化错误。"""

    def test_missing_facts_raises(self) -> None:
        with pytest.raises(ValidationError):
            exercise_service.generate_item(CHOICE_TEMPLATE, {}, "easy")

    def test_verify_empty_item_fails(self) -> None:
        assert not exercise_service.verify_item({"question_text": "", "answer": ""}, "choice")
