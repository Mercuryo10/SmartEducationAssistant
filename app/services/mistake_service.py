"""错题分析业务服务（docs/09 阶段四）：知识点自动关联、错题增查、薄弱点 TopN、结构化解讲。

独立于 LangGraph，供 knowledge_tool / mistake_agent / app/api/mistakes.py 复用：
- 知识点关联：优先 LLM 从内置知识点列表选最匹配项；LLM 不可用时回退关键词/别名打分
  （保证「录入自动关联知识点」在无 Key / 模型抖动时仍可用）。
- 薄弱点 TopN：纯 SQL 按知识点统计错误次数（数据真实，不虚构，docs/09 §4 验收）。
- 结构化解讲：调用当前 LLM 提供商给出错误模式/讲解/常见错误/变式题（docs/05 §5.3）。

关键链路（LLM）必须记录耗时日志（docs/08 §6）。
"""
import json
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError
from app.core.logging import get_logger
from app.services.llm import get_chat_llm
from app.storage.db import SessionLocal
from app.storage.models import Mistake
from app.storage.repositories import KnowledgeRepository, MistakeRepository

logger = get_logger("mistake_service")

# 常见术语 → 内置知识点名的别名表（LLM 不可用时的确定性回退，保证可验收）
_ALIASES = {
    "rag": "检索增强生成（RAG）",
    "检索增强": "检索增强生成（RAG）",
    "langgraph": "多 Agent 编排（LangGraph）",
    "agent": "多 Agent 编排（LangGraph）",
    "supervisor": "多 Agent 编排（LangGraph）",
    "attention": "Transformer 与注意力机制",
    "注意力": "Transformer 与注意力机制",
    "transformer": "Transformer 与注意力机制",
    "embedding": "向量检索与语义嵌入",
    "向量检索": "向量检索与语义嵌入",
    "语义嵌入": "向量检索与语义嵌入",
    "prompt": "提示词工程",
    "提示词": "提示词工程",
    "思维链": "提示词工程",
    "few-shot": "提示词工程",
}


def _norm_text(s: str) -> str:
    """文本归一化：去空白、全角转半角、统一小写。"""
    s = s.strip().lower()
    s = re.sub(r"[！-～]", lambda m: chr(ord(m.group()) - 0xFEE0), s)
    return re.sub(r"\s+", "", s)


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
    logger.warning("无法解析 LLM 输出：%.60s", content)
    return {}


# ---------- 知识点自动关联 ----------

_CLASSIFY_SYSTEM = """你是 EduMentor 的知识点分类器，面向学习大模型/Agent 的大学生。
根据错题文本，从候选知识点列表中选出最匹配的一个（只能从列表选，不要自创）。
候选知识点：
{candidates}
只输出 JSON：{{"name": "知识点名", "confidence": 0.0~1.0}}"""


def _llm_classify(text: str, kps: list) -> tuple[str | None, float]:
    """用当前 LLM 从候选知识点中选最匹配项。

    Args:
        text: 错题文本。
        kps: KnowledgePoint 列表。

    Returns:
        (知识点名, 置信度)；解析失败或名字不在候选列表时返回 (None, 0.0)。
    """
    candidates = "\n".join(f"- {kp.name}: {kp.description or ''}" for kp in kps)
    t0 = time.perf_counter()
    llm = get_chat_llm(temperature=0.0)
    resp = llm.invoke(
        [
            SystemMessage(content=_CLASSIFY_SYSTEM.format(candidates=candidates)),
            HumanMessage(content=f"【错题文本】{text}"),
        ]
    )
    logger.info("知识点 LLM 分类完成 耗时=%.2fs", time.perf_counter() - t0)
    data = _parse_json_content(resp.content or "")
    name = str(data.get("name", "")).strip()
    if not name:
        return None, 0.0
    norm_name = _norm_text(name)
    for kp in kps:
        if _norm_text(kp.name) == norm_name:
            return kp.name, min(1.0, max(0.0, float(data.get("confidence", 0.8))))
    # LLM 可能带括号差异/多余字样，做包含匹配
    for kp in kps:
        if _norm_text(kp.name) in norm_name or norm_name in _norm_text(kp.name):
            return kp.name, 0.7
    logger.warning("LLM 分类结果不在候选知识点列表：%s", name)
    return None, 0.0


def _keyword_classify(text: str, kps: list) -> tuple[str | None, float]:
    """关键词/别名打分回退：从文本中匹配别名或知识点名片段，返回最高分项。

    Args:
        text: 错题文本。
        kps: KnowledgePoint 列表。

    Returns:
        (知识点名, 置信度 0~1)；无任何匹配时返回 (None, 0.0)。
    """
    norm = _norm_text(text)
    best_name: str | None = None
    best_score = 0
    # 1) 别名精确匹配（优先）
    for alias, kp_name in _ALIASES.items():
        if _norm_text(alias) in norm:
            score = len(_norm_text(alias))
            if score > best_score:
                best_name, best_score = kp_name, score
    # 2) 知识点名本身/描述片段出现在文本中
    for kp in kps:
        for fragment in (kp.name, kp.description or ""):
            frag = _norm_text(fragment)
            if len(frag) >= 2 and frag in norm:
                score = len(frag)
                if score > best_score:
                    best_name, best_score = kp.name, score
    if best_name is None or best_score == 0:
        return None, 0.0
    confidence = min(1.0, best_score / max(len(norm), 1) * 2 + 0.3)
    return best_name, confidence


def classify_knowledge_point(text: str, session: Session | None = None) -> dict:
    """自动关联知识点：LLM 优先，失败回退关键词打分。

    Args:
        text: 错题文本（题干 + 错误答案等）。
        session: 可选数据库会话；缺省时自建短会话（供工具独立调用）。

    Returns:
        {"knowledge_point_id": int|None, "knowledge_point_name": str|None, "confidence": float}。
    """
    owns_session = session is None
    s = session or SessionLocal()
    try:
        kps = KnowledgeRepository(s).list_knowledge_points()
        if not kps or not (text or "").strip():
            return {"knowledge_point_id": None, "knowledge_point_name": None, "confidence": 0.0}
        name: str | None
        confidence: float
        try:
            name, confidence = _llm_classify(text, kps)
        except Exception as exc:
            logger.warning("知识点 LLM 分类失败，回退关键词打分：%s", exc)
            name, confidence = _keyword_classify(text, kps)
        if name is None:
            logger.info("未能自动关联知识点 text=%.30s", text)
            return {"knowledge_point_id": None, "knowledge_point_name": None, "confidence": 0.0}
        kp = KnowledgeRepository(s).get_knowledge_point_by_name(name)
        return {
            "knowledge_point_id": kp.id if kp is not None else None,
            "knowledge_point_name": name,
            "confidence": round(confidence, 2),
        }
    finally:
        if owns_session:
            s.close()


# ---------- 错题增查 / 薄弱点 / 知识点列表（供 API 层调用） ----------


def create_mistake(
    session: Session,
    user_id: int,
    question_text: str,
    wrong_answer: str,
    correct_answer: str | None = None,
    knowledge_point_id: int | None = None,
) -> Mistake:
    """录入一条错题（供 ingest 节点落库）。"""
    return MistakeRepository(session).create_mistake(
        user_id=user_id,
        question_text=question_text,
        wrong_answer=wrong_answer,
        correct_answer=correct_answer,
        knowledge_point_id=knowledge_point_id,
    )


def get_mistake_for_user(session: Session, user_id: int, mistake_id: int) -> Mistake | None:
    """按 id + 用户取错题（校验归属）。"""
    return MistakeRepository(session).get_mistake_for_user(mistake_id, user_id)


def _mistake_to_dict(m: Mistake) -> dict[str, Any]:
    """把 ORM 错题对象转列表响应字典（含知识点名）。"""
    kp = m.knowledge_point
    return {
        "id": m.id,
        "question_text": m.question_text,
        "wrong_answer": m.wrong_answer,
        "correct_answer": m.correct_answer,
        "error_type": m.error_type,
        "knowledge_point_id": m.knowledge_point_id,
        "knowledge_point_name": kp.name if kp is not None else None,
        "created_at": m.created_at,
    }


def list_mistakes(
    session: Session,
    user_id: int,
    knowledge_point_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页列出错题（可按知识点过滤），响应结构与 docs/04 §6.2 一致。"""
    total, items = MistakeRepository(session).list_by_user_with_knowledge(
        user_id, knowledge_point_id=knowledge_point_id, page=page, page_size=page_size
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_mistake_to_dict(m) for m in items],
    }


def weak_points_topn(session: Session, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """统计薄弱知识点 TopN（按错误次数降序，数据真实）。"""
    return MistakeRepository(session).count_by_knowledge_point(user_id, limit=limit)


def list_knowledge_points(session: Session) -> list:
    """列出全部内置知识点。"""
    return KnowledgeRepository(session).list_knowledge_points()


# ---------- 错题结构化解讲（docs/05 §5.3） ----------

_EXPLAIN_SYSTEM = """你是大模型课程错题讲解老师，面向初学大模型的大学生。
请针对下面错题给出：
1. 错误模式分析（概念混淆/理解偏差/原理记忆不清等）
2. 该知识点完整讲解
3. 常见错误清单（最多3条）
4. 一道同类变式练习题
只输出 JSON：{"error_pattern": "...", "explanation": "...", "common_mistakes": ["..."], "variant": "..."}"""


def _derive_error_type(analysis: str) -> str | None:
    """从错误模式分析中提取短标签（写入 mistakes.error_type，docs/03 §4.6）。"""
    if not analysis:
        return None
    for keyword, label in (
        ("概念", "概念混淆"),
        ("理解", "理解偏差"),
        ("记忆", "原理记忆不清"),
        ("计算", "计算失误"),
        ("逻辑", "逻辑推理错误"),
    ):
        if keyword in analysis:
            return label
    return None


def generate_explanation(session: Session, user_id: int, mistake_id: int) -> dict[str, Any]:
    """生成单题结构化解讲（docs/04 §6.3）：错误模式 + 知识点讲解 + 常见错误 + 变式题。

    Args:
        session: 数据库会话。
        user_id: 当前用户（归属校验）。
        mistake_id: 错题 id。

    Returns:
        {mistake_id, knowledge_point, analysis, explanation, common_mistakes, variant_exercise}；
        LLM 失败时降级为明确提示，仍返回完整结构（不阻塞接口）。
    """
    repo = MistakeRepository(session)
    mistake = repo.get_mistake_for_user(mistake_id, user_id)
    if mistake is None:
        raise ResourceNotFoundError(f"错题不存在 id={mistake_id}")
    kp_name = mistake.knowledge_point.name if mistake.knowledge_point is not None else None

    analysis = explanation = variant = ""
    common_mistakes: list[str] = []
    t0 = time.perf_counter()
    try:
        llm = get_chat_llm(temperature=0.3)
        resp = llm.invoke(
            [
                SystemMessage(content=_EXPLAIN_SYSTEM),
                HumanMessage(
                    content=(
                        f"【知识点】{kp_name or '（未标注）'}\n"
                        f"【题目】{mistake.question_text}\n"
                        f"【错误答案】{mistake.wrong_answer or '（无）'}\n"
                        f"【正确答案】{mistake.correct_answer or '（无）'}"
                    )
                ),
            ]
        )
        logger.info("错题讲解 LLM 生成完成 耗时=%.2fs", time.perf_counter() - t0)
        data = _parse_json_content(resp.content or "")
        analysis = str(data.get("error_pattern", "")).strip()
        explanation = str(data.get("explanation", "")).strip()
        variant = str(data.get("variant", "")).strip()
        raw_mistakes = data.get("common_mistakes", [])
        if isinstance(raw_mistakes, list):
            common_mistakes = [str(m).strip() for m in raw_mistakes if str(m).strip()]
    except Exception as exc:
        logger.exception("错题讲解 LLM 生成失败: %s", exc)
        analysis = "LLM 讲解服务暂不可用，请稍后重试"
        explanation = ""
        variant = ""
        common_mistakes = []

    # 把错误模式写入错题记录（列表展示用），失败不阻塞
    error_type = _derive_error_type(analysis)
    if error_type:
        try:
            repo.update(mistake, error_type=error_type)
        except Exception:
            logger.warning("更新错题 error_type 失败", exc_info=True)

    return {
        "mistake_id": mistake_id,
        "knowledge_point": kp_name,
        "analysis": analysis,
        "explanation": explanation,
        "common_mistakes": common_mistakes,
        "variant_exercise": variant,
    }
