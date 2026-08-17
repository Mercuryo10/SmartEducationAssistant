"""作业批改仓储（docs/03 §7，覆盖 homework_submissions + grading_results）。"""
from sqlalchemy import select

from app.storage.models import GradingResult, HomeworkSubmission
from app.storage.repositories.base import BaseRepository


class HomeworkRepository(BaseRepository):
    """作业提交与批改结果数据访问。"""

    model = HomeworkSubmission

    def create_submission(
        self, user_id: int, image_paths: list[str], answer_key: str | None = None
    ) -> HomeworkSubmission:
        """创建提交记录（初始状态 pending）。"""
        return self.create(
            user_id=user_id, image_paths=image_paths, answer_key=answer_key, status="pending"
        )

    def get_submission(self, submission_id: int) -> HomeworkSubmission | None:
        """按 id 取提交记录。"""
        return self.get_by_id(submission_id)

    def update_submission_status(self, submission_id: int, status: str, ocr_text: str | None = None) -> HomeworkSubmission:
        """更新提交状态（pending/grading/done/failed），可选回填 OCR 文本。"""
        submission = self.get_by_id(submission_id)
        if submission is None:
            raise ValueError(f"homework_submissions 不存在 id={submission_id}")
        fields = {"status": status}
        if ocr_text is not None:
            fields["ocr_text"] = ocr_text
        return self.update(submission, **fields)

    def create_grading_result(self, submission_id: int, **fields) -> GradingResult:
        """写入一条批改明细（question_no/question_type/score 等）并 flush。"""
        result = GradingResult(submission_id=submission_id, **fields)
        self.session.add(result)
        self.session.flush()
        return result

    def list_grading_results_by_submission(self, submission_id: int) -> list[GradingResult]:
        """列出某提交的全部批改明细（按题号升序）。"""
        stmt = (
            select(GradingResult)
            .where(GradingResult.submission_id == submission_id)
            .order_by(GradingResult.question_no.asc())
        )
        return list(self.session.scalars(stmt))
