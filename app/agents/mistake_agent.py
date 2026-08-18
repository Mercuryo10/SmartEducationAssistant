"""错题分析子图（docs/05 §5.3）：ingest → tag → explain，按入口流程条件路由。

两条流程（API 层用 `mistake_action` 指定）：
- ingest 流程（POST /mistakes 录入）：ingest → tag。
  - ingest：解析错题入参（可带图片附件，先 OCR 提取题干），落库 mistakes。
  - tag：自动关联知识点（优先按入参名称解析，缺省走 classify_knowledge_point 工具）。
- explain 流程（POST /mistakes/{id}/analyze 讲解）：仅 explain，生成结构化解讲并写回 error_type。

薄弱点 TopN / 错题列表 / 知识点列表为纯查询，不经过子图，由 API 层直调
mistake_service（docs/09 §4 验收 US-MS-*）。
"""
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.state import AppState
from app.core.logging import get_logger
from app.services import mistake_service
from app.storage.repositories import KnowledgeRepository, MistakeRepository
from app.tools.knowledge_tool import classify_knowledge_point
from app.tools.ocr_tool import ocr_extract

logger = get_logger("mistake_agent")


def ingest(state: AppState) -> dict[str, Any]:
    """解析错题入参并落库 mistakes；带图片附件时先 OCR 提取题干。

    返回 {mistake_id, mistake_knowledge_point_name}（tag 节点据此续接）；
    OCR 失败时置 error，调用方（API）按录入失败处理。
    """
    payload = state.get("mistake_payload") or {}
    question_text = str(payload.get("question_text", "")).strip()

    # 图片附件 → OCR 提取题干（与入参文本合并）
    for att in state.get("attachments", []):
        if att.get("type") != "image":
            continue
        try:
            text = ocr_extract.invoke({"image_path": att["path"]})
        except Exception as exc:
            msg = getattr(exc, "detail", None) or getattr(exc, "message", None) or str(exc)
            logger.warning("错题图片 OCR 失败：%s", msg)
            return {"error": f"错题图片 OCR 识别失败：{msg}"}
        question_text = (question_text + "\n" + text).strip()
        logger.info("错题图片 OCR 完成，文本 %d 字符", len(text))

    if not question_text:
        return {"error": "错题题干不能为空"}

    mistake = mistake_service.create_mistake(
        session=state["session"],
        user_id=state["user_id"],
        question_text=question_text,
        wrong_answer=str(payload.get("wrong_answer", "")).strip(),
        correct_answer=payload.get("correct_answer"),
    )
    logger.info("错题已录入 id=%s 题干=%.30s", mistake.id, question_text)
    return {
        "mistake_id": mistake.id,
        "mistake_knowledge_point_name": payload.get("knowledge_point_name"),
    }


def tag(state: AppState) -> dict[str, Any]:
    """自动关联知识点并写回错题记录，组装录入结果 mistake_result。

    优先级：入参 knowledge_point_name 精确解析 > classify_knowledge_point 工具
    （LLM 自动关联，失败回退关键词打分）；关联失败不阻塞录入（knowledge_point_id=None）。
    """
    payload = state.get("mistake_payload") or {}
    requested = payload.get("knowledge_point_name")
    kp_id: int | None = None
    kp_name: str | None = None

    kp_repo = KnowledgeRepository(state["session"])
    if requested:
        kp = kp_repo.get_knowledge_point_by_name(str(requested))
        if kp is not None:
            kp_id, kp_name = kp.id, kp.name
        else:
            logger.warning("入参知识点名未命中内置列表：%s，改为自动关联", requested)

    if kp_id is None:
        try:
            result = classify_knowledge_point.invoke({"text": str(payload.get("question_text", ""))})
            kp_id = result.get("knowledge_point_id")
            kp_name = result.get("knowledge_point_name")
        except Exception as exc:
            logger.warning("知识点自动关联失败：%s", exc)

    repo = MistakeRepository(state["session"])
    mistake = repo.get_by_id(state["mistake_id"])
    if mistake is not None and kp_id is not None:
        repo.update(mistake, knowledge_point_id=kp_id)
    logger.info("错题知识点关联 id=%s 知识点=%s", state["mistake_id"], kp_name)

    created_at = mistake.created_at if mistake is not None else None
    return {
        "mistake_knowledge_point_id": kp_id,
        "mistake_knowledge_point_name": kp_name,
        "mistake_result": {
            "id": state["mistake_id"],
            "knowledge_point_id": kp_id,
            "knowledge_point_name": kp_name,
            "created_at": created_at,
        },
    }


def explain(state: AppState) -> dict[str, Any]:
    """针对单题生成结构化解讲并写回 error_type，组装讲解结果 mistake_result。"""
    result = mistake_service.generate_explanation(
        session=state["session"],
        user_id=state["user_id"],
        mistake_id=state["mistake_id"],
    )
    return {"mistake_result": result}


def build_mistake_subgraph() -> CompiledStateGraph:
    """构建错题分析子图（docs/05 §5.3），按 mistake_action 条件路由入口。"""
    g = StateGraph(AppState)
    g.add_node("ingest", ingest)
    g.add_node("tag", tag)
    g.add_node("explain", explain)

    g.add_conditional_edges(
        START,
        lambda s: "ingest" if s.get("mistake_action") == "ingest" else "explain",
        {"ingest": "ingest", "explain": "explain"},
    )
    g.add_edge("ingest", "tag")
    g.add_edge("tag", END)
    g.add_edge("explain", END)
    return g.compile()
