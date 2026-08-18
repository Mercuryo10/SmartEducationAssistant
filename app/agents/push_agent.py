"""学习推送子图（docs/05 §5.5）：parse_plan → persist_tasks（创建任务）。

节点职责（对照 docs/05 §5.5）：
- parse_plan：解析「直接时间」（create）或「遗忘曲线计划」（plan，1/2/4/7 天），
  生成本次待创建的计划项列表（本地函数，不调用 LLM）。
- persist_tasks：把计划项批量写入 push_tasks（初始 pending），组装 push_result。

后台调度独立于本图（app/services/scheduler.py）：每 push_scan_interval 秒扫描
到期 pending 任务并渠道分发。入参经 push_payload 传入（create / plan 两种 action），
出错时置 error，API 层据此返回结构化错误（docs/04 §8）。
"""
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.state import AppState
from app.core.logging import get_logger
from app.services import push_service
from app.storage.repositories import KnowledgeRepository

logger = get_logger("push_agent")


def parse_plan(state: AppState) -> dict[str, Any]:
    """解析推送计划：直接时间（create）或遗忘曲线复习计划（plan，docs/05 §5.5）。"""
    action = state.get("push_action", "create")
    payload = state.get("push_payload") or {}

    if action == "create":
        items = [
            {
                "scheduled_at": payload["scheduled_at"],
                "content": payload["content"],
            }
        ]
        channel = payload.get("channel", "mock")
        logger.info("推送任务解析：单点触发 scheduled_at=%s", items[0]["scheduled_at"])
    else:  # plan：遗忘曲线
        kp_id = payload.get("knowledge_point_id")
        kp = KnowledgeRepository(state["session"]).get_knowledge_point(kp_id)
        if kp is None:
            return {"error": f"知识点不存在 id={kp_id}"}
        items = push_service.review_schedule(payload.get("start_date"), kp.name)
        channel = "mock"
        logger.info("遗忘曲线计划：kp=%s 复习点 %d 个", kp.name, len(items))

    return {"push_plan_items": items, "push_channel": channel}


def persist_tasks(state: AppState) -> dict[str, Any]:
    """把计划项写入 push_tasks（pending）并组装 push_result（docs/04 §7.2/§7.3）。"""
    action = state.get("push_action", "create")
    items = state.get("push_plan_items") or []
    channel = state.get("push_channel", "mock")
    tasks = push_service.create_push_tasks(state["session"], state["user_id"], items, channel)

    if action == "create":
        task = tasks[0]
        result = {"id": task.id, "status": task.status, "scheduled_at": task.scheduled_at}
    else:  # plan
        result = {"items": [{"scheduled_at": t.scheduled_at, "content": t.content} for t in tasks]}
    logger.info("推送任务已创建 action=%s 共 %d 条", action, len(tasks))
    return {"push_result": result}


def build_push_subgraph() -> CompiledStateGraph:
    """构建学习推送子图（docs/05 §5.5）；出错时短路到 END。"""
    g = StateGraph(AppState)
    g.add_node("parse_plan", parse_plan)
    g.add_node("persist_tasks", persist_tasks)

    g.add_edge(START, "parse_plan")
    g.add_conditional_edges(
        "parse_plan",
        lambda s: "persist_tasks" if not s.get("error") else "error",
        {"persist_tasks": "persist_tasks", "error": END},
    )
    g.add_edge("persist_tasks", END)
    return g.compile()
