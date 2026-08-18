"""练习生成子图（docs/05 §5.4）：resolve_template → fill_params → validate → polish。

节点职责（对照 docs/05 §5.4，可解校验与 LLM 润色拆分为独立节点）：
- resolve_template：按知识点/题型/难度查 exercises 表模板；知识点或模板缺失时报错。
- fill_params：按 count 逐道程序化填参（模板填充，答案唯一可解，docs/06 §4.5）。
- validate：可解性 + 答案自洽校验（choice 正确项唯一、选项不重复），不通过则剔除。
- polish：按难度调用 LLM 润色题干并生成解析（失败回退模板解析，不阻塞），
  同时把每题落库 generated_exercises（留痕）并组装 exercise_result。

练习生成请求（POST /api/v1/exercises/generate）入参经 exercise_payload 传入；
出错时置 error，API 层据此返回结构化错误。
"""
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.state import AppState
from app.core.logging import get_logger
from app.services import exercise_service
from app.storage.repositories import ExerciseRepository, KnowledgeRepository

logger = get_logger("exercise_agent")


def resolve_template(state: AppState) -> dict[str, Any]:
    """按入参查 exercises 模板（知识点/题型/难度）；返回模板列表供 fill_params 使用。"""
    payload = state.get("exercise_payload") or {}
    kp_id = payload.get("knowledge_point_id")
    qtype = payload.get("question_type", "solve")
    difficulty = payload.get("difficulty", "medium")

    kp = KnowledgeRepository(state["session"]).get_knowledge_point(kp_id)
    if kp is None:
        return {"error": f"知识点不存在 id={kp_id}"}

    rows = ExerciseRepository(state["session"]).list_by_knowledge_point(
        kp_id, question_type=qtype, difficulty=difficulty
    )
    if not rows:
        return {"error": f"该知识点暂无 {qtype}/{difficulty} 题型模板，请先运行 python scripts/init_db.py"}

    templates = [
        {
            "id": t.id,
            "question_type": t.question_type,
            "difficulty": t.difficulty,
            "template": t.template,
            "answer_template": t.answer_template,
            "params_schema": t.params_schema or {},
        }
        for t in rows
    ]
    logger.info("练习模板命中 kp=%s type=%s difficulty=%s 共 %d 套", kp.name, qtype, difficulty, len(templates))
    return {"exercise_templates": templates, "exercise_knowledge_point_name": kp.name}


def fill_params(state: AppState) -> dict[str, Any]:
    """按 count 逐道程序化生成题目草稿（模板填充 + 答案自洽，不调用 LLM）。"""
    payload = state.get("exercise_payload") or {}
    count = int(payload.get("count", 3))
    difficulty = payload.get("difficulty", "medium")
    templates = state.get("exercise_templates") or []
    if not templates:
        return {"error": "缺少练习模板，无法生成"}

    drafts: list[dict] = []
    for i in range(count):
        tpl = templates[i % len(templates)]
        drafts.append(
            exercise_service.generate_item(tpl, tpl.get("params_schema") or {}, difficulty)
        )
    logger.info("练习生成草稿 %d 道", len(drafts))
    return {"exercise_items": drafts}


def validate(state: AppState) -> dict[str, Any]:
    """可解性 + 答案自洽校验；剔除不合格题目，全不合格则报错。"""
    drafts = state.get("exercise_items") or []
    valid = [d for d in drafts if exercise_service.validate_item(d)]
    if len(valid) != len(drafts):
        logger.warning("部分题目未通过可解校验，已剔除 %d 道", len(drafts) - len(valid))
    if not valid:
        return {"error": "生成的题目未能通过可解校验，请重试"}
    return {"exercise_items": valid}


def polish(state: AppState) -> dict[str, Any]:
    """LLM 按难度润色 + 生成解析；每题落库 generated_exercises 并组装 exercise_result。"""
    payload = state.get("exercise_payload") or {}
    kp_id = payload.get("knowledge_point_id")
    difficulty = payload.get("difficulty", "medium")
    repo = ExerciseRepository(state["session"])

    items: list[dict] = []
    for d in state.get("exercise_items") or []:
        polished = exercise_service.polish_item(d, difficulty)
        item = {
            "question_text": polished["question_text"],
            "answer": polished["answer"],
            "explanation": polished["explanation"],
            "difficulty": difficulty,
            "knowledge_point_id": kp_id,
        }
        # 留痕：记录一次实际下发的题目（docs/03 §4.7 generated_exercises）
        try:
            repo.create_generated(
                user_id=state["user_id"],
                knowledge_point_id=kp_id,
                question_text=item["question_text"],
                answer=item["answer"],
                explanation=item["explanation"],
                difficulty=difficulty,
                exercise_id=polished.get("exercise_id"),
            )
        except Exception:
            logger.warning("练习留痕失败，不阻塞返回", exc_info=True)
        items.append(item)
    logger.info("练习生成完成 %d 道 difficulty=%s", len(items), difficulty)
    return {"exercise_result": {"items": items}}


def build_exercise_subgraph() -> CompiledStateGraph:
    """构建练习生成子图（docs/05 §5.4）；出错时直接短路到 END。"""
    g = StateGraph(AppState)
    g.add_node("resolve_template", resolve_template)
    g.add_node("fill_params", fill_params)
    g.add_node("validate", validate)
    g.add_node("polish", polish)

    g.add_edge(START, "resolve_template")
    g.add_conditional_edges(
        "resolve_template",
        lambda s: "fill_params" if not s.get("error") else "error",
        {"fill_params": "fill_params", "error": END},
    )
    g.add_edge("fill_params", "validate")
    g.add_conditional_edges(
        "validate",
        lambda s: "polish" if not s.get("error") else "error",
        {"polish": "polish", "error": END},
    )
    g.add_edge("polish", END)
    return g.compile()
