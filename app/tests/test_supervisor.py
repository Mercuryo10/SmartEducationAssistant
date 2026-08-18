"""Supervisor 路由单测（docs/08 §10：supervisor 路由分类）。

用假 LLM 模拟 route_to_agent 工具调用，验证意图分类、未知意图兜底、
LLM 失败兜底，以及聚合节点对非答疑任务的引导文案。不依赖 DB / 真实 LLM。
"""
import queue
from types import SimpleNamespace

from app.agents.supervisor import (
    _VALID_TASKS,
    _extract_intent,
    aggregate_node,
    build_graph,
    supervisor_node,
)


class _FakeBind:
    """模拟 llm.bind_tools().invoke() 返回带工具调用的 AIMessage。"""

    def __init__(self, intent: str | None) -> None:
        self._intent = intent

    def invoke(self, _messages):
        calls = (
            [{"name": "route_to_agent", "args": {"intent": self._intent}, "id": "1", "type": "tool_call"}]
            if self._intent is not None
            else []
        )
        return SimpleNamespace(tool_calls=calls)


class _FakeLLM:
    """模拟 get_chat_llm() 返回的客户端。"""

    def __init__(self, intent: str | None) -> None:
        self._intent = intent

    def bind_tools(self, _tools):
        return _FakeBind(self._intent)


def _patch_llm(monkeypatch, intent: str | None):
    """把 supervisor 模块的 get_chat_llm 替换为假实现。"""
    monkeypatch.setattr(
        "app.agents.supervisor.get_chat_llm",
        lambda temperature=0.3: _FakeLLM(intent),
    )


# 各任务的必需入参（与 supervisor._REQUIRED_PAYLOAD 对应；qa 无要求）
_TASK_PAYLOAD = {
    "qa": {},
    "grading": {"submission_id": 1},
    "mistake": {"mistake_action": "ingest"},
    "exercise": {"exercise_payload": {"knowledge_point_id": 1}},
    "push": {"push_payload": {"content": "x", "scheduled_at": "2026-01-01T00:00:00"}},
}


def test_routes_each_valid_task(monkeypatch) -> None:
    for intent in sorted(_VALID_TASKS):
        _patch_llm(monkeypatch, intent)
        out = supervisor_node({"query": "测试输入", **_TASK_PAYLOAD[intent]})
        assert out["task"] == intent, f"{intent} 路由失败"


def test_unknown_intent_falls_back_to_qa(monkeypatch) -> None:
    _patch_llm(monkeypatch, "cook")
    assert supervisor_node({"query": "教我做菜"})["task"] == "qa"


def test_non_qa_without_payload_falls_back_to_qa(monkeypatch) -> None:
    # chat 走主图时不携带子图专用入参：grading 缺 submission_id → 收敛为 qa（不崩）
    _patch_llm(monkeypatch, "grading")
    assert supervisor_node({"query": "帮我批改作业"})["task"] == "qa"
    # 携带入参时保持原路由（专用接口经各自子图调用）
    _patch_llm(monkeypatch, "grading")
    assert supervisor_node({"query": "x", "submission_id": 1})["task"] == "grading"


def test_llm_failure_falls_back_to_qa(monkeypatch) -> None:
    def boom(temperature=0.3):
        raise RuntimeError("上游模型不可用")

    monkeypatch.setattr("app.agents.supervisor.get_chat_llm", boom)
    assert supervisor_node({"query": "x"})["task"] == "qa"


def test_extract_intent_no_tool_call() -> None:
    assert _extract_intent(SimpleNamespace(tool_calls=[])) is None


def test_build_graph_contains_all_subgraphs() -> None:
    nodes = set(build_graph().get_graph().nodes.keys())
    for name in _VALID_TASKS:
        assert name in nodes, f"主图缺少子图节点 {name}"
    assert "supervisor" in nodes and "aggregate" in nodes


def test_aggregate_guides_non_qa() -> None:
    q: "queue.Queue[dict]" = queue.Queue()
    state = {"task": "grading", "token_queue": q}
    aggregate_node(state)
    items = [q.get_nowait() for _ in range(q.qsize())]
    assert any(i["type"] == "token" for i in items), "应推送引导文案 token"
    assert any(i["type"] == "eod" for i in items), "应推送流结束 eod"


def test_aggregate_noop_for_qa() -> None:
    q: "queue.Queue[dict]" = queue.Queue()
    state = {"task": "qa", "token_queue": q, "qa_result": {"answer": "回答"}}
    assert aggregate_node(state) == {}
    assert q.empty()
