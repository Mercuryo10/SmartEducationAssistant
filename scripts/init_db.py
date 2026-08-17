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
from app.storage.db import Base, SessionLocal, engine  # noqa: E402
from app.storage.repositories import KnowledgeRepository, UserRepository  # noqa: E402

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


def main() -> None:
    """执行初始化。"""
    setup_logging()
    logger.info("开始初始化数据库 ...")
    Base.metadata.create_all(bind=engine)
    logger.info("数据表已就绪（create_all 幂等，已存在表跳过）")
    with SessionLocal() as session:
        seed_knowledge_points(session)
        seed_demo_user(session)
        session.commit()
    logger.info("数据库初始化完成")


if __name__ == "__main__":
    main()
