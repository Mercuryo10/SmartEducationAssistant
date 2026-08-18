"""阶段 7.1 预览：标题感知分块 demo_data（md/txt/html/docx），输出 data/chunks_preview.json。

用法：python scripts/chunk_demo_data.py [目录]
  [目录] 可选，默认 scripts/demo_data/（可对 data/samples/ 等样例目录预览）。
产物：data/chunks_preview.json（{documents:[{source,title,fmt,chunks:[...]}], stats}）
仅供人工评估分块质量，不写入向量库；确认后再用 build_kb.py --strategy heading 接入。
"""
import argparse
import json
import sys
from pathlib import Path

# 使 `app` 包可导入（以项目根为运行目录）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.services.doc_splitter import extract_title_file, split_document_file_sections  # noqa: E402

logger = get_logger("chunk_demo_data")

DEFAULT_DIR = Path(__file__).resolve().parent / "demo_data"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "chunks_preview.json"
SUPPORTED_SUFFIXES = (".md", ".txt", ".html", ".htm", ".docx")


def main() -> None:
    """切分指定目录下全部支持格式的文档，写出预览 JSON（幂等，覆盖写）。"""
    parser = argparse.ArgumentParser(description="生成知识库分块预览 JSON")
    parser.add_argument("src_dir", nargs="?", default=str(DEFAULT_DIR), help="扫描目录（默认 scripts/demo_data）")
    args = parser.parse_args()

    setup_logging()
    src_dir = Path(args.src_dir)
    docs: list[dict] = []
    for path in sorted(src_dir.iterdir()):
        if not (path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES):
            continue
        title = extract_title_file(path) or path.stem
        chunks = [
            {
                "chunk_index": i,
                "heading_path": sec["heading_path"],
                "char_count": len(sec["text"]),
                "text": sec["text"],
            }
            for i, sec in enumerate(split_document_file_sections(path))
        ]
        docs.append(
            {
                "source": f"{src_dir.name}/{path.name}",
                "title": title,
                "fmt": path.suffix.lower().lstrip("."),
                "chunks": chunks,
            }
        )
        logger.info("切分 %s（%s）：%d 个分块", path.name, path.suffix, len(chunks))

    result = {
        "stats": {
            "src_dir": str(src_dir),
            "docs": len(docs),
            "total_chunks": sum(len(d["chunks"]) for d in docs),
            "per_doc": {d["title"]: len(d["chunks"]) for d in docs},
            "chunk_size": 500,  # 对应 settings.chunk_size
            "chunk_overlap": 50,
            "strategy": "heading",
        },
        "documents": docs,
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("分块预览已写出：%s（%d 篇 / %d 块）", OUT_PATH, result["stats"]["docs"], result["stats"]["total_chunks"])


if __name__ == "__main__":
    main()
