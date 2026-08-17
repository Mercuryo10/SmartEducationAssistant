"""MySQL 连接与会话（docs/03 §2）。

- engine：pymysql 驱动，连接串来自 settings.DATABASE_URL。
- Base：所有 ORM 模型的声明基类。
- get_session：FastAPI 依赖，提供事务安全的 Session 上下文。
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=(settings.app_env == "dev"),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
Base = declarative_base()


def get_session() -> Generator[Session, None, None]:
    """FastAPI 依赖：每次请求一个 Session，结束时提交/关闭。

    Yields:
        数据库会话；异常时自动回滚。
    """
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
