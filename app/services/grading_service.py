"""作业批改业务服务（docs/09 阶段三）：作业文本切题、参考答案解析、主观题 AI 评分。

独立于 LangGraph，供 grading_tool / grading_agent 复用：
- 切题：把 OCR 作业文本按题号切分为逐题明细（题干 + 学生答案）。
- 解析参考答案：把 `1. 答案` / `第2题：答案` 格式文本解析为 {题号: 答案}。
- 题型判定：按参考答案格式启发式区分客观题（选择/判断/填空）与主观题。
- 主观题评分：调用当前 LLM 提供商（开发 DeepSeek / 生产本地 Qwen）给出参考评分。

关键链路（LLM 评分）必须记录耗时日志（docs/08 §6）。
"""
import json
import re
import time
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.logging import get_logger
from app.services.llm import get_chat_llm
from app.storage.models import GradingResult, HomeworkSubmission
from app.storage.repositories import HomeworkRepository

logger = get_logger("grading_service")


class ParsedQuestion(TypedDict):
    """切分后的单题：题号、题干、学生答案。"""

    question_no: int
    question_text: str
    student_answer: str


# ---------- 客观题判定常量 ----------

_BOOL_TRUE = {"对", "正确", "是", "√", "✓", "t", "true", "yes", "y"}
_BOOL_FALSE = {"错", "错误", "否", "×", "✗", "x", "false", "no", "n"}
_OBJECTIVE_MAX_LEN = 12  # 短答（<=12 字）按填空题（客观）处理


def _norm_text(s: str) -> str:
    """文本归一化：去空白、全角转半角、统一小写。"""
    s = s.strip().lower()
    s = re.sub(r"[！-～]", lambda m: chr(ord(m.group()) - 0xFEE0), s)
    return re.sub(r"\s+", "", s)


def _choice_letter(s: str) -> str | None:
    """从单选参考答案中提取选项字母（b / (b) / 选b / 答案：b）。"""
    m = re.match(r"^(?:选|答案\s*[:：]?\s*)?[（(]?([a-h])[）)]?[.、．:]?$", s)
    return m.group(1) if m else None


# ---------- 切题 ----------

# 题号开头正则：`1.` / `1、` / `1)` / `第1题` 等
_QUESTION_NO_RE = re.compile(r"^(?:第\s*)?(\d{1,3})\s*(?:[.、．)）:：]|题)")
# 学生答案标记：答：/ 答案：/ answer：
_ANSWER_MARKER_RE = re.compile(r"^\s*(?:答|答案|答?案)\s*[:：]?")


def parse_homework_text(text: str) -> list[ParsedQuestion]:
    """把 OCR 作业文本按题号切分为逐题明细。

    Args:
        text: OCR 识别出的作业全文。

    Returns:
        逐题列表（按题号升序）；无法识别题号时整体视为 1 题。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []

    # 定位题号行：行首为数字序号（跳过“答：”等答案行）
    starts: list[tuple[int, int]] = []
    for idx, ln in enumerate(lines):
        m = _QUESTION_NO_RE.match(ln)
        if m and (idx == 0 or not _ANSWER_MARKER_RE.match(ln)):
            starts.append((int(m.group(1)), idx))

    if not starts:
        q_text, answer = _split_q_and_answer("\n".join(lines))
        return [{"question_no": 1, "question_text": q_text, "student_answer": answer}]

    questions: list[ParsedQuestion] = []
    for i, (no, start_idx) in enumerate(starts):
        end_idx = starts[i + 1][1] if i + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start_idx:end_idx])
        q_text, answer = _split_q_and_answer(block)
        questions.append({"question_no": no, "question_text": q_text, "student_answer": answer})
    return questions


def _split_q_and_answer(block: str) -> tuple[str, str]:
    """把单题文本切为 (题干, 学生答案)。

    查找“答：”/“答案：”等标记；无标记时整段视为题干，学生答案为空。
    """
    text_lines: list[str] = []
    answer_lines: list[str] = []
    in_answer = False
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if not in_answer and _ANSWER_MARKER_RE.match(ln):
            in_answer = True
            answer_lines.append(_ANSWER_MARKER_RE.sub("", ln).strip())
        elif in_answer:
            answer_lines.append(ln)
        else:
            text_lines.append(ln)
    return "\n".join(text_lines).strip(), "\n".join(answer_lines).strip()


# ---------- 参考答案解析 ----------

_ANSWER_KEY_RE = re.compile(r"^(?:第\s*)?(\d{1,3})\s*(?:[.、．)）:：-]|题)\s*(.*)$")


def parse_answer_key(answer_key: str | None) -> dict[int, str]:
    """解析参考答案文本 → {题号: 答案}。

    每行形如 `1. Q、K、V` / `2: B` / `第3题：...`；无法解析的行忽略并告警。

    Args:
        answer_key: 参考答案原文（可为空）。

    Returns:
        题号到参考答案的映射。
    """
    result: dict[int, str] = {}
    if not answer_key:
        return result
    for ln in answer_key.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = _ANSWER_KEY_RE.match(ln)
        if m:
            result[int(m.group(1))] = m.group(2).strip()
        else:
            logger.warning("参考答案行无法解析，忽略：%s", ln)
    return result


# ---------- 题型判定 ----------


def classify_question_type(reference_answer: str) -> str:
    """按参考答案格式判定题型：objective（选择/判断/填空）或 subjective。

    Args:
        reference_answer: 该题参考答案。

    Returns:
        "objective" 或 "subjective"；无参考答案按主观题处理（交给 AI 评分）。
    """
    ref = _norm_text(reference_answer or "")
    if not ref:
        return "subjective"
    if _choice_letter(ref):
        return "objective"
    if ref in _BOOL_TRUE or ref in _BOOL_FALSE:
        return "objective"
    if len(ref) <= _OBJECTIVE_MAX_LEN and ref[-1] not in "。！？!?.":
        return "objective"
    return "subjective"


_HINT_OBJECTIVE = {"choice", "fill", "judgment", "objective"}


def resolve_question_types(
    questions: list[ParsedQuestion],
    answer_map: dict[int, str],
    hint: list[str] | None = None,
) -> list[str]:
    """逐题判定题型。

    Args:
        questions: 切分后的逐题明细。
        answer_map: 题号 → 参考答案。
        hint: 接口传入的题型提示（如 ["choice","fill","solve"]）；数量与题目一致时优先使用。

    Returns:
        与 questions 等长的题型列表（objective/subjective）。
    """
    use_hint = hint is not None and len(hint) == len(questions)
    return [
        ("objective" if hint[i] in _HINT_OBJECTIVE else "subjective")
        if use_hint
        else classify_question_type(answer_map.get(q["question_no"], ""))
        for i, q in enumerate(questions)
    ]


def resolve_type_hint(hint: str | None) -> list[str] | None:
    """解析题型提示字符串（`choice+fill+solve` 或 `choice,fill`）为列表。

    Args:
        hint: 原始提示字符串，可为空。

    Returns:
        规范化后的题型列表；为空或数量与题目不匹配时返回 None（改用规则判定）。
    """
    if not hint:
        return None
    parts = [p.strip() for p in re.split(r"[+,，、]", hint) if p.strip()]
    return parts or None


# ---------- 主观题 AI 评分 ----------

_SUBJECTIVE_SYSTEM = """你是《大模型导论》课程作业批改助手，批改对象为初学大模型的大学生。
请根据参考答案，对学生主观题作答给出参考评分(0-100)、一句话评语和改进建议。
只输出 JSON：{"score": 86, "comment": "一句话评语", "suggestion": "改进建议"}"""


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
    logger.warning("无法解析 LLM 评分输出：%.60s", content)
    return {}


def grade_subjective(
    question_text: str, reference_answer: str, student_answer: str
) -> dict[str, Any]:
    """调用 LLM 对主观题给出 AI 参考评分。

    Args:
        question_text: 题干。
        reference_answer: 参考答案（可为空）。
        student_answer: 学生作答。

    Returns:
        {"score": float, "comment": str, "suggestion": str, "is_ai_scored": bool}；
        未作答或 LLM 失败时 is_ai_scored=False（降级，不阻塞整份批改）。
    """
    if not student_answer:
        return {"score": 0.0, "comment": "未作答", "suggestion": "请补充作答内容", "is_ai_scored": False}
    t0 = time.perf_counter()
    try:
        llm = get_chat_llm(temperature=0.2)
        messages = [
            SystemMessage(content=_SUBJECTIVE_SYSTEM),
            HumanMessage(
                content=f"【题目】{question_text}\n【参考答案】{reference_answer or '（无）'}\n【学生作答】{student_answer}"
            ),
        ]
        resp = llm.invoke(messages)
        data = _parse_json_content(resp.content or "")
        score = max(0.0, min(100.0, float(data.get("score", 0) or 0)))
        logger.info("主观题评分完成 耗时=%.2fs", time.perf_counter() - t0)
        return {
            "score": round(score, 2),
            "comment": str(data.get("comment", "")),
            "suggestion": str(data.get("suggestion", "")),
            "is_ai_scored": True,
        }
    except Exception as exc:
        logger.exception("主观题 AI 评分失败: %s", exc)
        return {"score": 0.0, "comment": "AI 评分失败", "suggestion": str(exc), "is_ai_scored": False}


# ---------- 仓储封装（供 API 层调用，遵循 api → services → storage 单向依赖） ----------


def create_submission(
    session, user_id: int, image_paths: list[str], answer_key: str | None
) -> HomeworkSubmission:
    """创建作业提交记录（状态 pending，先落库以便失败也可复现）。"""
    return HomeworkRepository(session).create_submission(user_id, image_paths, answer_key)


def get_submission_for_user(
    session, user_id: int, submission_id: int
) -> HomeworkSubmission | None:
    """按 id + 用户取提交记录（校验归属）。"""
    return HomeworkRepository(session).get_submission_for_user(submission_id, user_id)


def mark_submission_failed(session, submission_id: int) -> None:
    """把提交状态标记为 failed（OCR 失败或处理异常时由调用方在回滚后调用）。"""
    HomeworkRepository(session).update_submission_status(submission_id, "failed")


def _item_from_result(r: GradingResult) -> dict[str, Any]:
    """把 ORM 批改明细转响应字典。"""
    return {
        "question_no": r.question_no,
        "question_type": r.question_type or "objective",
        "question_text": r.question_text or "",
        "student_answer": r.student_answer or "",
        "reference_answer": r.reference_answer or "",
        "is_correct": bool(r.is_correct) if r.is_correct is not None else None,
        "score": float(r.score) if r.score is not None else None,
        "comment": r.comment or "",
        "is_ai_scored": bool(r.question_type == "subjective"),
        "suggestion": "",
    }


def load_submission_result(session, submission: HomeworkSubmission) -> dict[str, Any]:
    """组装提交查询结果（summary + items，docs/04 §5.2）。"""
    repo = HomeworkRepository(session)
    results = repo.list_grading_results_by_submission(submission.id)
    items = [_item_from_result(r) for r in results]
    objective_items = [r for r in results if r.question_type == "objective"]
    correct = sum(1 for r in results if r.is_correct)
    objective_score = (
        round(100 * sum(1 for r in objective_items if r.is_correct) / len(objective_items), 2)
        if objective_items
        else 0.0
    )
    return {
        "submission_id": submission.id,
        "status": submission.status,
        "summary": {"total": len(results), "correct": correct, "objective_score": objective_score},
        "items": items,
    }
