"""向量检索单测（docs/08 §10：retrieve 命中率）。

用临时目录构建独立 FAISS 索引（16 维随机向量，避开真实 1024 维知识库），
验证「同向量检索 Top-1 命中、Top-5 召回」；并断言默认工厂返回 Faiss 实现。
不依赖 DB / Embedding API，可离线运行。
"""
import tempfile

import numpy as np

from app.core.config import settings
from app.storage.vector_store import FaissVectorStore, get_vector_store


def _vector(seed: int, dim: int = 16) -> list[float]:
    """按种子生成确定性随机向量。"""
    rng = np.random.default_rng(seed)
    return rng.uniform(-1, 1, size=dim).tolist()


def _make_store() -> FaissVectorStore:
    """构建临时 16 维 FAISS 索引并写入 10 个分块。"""
    store = FaissVectorStore(index_dir=tempfile.mkdtemp(), dim=16)
    chunks = [
        {
            "doc_id": i,
            "title": f"doc{i}",
            "source": f"src{i}.md",
            "chunk_index": 0,
            "text": f"文档{i}的分块文本",
            "vector": _vector(i),
        }
        for i in range(10)
    ]
    store.add(chunks)
    return store


def test_top1_exact_hit() -> None:
    store = _make_store()
    top = store.search(store._docs[3]["vector"], top_k=3)
    assert top[0]["doc_id"] == 3, "同向量检索 Top-1 应精确命中原文档"
    assert top[0]["score"] > 0.9, "归一化后同向量余弦应接近 1.0"
    assert top[0]["source"] == "src3.md"


def test_recall_within_top5() -> None:
    store = _make_store()
    top5 = store.search(store._docs[7]["vector"], top_k=5)
    assert any(r["doc_id"] == 7 for r in top5), "Top-5 内应召回精确命中"


def test_empty_index_returns_empty() -> None:
    store = FaissVectorStore(index_dir=tempfile.mkdtemp(), dim=16)
    assert store.count() == 0
    assert store.search(_vector(0)) == []


def test_delete_by_doc_removes_chunks() -> None:
    store = _make_store()
    store.delete_by_doc(1)
    assert store.count() == 9
    assert all(r["doc_id"] != 1 for r in store.search(store._docs[0]["vector"], top_k=10))


def test_get_vector_store_default_is_faiss() -> None:
    # 开发期默认 VECTOR_BACKEND=faiss，工厂必须仍返回 Faiss 实现（docs/09 §7 验收）
    if settings.vector_backend == "faiss":
        assert isinstance(get_vector_store(), FaissVectorStore)
