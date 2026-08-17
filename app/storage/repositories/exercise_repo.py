"""练习题仓储（docs/03 §7，覆盖 exercises + generated_exercises）。"""
from app.storage.models import Exercise, GeneratedExercise
from app.storage.repositories.base import BaseRepository


class ExerciseRepository(BaseRepository):
    """练习题模板与生成记录的数据访问。"""

    model = Exercise

    def create_exercise(
        self,
        knowledge_point_id: int,
        question_type: str,
        difficulty: str,
        template: str,
        answer_template: str,
        params_schema: dict | None = None,
    ) -> Exercise:
        """登记一条练习题模板。"""
        return self.create(
            knowledge_point_id=knowledge_point_id,
            question_type=question_type,
            difficulty=difficulty,
            template=template,
            answer_template=answer_template,
            params_schema=params_schema,
        )

    def list_by_knowledge_point(self, knowledge_point_id: int, question_type: str | None = None) -> list[Exercise]:
        """按知识点取模板，可选按题型过滤。"""
        return self.list_all(knowledge_point_id=knowledge_point_id, question_type=question_type)

    def create_generated(
        self,
        user_id: int,
        knowledge_point_id: int,
        question_text: str,
        answer: str,
        explanation: str,
        difficulty: str,
        exercise_id: int | None = None,
    ) -> GeneratedExercise:
        """保存一次实际生成下发的题目。"""
        gen = GeneratedExercise(
            user_id=user_id,
            exercise_id=exercise_id,
            knowledge_point_id=knowledge_point_id,
            question_text=question_text,
            answer=answer,
            explanation=explanation,
            difficulty=difficulty,
        )
        self.session.add(gen)
        self.session.flush()
        return gen

    def list_generated_by_user(self, user_id: int) -> list[GeneratedExercise]:
        """列出某用户的历史生成题目。"""
        return self.list_all(user_id=user_id, order_by="-created_at")
