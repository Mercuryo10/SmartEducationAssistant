"""练习生成业务服务（docs/09 阶段五）：程序化填参 + 可解校验 + LLM 难度解析。

独立于 LangGraph，供 exercise_tool / exercise_agent / app/api/exercises.py 复用：
- `generate_item`：从模板（exercises 行 + params_schema 事实库）程序化生成一道题，
  保证「答案唯一、可代入验算」——choice 正确项唯一且选项不重复，fill/solve 答案非空。
- `polish_item`：按难度调用 LLM 生成解析（easy/medium/hard 深度递增），失败回退模板解析。
- `validate_item` / `verify_item`：可解性与答案自洽校验（docs/09 §5 验收「答案代入验算通过」）。

关键链路（LLM）必须记录耗时日志（docs/08 §6）。
"""
import json
import random
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.exceptions import ToolExecutionError, ValidationError
from app.core.logging import get_logger
from app.services.llm import get_chat_llm

logger = get_logger("exercise_service")

_LETTERS = "ABCD"


def _parse_json_content(content: str) -> dict[str, Any]:
    """从 LLM 输出解析 JSON（容忍 markdown 代码块与前后多余文本）。"""
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    logger.warning("无法解析 LLM 输出：%.60s", content)
    return {}


def _choice_statements(fact: dict, difficulty: str) -> tuple[list[str], str]:
    """按难度选取选项与正确项。

    - easy/medium：1 条正确表述 + 3 条似是而非的干扰项，答案 = 正确表述。
    - hard：3 条正确表述 + 1 条明显错误表述，答案 = 错误表述（「下列说法错误的是」）。

    Returns:
        (选项文本列表, 答案语句)。
    """
    true = [s for s in (fact.get("true_statements") or []) if s]
    distractors = [s for s in (fact.get("distractors") or []) if s]
    if difficulty == "hard":
        false_stmt = fact.get("false_statement") or ""
        statements = (true[:3] + [false_stmt])[:4]
        # 数据异常兜底：不足 4 项用干扰项补齐
        for d in distractors:
            if len(statements) >= 4:
                break
            if d not in statements:
                statements.append(d)
        while len(statements) < 4:
            statements.append(f"干扰项{len(statements) + 1}")
        return statements, false_stmt
    correct = true[0] if true else ""
    statements = ([correct] + distractors[:3])[:4]
    return statements, correct


def _build_draft(template: dict, fact: dict, difficulty: str) -> dict[str, Any]:
    """程序化组装一道题的草稿（题干/答案/选项，解析先给模板兜底，polish 再升级）。

    Returns:
        {question_type, difficulty, exercise_id, fact, question_text, answer,
         answer_statement, options?, explanation}。
    """
    qtype = template.get("question_type", "choice")
    concept = fact.get("concept", "")
    draft: dict[str, Any] = {
        "question_type": qtype,
        "difficulty": difficulty,
        "exercise_id": template.get("id"),
        "fact": fact,
    }
    stem_tpl = template.get("template") or ""
    answer_tpl = template.get("answer_template") or ""

    if qtype == "choice":
        statements, answer_stmt = _choice_statements(fact, difficulty)
        random.shuffle(statements)
        letter = _LETTERS[statements.index(answer_stmt)]
        stem = stem_tpl.format(concept=concept)
        options_block = "\n".join(f"{_LETTERS[i]}. {s}" for i, s in enumerate(statements))
        draft.update(
            question_text=f"{stem}\n{options_block}",
            answer=answer_tpl.format(letter=letter, statement=answer_stmt),
            answer_statement=answer_stmt,
            options=statements,
        )
    elif qtype == "fill":
        draft.update(
            question_text=stem_tpl.format(fill_question=fact.get("fill_question", "")),
            answer=answer_tpl.format(fill_answer=fact.get("fill_answer", "")),
            answer_statement=fact.get("fill_answer", ""),
        )
    else:  # solve
        points = "；".join(fact.get("true_statements", []))
        draft.update(
            question_text=stem_tpl.format(concept=concept),
            answer=answer_tpl.format(points=points),
            answer_statement=points,
        )
    draft["explanation"] = _fallback_explanation(draft)
    return draft


def _validate_draft(draft: dict) -> bool:
    """可解校验：choice 正确项唯一且选项不重复；fill/solve 题干与答案非空。"""
    if draft["question_type"] == "choice":
        opts = draft.get("options") or []
        if len(opts) < 2 or len(set(opts)) != len(opts):
            return False  # 选项重复
        ans = draft.get("answer_statement")
        if not ans or opts.count(ans) != 1:
            return False  # 正确项不唯一
        return bool(draft.get("answer"))
    return bool((draft.get("question_text") or "").strip() and (draft.get("answer") or "").strip())


def _fallback_explanation(draft: dict) -> str:
    """模板解析兜底：不依赖 LLM，仍按难度给出可用的说明（文档可解性验收兜底）。"""
    qtype = draft["question_type"]
    difficulty = draft["difficulty"]
    fact = draft.get("fact") or {}
    true = fact.get("true_statements") or []
    answer = draft.get("answer", "")
    if qtype == "choice":
        if difficulty == "hard":
            return (
                f"本题要求找出说法【错误】的选项。错误的是：{answer}。"
                f"依据：{true[1] if len(true) > 1 else ''}、{true[2] if len(true) > 2 else ''}，"
                f"因此「{fact.get('false_statement', '')}」的说法不成立。"
            )
        return (
            f"本题考查「{fact.get('concept', '')}」的基础概念。正确选项：{answer}。"
            f"其余选项分别错在：{'；'.join(fact.get('distractors', []))}。"
        )
    if qtype == "fill":
        return f"正确答案是「{answer}」。本题考查 {true[0] if true else ''}。"
    return (
        f"参考答案见上。学习建议：掌握「{fact.get('concept', '')}」的核心原理"
        f"（{true[0] if true else ''}），并通过实例理解关键步骤。"
    )


def generate_item(template: dict, params_schema: dict, difficulty: str) -> dict[str, Any]:
    """程序化生成一道可解的练习题（docs/06 §4.5 核心：填参 + 答案自洽校验）。

    Args:
        template: exercises 行字典（含 question_type/template/answer_template/id）。
        params_schema: 该知识点的标准陈述库，形如 {"facts": [...]}（保证答案唯一）。
        difficulty: easy / medium / hard。

    Returns:
        完整草稿字典（见 _build_draft）；多次未过可解校验时抛 ToolExecutionError。
    """
    facts = (params_schema or {}).get("facts") or []
    if not facts:
        raise ValidationError("模板缺少标准陈述库（params_schema.facts）")
    for _ in range(3):
        fact = random.choice(facts)
        draft = _build_draft(template, fact, difficulty)
        if _validate_draft(draft):
            return draft
    raise ToolExecutionError("练习生成多次未通过可解校验，请重试")


def validate_item(draft: dict) -> bool:
    """可解性 + 答案自洽校验（validate 节点调用）。"""
    return _validate_draft(draft)


def verify_item(item: dict, question_type: str | None = None) -> bool:
    """答案代入验算（docs/09 §5 验收）：从题干与答案反推是否可解、答案一致。

    - choice：答案的选项字母在题干选项中存在，且对应内容一致（代入验算）。
    - fill/solve：题干与答案均非空（填空答案可代回填空位，简答答案非空）。

    Args:
        item: {question_text, answer, question_type?}。
        question_type: 题型；缺省时从 item 内取。

    Returns:
        bool。
    """
    qtype = question_type or item.get("question_type")
    qtext = (item.get("question_text") or "").strip()
    answer = (item.get("answer") or "").strip()
    if not qtext or not answer:
        return False
    if qtype == "choice":
        letter = answer[0].upper()
        stmt = answer[1:].strip().lstrip("（(").rstrip(")）").strip()
        if not stmt:
            return False
        for line in qtext.splitlines():
            if line.startswith(f"{letter}."):
                return stmt in line
        return False
    return True


# ---------- LLM 难度适配解析（polish） ----------

_DIFFICULTY_RULES = {
    "easy": "- easy：基础概念识别。解析简洁直白，一句话点明正确/错误的原因。",
    "medium": "- medium：概念理解与对比。解析说明关键步骤或原理，并与常见错误理解对比。",
    "hard": "- hard：原理推导与综合。解析展开原理推导、指出易错点与常见误区。",
}

_POLISH_SYSTEM = """你是《大模型导论》课程的出题老师。请为下面这道已生成好的练习题润色题干并写出与难度匹配的解析。
规则：
1. 【答案内容与选项绝不许改动】。若题干含选项列表，选项内容与顺序必须原样保留在题干末尾。
2. 难度适配：
{difficulty_rule}
3. 只输出 JSON：{{"question_text": "润色后的题干（选项保持原样）", "explanation": "解析"}}
【题型】{qtype}
【原题干】{question_text}
【参考答案】{answer}"""


def _polished_question_ok(draft: dict, new_question: str) -> bool:
    """校验 LLM 润色后的题干仍可解：选项原样保留 / 填空位存在 / 概念仍出现。"""
    if not new_question:
        return False
    if draft["question_type"] == "choice":
        options = draft.get("options") or []
        return all(o in new_question for o in options)
    if draft["question_type"] == "fill":
        return "____" in new_question
    fact = draft.get("fact") or {}
    return bool(fact.get("concept")) and fact["concept"] in new_question


def polish_item(draft: dict, difficulty: str) -> dict[str, Any]:
    """按难度用 LLM 润色题干 + 生成解析；失败或不可解时回退模板版本（不阻塞）。

    Args:
        draft: generate_item 产出的草稿（含 fact/options/answer_statement）。
        difficulty: easy / medium / hard。

    Returns:
        与 draft 同构但 question_text/explanation 可能被 LLM 升级的草稿。
    """
    new_question, explanation = "", ""
    t0 = time.perf_counter()
    try:
        llm = get_chat_llm(temperature=0.5)
        resp = llm.invoke(
            [
                SystemMessage(
                    content=_POLISH_SYSTEM.format(
                        difficulty_rule=_DIFFICULTY_RULES.get(difficulty, ""),
                        qtype=draft["question_type"],
                        question_text=draft["question_text"],
                        answer=draft["answer"],
                    )
                ),
                HumanMessage(content="请开始润色。"),
            ]
        )
        logger.info("练习解析 LLM 润色完成 耗时=%.2fs", time.perf_counter() - t0)
        data = _parse_json_content(resp.content or "")
        new_question = str(data.get("question_text", "")).strip()
        explanation = str(data.get("explanation", "")).strip()
    except Exception as exc:
        logger.exception("练习解析 LLM 润色失败，回退模板解析：%s", exc)

    polished = dict(draft)
    if new_question and _polished_question_ok(draft, new_question):
        polished["question_text"] = new_question
    polished["explanation"] = explanation or draft["explanation"]
    return polished
