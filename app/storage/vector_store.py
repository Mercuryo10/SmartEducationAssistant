"""向量库后端抽象与工厂（docs/03 §5）。

- VectorStore 接口：add/search/delete_by_doc/rebuild/count。
- FaissVectorStore：开发期（VECTOR_BACKEND=faiss），IndexFlatIP + L2 归一化 ≈ 余弦。
- MilvusVectorStore：生产期（VECTOR_BACKEND=milvus），阶段七实现完整功能。
- get_vector_store()：按配置返回实现，业务层只依赖接口。
"""
import pickle
from pathlib import Path
from typing import Any, Protocol

from app.core.config import settings
from app.core.exceptions import ToolExecutionError


class VectorStore(Protocol):
    """向量库抽象：业务层只依赖本接口，禁止直接 import faiss/pymilvus。"""

    def add(self, chunks: list[dict]) -> None:
        """写入分块。chunk: {doc_id, title, source, chunk_index, text, vector}。"""
        ...

    def search(self, vector: list[float], top_k: int = 5) -> list[dict]:
        """按向量检索，返回 [{text, source, doc_id, title, chunk_index, score}]。"""
        ...

    def delete_by_doc(self, doc_id: int) -> None:
        """删除某文档的全部分块。"""
        ...

    def rebuild(self) -> None:
        """重建索引（全量 KB 重建见 scripts/build_kb.py）。"""
        ...

    def count(self) -> int:
        """当前索引分块总数。"""
        ...


class FaissVectorStore:
    """FAISS 向量库（开发期后端，docs/03 §5.2）。

    存储：{index_dir}/index.faiss（向量）+ index.pkl（docstore 元数据与原始向量）。
    检索：IndexFlatIP 内积，向量 L2 归一化后等价余弦相似度。
    """

    def __init__(self, index_dir: str | None = None, dim: int | None = None) -> None:
        import faiss
        import numpy as np

        self._faiss = faiss
        self._np = np
        self.index_dir = Path(index_dir or settings.vector_index_dir)
        self.dim = dim or settings.vector_dim
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.index_dir / "index.faiss"
        self._docs_path = self.index_dir / "index.pkl"
        self._index: Any = None
        self._docs: list[dict] = []  # FAISS 序号 -> 元数据（含原始向量，便于重建/删除）
        self._load()

    # ---------- 内部工具 ----------

    def _load(self) -> None:
        if self._index_path.exists() and self._docs_path.exists():
            self._index = self._faiss.read_index(str(self._index_path))
            with self._docs_path.open("rb") as f:
                self._docs = pickle.load(f)
        else:
            self._index = self._faiss.IndexFlatIP(self.dim)
            self._save()

    def _save(self) -> None:
        self._faiss.write_index(self._index, str(self._index_path))
        with self._docs_path.open("wb") as f:
            pickle.dump(self._docs, f)

    def _rebuild_index_from_docs(self) -> None:
        """按当前 _docs 中的原始向量重建 FAISS 索引（删除文档后调用）。"""
        self._index = self._faiss.IndexFlatIP(self.dim)
        if self._docs:
            xb = self._np.vstack(
                [self._np.asarray(d["vector"], dtype="float32") for d in self._docs]
            )
            self._faiss.normalize_L2(xb)
            self._index.add(xb)
        self._save()

    # ---------- 接口实现 ----------

    def add(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        xb = self._np.vstack(
            [self._np.asarray(c["vector"], dtype="float32").reshape(1, -1) for c in chunks]
        )
        self._faiss.normalize_L2(xb)
        self._index.add(xb)
        for c in chunks:
            self._docs.append(
                {
                    "doc_id": c["doc_id"],
                    "title": c.get("title", ""),
                    "source": c.get("source", ""),
                    "chunk_index": c.get("chunk_index", 0),
                    "text": c.get("text", ""),
                    "vector": list(c["vector"]),
                }
            )
        self._save()

    def search(self, vector: list[float], top_k: int = 5) -> list[dict]:
        if self._index.ntotal == 0:
            return []
        xq = self._np.asarray(vector, dtype="float32").reshape(1, -1)
        self._faiss.normalize_L2(xq)
        scores, idxs = self._index.search(xq, min(top_k, self._index.ntotal))
        results: list[dict] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or idx >= len(self._docs):
                continue
            d = self._docs[idx]
            results.append(
                {
                    "text": d["text"],
                    "source": d["source"],
                    "doc_id": d["doc_id"],
                    "title": d["title"],
                    "chunk_index": d["chunk_index"],
                    "score": float(score),
                }
            )
        return results

    def delete_by_doc(self, doc_id: int) -> None:
        self._docs = [d for d in self._docs if d["doc_id"] != doc_id]
        self._rebuild_index_from_docs()

    def rebuild(self) -> None:
        self._rebuild_index_from_docs()

    def count(self) -> int:
        return len(self._docs)

    def __repr__(self) -> str:
        return f"FaissVectorStore(dir={self.index_dir}, chunks={len(self._docs)})"


class MilvusVectorStore:
    """Milvus 向量库（生产期后端）。

    完整功能在阶段七实现（docs/09 §7）；当前占位，防止后端误选导致静默错误。
    """

    def __init__(self) -> None:
        raise ToolExecutionError(
            "Milvus 后端将在阶段七实现；开发期请使用 VECTOR_BACKEND=faiss"
        )


def get_vector_store() -> VectorStore:
    """按 VECTOR_BACKEND 返回向量库实现（默认 faiss）。"""
    if settings.vector_backend == "milvus":
        return MilvusVectorStore()
    return FaissVectorStore()
