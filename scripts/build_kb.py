"""构建知识库：读取 scripts/demo_data/ 文档 → 分块 → 嵌入 → 写入向量库（docs/09 阶段二）。

- **支持格式**：md / txt / html / docx（pdf 暂不支持，见 doc_splitter）。
- **分块策略**（docs/09 阶段 7.1）：
  * `--strategy char`（默认）：按字符切分（rag_service.split_text），与旧知识库一致，不改变现有行为。
  * `--strategy heading`：标题感知分块（doc_splitter），块不跨标题、块首拼接标题路径。
  两者可分别重建索引，供评估脚本（docs/10）对比 Recall@K 与溯源正确率。

- 幂等：重复运行不产生重复分块 —— 对已登记文档先删除旧分块再重建。
- 生产迁移到 Milvus 后需重跑本脚本（docs/09 §8：索引写入 Milvus）。

用法：python scripts/build_kb.py [--strategy char|heading]
"""
import argparse
import sys
from pathlib import Path

# 使 `app` 包可导入（以项目根为运行目录）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.services.doc_splitter import extract_title_file, extract_plain_text, split_document_file  # noqa: E402
from app.services.rag_service import get_rag_service  # noqa: E402
from app.storage.db import SessionLocal  # noqa: E402
from app.storage.repositories import KnowledgeRepository  # noqa: E402

logger = get_logger("build_kb")

DEMO_DIR = Path(__file__).resolve().parent / "demo_data"
SUPPORTED_SUFFIXES = (".md", ".txt", ".html", ".htm", ".docx")


def load_demo_docs() -> list[dict]:
    """读取 demo_data 下全部支持格式的文档。

    Returns:
        每项 {title, source, content, path}；title 优先取文档结构标题，否则文件名。
    """
    docs: list[dict] = []
    for path in sorted(DEMO_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            title = extract_title_file(path) or path.stem
            docs.append(
                {
                    "title": title,
                    "source": f"demo_data/{path.name}",
                    "content": extract_plain_text(path),
                    "path": path,
                }
            )
    return docs


def main() -> None:
    """执行知识库构建（幂等）；--strategy 选择分块策略。"""
    parser = argparse.ArgumentParser(description="构建 EduMentor 知识库（幂等，可重复运行）")
    parser.add_argument(
        "--strategy",
        choices=("char", "heading"),
        default="char",
        help="分块策略：char=按字符切分（默认，与旧知识库一致）；heading=标题感知分块（阶段 7.1）",
    )
    args = parser.parse_args()

    setup_logging()
    logger.info("开始构建知识库（strategy=%s）...", args.strategy)
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
            if args.strategy == "heading":
                n = rag.add_chunks(old.id, doc["title"], source, split_document_file(doc["path"]))
            else:
                n = rag.add_document(old.id, doc["title"], source, doc["content"])
            repo.update_doc_chunk_count(old.id, n)
            total_chunks += n
        session.commit()
    logger.info(
        "知识库构建完成：%d 篇文档，%d 个分块（向量库共 %d）",
        len(docs),
        total_chunks,
        rag.store.count(),
    )


if __name__ == "__main__":
    main()
