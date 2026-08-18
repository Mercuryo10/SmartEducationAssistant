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

    # --- 作业批改子图内部字段 ---
    submission_id: int            # 已创建的作业提交 id（API 层先落库 pending）
    answer_key: str | None        # 参考答案文本（docs/04 §5.1）
    question_type_hint: str | None  # 题型提示（choice+fill+solve）
    ocr_text: str                 # OCR 识别出的作业全文
    parsed_questions: list[dict]  # 切题结果 [{question_no, question_text, student_answer}]
    answer_map: dict              # {题号: 参考答案}
    question_types: list[str]     # 逐题题型（objective/subjective）
    grading_items: list[dict]     # 逐题批改明细（assemble 前累积）

    # --- 错题分析子图内部字段 ---
    mistake_action: str           # ingest（录入+关联） | explain（讲解）
    mistake_payload: dict         # 录入入参 {question_text, wrong_answer, correct_answer, knowledge_point_name}
    mistake_id: int               # 已录入/待讲解的错题 id
    mistake_knowledge_point_id: int | None  # 关联的知识点 id
    mistake_knowledge_point_name: str | None  # 关联的知识点名
