"""共享图状态定义（docs/05 §3）。

所有子 Agent 共享 AppState：每个子 Agent 只写自己的 `*_result` 字段；
答疑内部字段（session / token_queue 等）仅 qa 子图使用。
"""
from typing import Any, TypedDict


class AppState(TypedDict, total=False):
    """LangGraph 图共享状态。"""

    # --- 输入（API 层写入） ---
    user_id: int
    conversation_id: int | None
    query: str                    # 用户原始输入（文本）
    attachments: list[dict]       # [{type: image|audio, path: str}]
    history: list[dict]           # 近期对话 [{role, content}]
    task: str                     # 意图分类结果: qa|grading|mistake|exercise|push
    session: Any                  # 数据库 Session（FASTAPI 依赖注入）
    token_queue: Any              # 线程安全队列，SSE 消费流式 token

    # --- 各子 Agent 输出 ---
    qa_result: dict               # {answer, source_refs}
    grading_result: dict
    mistake_result: dict
    exercise_result: dict
    push_result: dict
    error: str | None

    # --- 答疑子图内部字段 ---
    assistant_message_id: int     # 助手消息占位 id（meta 事件用）
    context: list[dict]           # 检索到的知识片段（retrieve 节点写入）
