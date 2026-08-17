"""构建知识库：读取 scripts/demo_data/ 文档 → 切分 → 嵌入 → 写入向量库（docs/09 阶段二）。

幂等：重复运行不产生重复分块 —— 对已登记文档先删除旧分块再重建；
生产迁移到 Milvus 后需重跑本脚本（docs/09 §8：索引写入 Milvus）。
用法：python scripts/build_kb.py
"""
import sys
from pathlib import Path

# 使 `app` 包可导入（以项目根为运行目录）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.services.rag_service import get_rag_service  # noqa: E402
from app.storage.db import SessionLocal  # noqa: E402
from app.storage.repositories import KnowledgeRepository  # noqa: E402

logger = get_logger("build_kb")

DEMO_DIR = Path(__file__).resolve().parent / "demo_data"


def load_demo_docs() -> list[dict]:
    """读取 demo_data 下全部 .md 文档。

    Returns:
        每项 {title, source, content}；title 取首个一级标题，否则用文件名。
    """
    docs: list[dict] = []
    for path in sorted(DEMO_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title = content.splitlines()[0].lstrip("#").strip() if content.splitlines() else path.stem
        docs.append({"title": title, "source": f"demo_data/{path.name}", "content": content})
    return docs


def main() -> None:
    """执行知识库构建（幂等）。"""
    setup_logging()
    logger.info("开始构建知识库 ...")
    rag = get_rag_service()
    docs = load_demo_docs()
    with SessionLocal() as session:
        repo = KnowledgeRepository(session)
        existing = {d.source: d for d in repo.list_docs()}
        total_chunks = 0
        for doc in docs:
            source = doc["source"]
            old = existing.get(source)
            if old:
                rag.delete_document(old.id)
                logger.info("重建文档：%s（id=%s）", doc["title"], old.id)
            else:
                old = repo.create_doc(title=doc["title"], source=source, content=doc["content"])
                logger.info("新增文档：%s（id=%s）", doc["title"], old.id)
            n = rag.add_document(old.id, doc["title"], source, doc["content"])
            repo.update_doc_chunk_count(old.id, n)
            total_chunks += n
        session.commit()
    logger.info("知识库构建完成：%d 篇文档，%d 个分块（向量库共 %d）", len(docs), total_chunks, rag.store.count())


if __name__ == "__main__":
    main()
