"""作业批改子图（docs/05 §5.2）：ocr → parse → grade_objective → grade_subjective → assemble。

- ocr：把上传图片 OCR 为文本；引擎不可用/识别失败时置 `error`（不崩溃，assemble 落 failed）。
- parse：按题号切分逐题明细 + 解析参考答案 + 判定题型。
- grade_objective：客观题纯规则判分（不消耗 LLM）。
- grade_subjective：主观题调用 LLM 给参考评分（标注 is_ai_scored）。
- assemble：汇总 summary + items，落库 homework_submissions / grading_results。
"""
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.state import AppState
from app.core.logging import get_logger
from app.services import grading_service
from app.storage.repositories import HomeworkRepository
from app.tools.grading_tool import grade_objective
from app.tools.ocr_tool import ocr_extract

logger = get_logger("grading_agent")


def _make_item(
    q: dict, qtype: str, ref: str, *, is_correct: bool | None = None,
    score: float | None = None, comment: str = "", is_ai_scored: bool = False, suggestion: str = "",
) -> dict:
    """把单题组装成批改明细（docs/04 §5.1 GradingItem 字段）。"""
    return {
        "question_no": q["question_no"],
        "question_type": qtype,
        "question_text": q["question_text"],
        "student_answer": q["student_answer"],
        "reference_answer": ref,
        "is_correct": is_correct,
        "score": score,
        "comment": comment,
        "is_ai_scored": is_ai_scored,
        "suggestion": suggestion,
    }


def ocr(state: AppState) -> dict[str, Any]:
    """把图片附件 OCR 为作业全文；失败置 error（不阻塞，由 assemble 落 failed）。"""
    texts: list[str] = []
    for att in state.get("attachments", []):
        if att.get("type") != "image":
            continue
        try:
            text = ocr_extract.invoke({"image_path": att["path"]})
        except Exception as exc:
            msg = getattr(exc, "detail", None) or getattr(exc, "message", None) or str(exc)
            logger.warning("作业图片 OCR 失败：%s", msg)
            return {"error": f"OCR 识别失败：{msg}"}
        texts.append(text)
    full_text = "\n".join(texts).strip()
    if not full_text:
        return {"error": "未能从图片中识别出任何文字，请重新拍摄或上传更清晰的作业照片"}
    logger.info("作业 OCR 完成，文本 %d 字符", len(full_text))
    return {"ocr_text": full_text}


def parse(state: AppState) -> dict[str, Any]:
    """切分 OCR 文本为逐题明细，解析参考答案并逐题判定题型。"""
    questions = grading_service.parse_homework_text(state.get("ocr_text", ""))
    answer_map = grading_service.parse_answer_key(state.get("answer_key"))
    hint = grading_service.resolve_type_hint(state.get("question_type_hint"))
    types = grading_service.resolve_question_types(questions, answer_map, hint)
    if not questions:
        return {"error": "作业文本无法切分出题目，请确认图片内容或补充参考答案"}
    logger.info("作业切分 %d 题", len(questions))
    return {
        "parsed_questions": questions,
        "answer_map": answer_map,
        "question_types": types,
    }


def grade_objective_node(state: AppState) -> dict[str, Any]:
    """客观题逐题规则判分，生成客观题批改明细。"""
    items: list[dict] = []
    for q, qtype in zip(state["parsed_questions"], state["question_types"]):
        if qtype != "objective":
            continue
        ref = state["answer_map"].get(q["question_no"], "")
        if not ref:
            items.append(_make_item(q, qtype, ref, is_correct=False, score=0.0, comment="缺少参考答案，无法判分"))
            continue
        result = grade_objective.invoke({"student_answer": q["student_answer"], "reference_answer": ref})
        items.append(
            _make_item(q, qtype, ref, is_correct=result["is_correct"], score=float(result["score"]), comment=result["comment"])
        )
    logger.info("客观题判分完成 %d 题", len(items))
    return {"grading_items": items}


def grade_subjective_node(state: AppState) -> dict[str, Any]:
    """主观题调用 LLM 评分，并入批改明细。"""
    items = list(state.get("grading_items", []))
    for q, qtype in zip(state["parsed_questions"], state["question_types"]):
        if qtype != "subjective":
            continue
        ref = state["answer_map"].get(q["question_no"], "")
        res = grading_service.grade_subjective(q["question_text"], ref, q["student_answer"])
        items.append(
            _make_item(
                q, qtype, ref,
                score=res["score"], comment=res["comment"],
                is_ai_scored=res["is_ai_scored"], suggestion=res["suggestion"],
            )
        )
    items.sort(key=lambda it: it["question_no"])
    logger.info("主观题评分完成 %d 题，明细共 %d 题", sum(1 for it in items if it["question_type"] == "subjective"), len(items))
    return {"grading_items": items}


def assemble(state: AppState) -> dict[str, Any]:
    """汇总 summary + items，落库提交状态与批改明细。"""
    repo = HomeworkRepository(state["session"])
    submission_id = state["submission_id"]

    if state.get("error"):
        repo.update_submission_status(submission_id, "failed")
        logger.warning("作业批改标记 failed submission_id=%s error=%s", submission_id, state["error"])
        return {
            "grading_result": {
                "submission_id": submission_id,
                "status": "failed",
                "error": state["error"],
                "items": [],
            }
        }

    items = state.get("grading_items", [])
    for it in items:
        repo.create_grading_result(
            submission_id=submission_id,
            question_no=it["question_no"],
            question_type=it["question_type"],
            question_text=it["question_text"],
            student_answer=it["student_answer"],
            reference_answer=it["reference_answer"],
            is_correct=it["is_correct"],
            score=it["score"],
            comment=it["comment"],
        )
    repo.update_submission_status(submission_id, "done", ocr_text=state.get("ocr_text"))

    objective_items = [it for it in items if it["question_type"] == "objective"]
    correct = sum(1 for it in items if it.get("is_correct"))
    objective_score = (
        round(100 * sum(1 for it in objective_items if it.get("is_correct")) / len(objective_items), 2)
        if objective_items
        else 0.0
    )
    summary = {"total": len(items), "correct": correct, "objective_score": objective_score}
    logger.info("作业批改完成 submission_id=%s 共 %d 题 对 %d 题", submission_id, len(items), correct)
    return {
        "grading_result": {
            "submission_id": submission_id,
            "status": "done",
            "summary": summary,
            "items": items,
        }
    }


def build_grading_subgraph() -> CompiledStateGraph:
    """构建作业批改子图（docs/05 §5.2 节点序列）。"""
    g = StateGraph(AppState)
    g.add_node("ocr", ocr)
    g.add_node("parse", parse)
    g.add_node("grade_objective", grade_objective_node)
    g.add_node("grade_subjective", grade_subjective_node)
    g.add_node("assemble", assemble)

    g.add_edge(START, "ocr")
    # OCR 失败（error 置位）直接跳到 assemble 落 failed，不阻塞
    g.add_conditional_edges(
        "ocr",
        lambda s: "parse" if not s.get("error") else "assemble",
        {"parse": "parse", "assemble": "assemble"},
    )
    g.add_edge("parse", "grade_objective")
    g.add_edge("grade_objective", "grade_subjective")
    g.add_edge("grade_subjective", "assemble")
    g.add_edge("assemble", END)
    return g.compile()
