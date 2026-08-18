"""Supervisor 主图（docs/05 §2/§4 / docs/09 阶段七）。

节点结构：supervisor（意图分类）→ 5 个子 Agent 子图 → aggregate（收尾）。

- supervisor_node：LLM 绑定 route_to_agent 工具做意图分类，归一化为 5 类之一；
  未知意图与 LLM 调用失败一律兜底到 qa（docs/05 §4「无法识别/闲聊回落到 qa」）。
- 各子图以 compiled 子图形式挂载（state schema 均为 AppState）。
- aggregate_node：chat 走主图且路由到非答疑任务时（无专用入参），
  给用户一条引导文案；答疑任务的结果已由 qa 子图流式产出，不再处理。

chat 接口（app/api/chat.py）走本主图；批改/错题/出题/推送四个接口仍独立
调用各自子图（docs/09 §7「其余接口独立可调」）。
"""
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.exercise_agent import build_exercise_subgraph
from app.agents.grading_agent import build_grading_subgraph
from app.agents.mistake_agent import build_mistake_subgraph
from app.agents.push_agent import build_push_subgraph
from app.agents.qa_agent import build_qa_subgraph
from app.agents.state import AppState
from app.core.logging import get_logger
from app.services.llm import get_chat_llm

logger = get_logger("supervisor")

_VALID_TASKS = {"qa", "grading", "mistake", "exercise", "push"}

# 任务中文名与「在对应面板操作」的引导文案（chat 误路由到非答疑任务时使用）
_TASK_LABELS = {
    "qa": "智能答疑",
    "grading": "作业批改",
    "mistake": "错题分析",
    "exercise": "练习生成",
    "push": "学习推送",
}
_TASK_GUIDE = {
    "grading": "请切换到「作业批改」面板，上传作业图片并填写参考答案",
    "mistake": "请切换到「错题分析」面板录入错题",
    "exercise": "请切换到「出题练习」面板选择知识点与难度生成练习",
    "push": "请切换到「学习推送」面板创建提醒或遗忘曲线复习计划",
}

# 各非答疑子图必需的状态入参（由各自专用接口写入；chat 走主图时不携带）
_REQUIRED_PAYLOAD = {
    "grading": "submission_id",
    "mistake": "mistake_action",
    "exercise": "exercise_payload",
    "push": "push_payload",
}


@tool
def route_to_agent(intent: str) -> str:
    """判断用户请求属于哪个教育任务。
    intent 取值：
    - qa: 知识问答/讲解/多模态提问
    - grading: 作业/试卷批改、判分
    - mistake: 错题录入、错题分析、薄弱点
    - exercise: 出题、练习题、组卷
    - push: 提醒、复习计划、推送
    """
    return intent


SYSTEM_PROMPT = """你是 EduMentor 的任务调度器。
请阅读用户输入与附件，用 route_to_agent 工具选择最合适的教育任务类别。
只调用一次工具，不要执行任务本身；无法判断时选择 qa。"""


def _extract_intent(resp: Any) -> str | None:
    """从 LLM 工具调用响应中解析 route_to_agent 的 intent 参数。

    Args:
        resp: llm.bind_tools(...).invoke() 返回的 AIMessage。

    Returns:
        intent 字符串；未调用工具或参数缺失时返回 None。
    """
    for call in getattr(resp, "tool_calls", None) or []:
        args = call.get("args") or {}
        intent = args.get("intent")
        if intent:
            return str(intent)
    return None


def supervisor_node(state: AppState) -> dict[str, Any]:
    """意图分类：LLM 工具调用决定 task；未知/失败兜底 qa（docs/05 §4）。"""
    intent: str | None = None
    try:
        llm = get_chat_llm(temperature=0)
        resp = llm.bind_tools([route_to_agent]).invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=state.get("query") or ""),
            ]
        )
        intent = _extract_intent(resp)
    except Exception as exc:
        logger.warning("Supervisor 意图分类失败，兜底 qa：%s", exc)

    task = intent if intent in _VALID_TASKS else "qa"
    # chat 走主图时不含非答疑子图的专用入参；缺失则收敛为 qa，避免子图缺参抛错
    required = _REQUIRED_PAYLOAD.get(task)
    if required and not state.get(required):
        logger.info("Supervisor 收敛 %s→qa（缺少入参 %s）", task, required)
        task = "qa"
    logger.info("Supervisor 路由 task=%s intent=%s", task, intent)
    return {"task": task}


def aggregate_node(state: AppState) -> dict[str, Any]:
    """聚合收尾：chat 误路由到非答疑任务且子图未产出结果时，给出引导文案。

    答疑任务的结果由 qa 子图逐 token 流式推送（token_queue），此处不再处理；
    非答疑任务经 /chat 进入时缺少专用入参，用引导文案优雅收尾。
    """
    task = state.get("task", "qa")
    q = state.get("token_queue")
    if task == "qa" or q is None:
        return {}
    produced = (
        state.get("qa_result")
        or state.get("grading_result")
        or state.get("mistake_result")
        or state.get("exercise_result")
        or state.get("push_result")
    )
    if produced:
        return {}
    guide = _TASK_GUIDE.get(task)
    if not guide:
        return {}
    text = f"已识别为「{_TASK_LABELS.get(task, task)}」：{guide}。"
    q.put({"type": "token", "text": text})
    q.put({"type": "eod"})
    logger.info("chat 主图路由到非答疑任务 %s，已推送引导文案", task)
    return {}


def build_graph() -> CompiledStateGraph:
    """构建 Supervisor 主图（docs/05 §2/§4）：决策 → 子图 → 聚合。"""
    g = StateGraph(AppState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("qa", build_qa_subgraph())
    g.add_node("grading", build_grading_subgraph())
    g.add_node("mistake", build_mistake_subgraph())
    g.add_node("exercise", build_exercise_subgraph())
    g.add_node("push", build_push_subgraph())
    g.add_node("aggregate", aggregate_node)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        lambda s: s.get("task", "qa"),  # supervisor_node 已归一化 task 合法
        {t: t for t in _VALID_TASKS},
    )
    for name in _VALID_TASKS:
        g.add_edge(name, "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()
