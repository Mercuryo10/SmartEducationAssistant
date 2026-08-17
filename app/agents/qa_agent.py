"""智能答疑子图（docs/05 §5.1）：preprocess → retrieve → generate → persist。

- preprocess：建/续会话、取历史、处理附件（OCR/ASR）、落库 user 消息与助手占位消息。
- retrieve：问题向量化 + 检索 top_k 片段（retrieve_knowledge 工具）。
- generate：组装 RAG 提示词 → LLM 流式生成，逐 token 推入线程安全队列。
- persist：把完整回答与溯源写回助手消息。

流式约定：preprocess 先推 `{"type":"meta",...}`，generate 推 `{"type":"token",...}`，
结束后推 `{"type":"eod"}`；API 层（SSE）消费该队列。
"""
import queue
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.state import AppState
from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError
from app.core.logging import get_logger
from app.services import rag_service
from app.services.llm import get_chat_llm
from app.storage.repositories import ConversationRepository
from app.tools.asr_tool import speech_to_text
from app.tools.ocr_tool import ocr_extract
from app.tools.retrieval_tool import retrieve_knowledge

logger = get_logger("qa_agent")

_HISTORY_LIMIT = 10  # 带入上下文的最近对话轮数


def preprocess(state: AppState) -> dict[str, Any]:
    """预处理：建/续会话、取历史、附件转写、落库占位消息。"""
    repo = ConversationRepository(state["session"])
    query = state["query"]

    # 1. 建会话或校验续接会话
    conv_id = state.get("conversation_id")
    if conv_id:
        conv = repo.get_by_id(conv_id)
        if conv is None:
            raise ResourceNotFoundError(f"会话不存在 id={conv_id}")
    else:
        conv = repo.create_conversation(state["user_id"], title=query[:30])
        conv_id = conv.id
        logger.info("新建会话 id=%s user_id=%s", conv_id, state["user_id"])

    # 2. 取历史（不含本轮新消息）
    old_msgs = repo.list_messages_by_conversation(conv_id)
    history = [{"role": m.role, "content": m.content} for m in old_msgs[-_HISTORY_LIMIT:]]

    # 3. 附件处理：图片→OCR，语音→转写，并入 query
    for att in state.get("attachments", []):
        if att.get("type") == "image":
            text = ocr_extract.invoke({"image_path": att["path"]})
            query += f"\n[图片内容]\n{text}"
            logger.info("图片已 OCR 并入问题，路径=%s", att["path"])
        elif att.get("type") == "audio":
            text = speech_to_text.invoke({"audio_path": att["path"]})
            query += f"\n[语音转写]\n{text}"
            logger.info("语音已转写并入问题，路径=%s", att["path"])

    # 4. 落库：user 消息 + 助手占位消息（meta 事件需要其 id）
    repo.create_message(conv_id, "user", query)
    assistant = repo.create_message(conv_id, "assistant", "")

    # 5. 推送 meta 事件（SSE 首帧：会话与消息标识）
    state["token_queue"].put(
        {"type": "meta", "conversation_id": conv_id, "message_id": assistant.id}
    )

    return {
        "conversation_id": conv_id,
        "assistant_message_id": assistant.id,
        "history": history,
        "query": query,
    }


def retrieve(state: AppState) -> dict[str, Any]:
    """检索：问题向量化 + 知识库召回 top_k 片段。"""
    results = retrieve_knowledge.invoke(
        {"query": state["query"], "top_k": settings.retrieve_top_k}
    )
    logger.info("检索召回 %d 条片段", len(results))
    return {"context": results}


def generate(state: AppState) -> dict[str, Any]:
    """生成：组装 RAG 提示词 → LLM 流式回答，逐 token 推入队列。"""
    messages = rag_service.get_rag_service().build_messages(
        query=state["query"], context=state.get("context", []), history=state.get("history")
    )
    llm = get_chat_llm(temperature=0.3)
    q: "queue.Queue[dict]" = state["token_queue"]
    full = ""
    for chunk in llm.stream(messages):
        piece = getattr(chunk, "content", None) or ""
        if not piece:
            continue
        q.put({"type": "token", "text": piece})
        full += piece
    q.put({"type": "eod"})
    logger.info("回答生成完成，长度 %d 字符", len(full))
    return {"qa_result": {"answer": full}}


def persist(state: AppState) -> dict[str, Any]:
    """持久化：把完整回答与溯源写回助手消息。"""
    repo = ConversationRepository(state["session"])
    qa = state["qa_result"]
    source_refs = rag_service.get_rag_service().build_source_refs(state.get("context", []))
    repo.update_message_content(state["assistant_message_id"], qa["answer"], source_refs)
    logger.info("助手消息已落库 message_id=%s 溯源 %d 条", state["assistant_message_id"], len(source_refs))
    return {"qa_result": {**qa, "source_refs": source_refs}}


def build_qa_subgraph() -> CompiledStateGraph:
    """构建答疑子图（docs/05 §5.1 节点序列）。"""
    g = StateGraph(AppState)
    g.add_node("preprocess", preprocess)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_node("persist", persist)
    g.add_edge(START, "preprocess")
    g.add_edge("preprocess", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "persist")
    g.add_edge("persist", END)
    return g.compile()
