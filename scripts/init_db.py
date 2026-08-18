"""初始化数据库：建表 + 内置知识点 + 演示账号（docs/03 §8，幂等）。

前置条件：MySQL 库 `edumentor` 与用户 `edumentor` 已创建（见 docs/07 §3）。
用法：python scripts/init_db.py
"""
import sys
from pathlib import Path

# 使 `app` 包可导入（以项目根为运行目录）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.services import exercise_data  # noqa: E402
from app.storage.db import Base, SessionLocal, engine  # noqa: E402
from app.storage.repositories import ExerciseRepository, KnowledgeRepository, UserRepository  # noqa: E402

logger = get_logger("init_db")

# 内置知识点（大模型/Agent 领域，阶段二起被答疑/错题/出题引用）
SEED_KNOWLEDGE_POINTS = [
    {
        "name": "Transformer 与注意力机制",
        "subject": "ai",
        "description": "自注意力机制、Q/K/V、多头注意力与位置编码。",
    },
    {
        "name": "检索增强生成（RAG）",
        "subject": "ai",
        "description": "Retrieval-Augmented Generation：检索 + 生成约束幻觉。",
    },
    {
        "name": "多 Agent 编排（LangGraph）",
        "subject": "ai",
        "description": "LangGraph StateGraph、Supervisor 模式与子图编排。",
    },
    {
        "name": "向量检索与语义嵌入",
        "subject": "ai",
        "description": "Embedding 表示、余弦相似度、向量数据库与召回。",
    },
    {
        "name": "提示词工程",
        "subject": "ai",
        "description": "提示设计、few-shot、思维链与结构化输出。",
    },
]

# 演示账号
DEMO_USER = {"username": "demo", "password": "demo123", "nickname": "演示用户", "role": "student"}


def seed_knowledge_points(session: Session) -> None:
    """幂等写入内置知识点（按名称查重）。"""
    repo = KnowledgeRepository(session)
    for kp in SEED_KNOWLEDGE_POINTS:
        if repo.get_knowledge_point_by_name(kp["name"]):
            continue
        repo.create_knowledge_point(**kp)
        logger.info("内置知识点：%s", kp["name"])


def seed_demo_user(session: Session) -> None:
    """幂等创建演示账号 demo / demo123。"""
    repo = UserRepository(session)
    if repo.get_by_username(DEMO_USER["username"]):
        return
    repo.create_user(
        username=DEMO_USER["username"],
        password_hash=hash_password(DEMO_USER["password"]),
        nickname=DEMO_USER["nickname"],
        role=DEMO_USER["role"],
    )
    logger.info("演示账号：%s / %s", DEMO_USER["username"], DEMO_USER["password"])


def seed_exercise_templates(session: Session) -> None:
    """幂等写入练习模板（docs/09 阶段五「模板数据」，≥3 题型 × ≥5 知识点 × 3 难度）。

    数据源为 app/services/exercise_data.py（标准陈述库 + 题干/答案模板）；
    写入 exercises 表，生成时从 params_schema.facts 读取事实库。
    """
    ex_repo = ExerciseRepository(session)
    kp_repo = KnowledgeRepository(session)
    for kp_name, facts in exercise_data.FACT_LIBRARIES.items():
        kp = kp_repo.get_knowledge_point_by_name(kp_name)
        if kp is None:
            logger.warning("知识点不存在，跳过练习模板：%s", kp_name)
            continue
        for qtype in exercise_data.QUESTION_TYPES:
            for difficulty in exercise_data.DIFFICULTIES:
                if ex_repo.list_by_knowledge_point(kp.id, qtype, difficulty):
                    continue  # 幂等：已存在跳过
                ex_repo.create_exercise(
                    knowledge_point_id=kp.id,
                    question_type=qtype,
                    difficulty=difficulty,
                    template=exercise_data.STEM_TEMPLATES[qtype][difficulty],
                    answer_template=exercise_data.ANSWER_TEMPLATES[qtype],
                    params_schema={"facts": facts},
                )
                logger.info("练习模板：%s %s/%s", kp_name, qtype, difficulty)


def main() -> None:
    """执行初始化。"""
    setup_logging()
    logger.info("开始初始化数据库 ...")
    Base.metadata.create_all(bind=engine)
    logger.info("数据表已就绪（create_all 幂等，已存在表跳过）")
    with SessionLocal() as session:
        seed_knowledge_points(session)
        seed_demo_user(session)
        seed_exercise_templates(session)
        session.commit()
    logger.info("数据库初始化完成")


if __name__ == "__main__":
    main()
