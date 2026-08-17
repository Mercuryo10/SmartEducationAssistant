"""知识库文档与知识点仓储（docs/03 §7，覆盖 knowledge_docs + knowledge_points）。"""
from sqlalchemy import select

from app.storage.models import KnowledgeDoc, KnowledgePoint
from app.storage.repositories.base import BaseRepository


class KnowledgeRepository(BaseRepository):
    """知识库（文档 + 知识点）数据访问。"""

    model = KnowledgeDoc

    # ---------- 知识库文档 ----------

    def create_doc(self, title: str, source: str, content: str, chunk_count: int = 0) -> KnowledgeDoc:
        """登记一条知识库文档。"""
        return self.create(title=title, source=source, content=content, chunk_count=chunk_count)

    def get_doc(self, doc_id: int) -> KnowledgeDoc | None:
        """按 id 取文档。"""
        return self.get_by_id(doc_id)

    def list_docs(self) -> list[KnowledgeDoc]:
        """列出全部知识库文档。"""
        return list(self.session.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.id)))

    def update_doc_chunk_count(self, doc_id: int, chunk_count: int) -> KnowledgeDoc:
        """更新文档分块数。"""
        doc = self.get_by_id(doc_id)
        if doc is None:
            raise ValueError(f"knowledge_docs 不存在 id={doc_id}")
        return self.update(doc, chunk_count=chunk_count)

    # ---------- 知识点 ----------

    def create_knowledge_point(self, name: str, subject: str = "math", description: str | None = None) -> KnowledgePoint:
        """新建知识点并 flush（返回带主键对象）。"""
        kp = KnowledgePoint(name=name, subject=subject, description=description)
        self.session.add(kp)
        self.session.flush()
        return kp

    def get_knowledge_point(self, kp_id: int) -> KnowledgePoint | None:
        """按 id 取知识点。"""
        return self.session.get(KnowledgePoint, kp_id)

    def get_knowledge_point_by_name(self, name: str) -> KnowledgePoint | None:
        """按名称取知识点（唯一）。"""
        return self.session.query(KnowledgePoint).filter(KnowledgePoint.name == name).first()

    def list_knowledge_points(self) -> list[KnowledgePoint]:
        """列出全部知识点。"""
        return list(self.session.scalars(select(KnowledgePoint).order_by(KnowledgePoint.id)))
