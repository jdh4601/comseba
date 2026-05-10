"""ReportGenerator — all data → Markdown report (stub)."""

from __future__ import annotations

from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback


class ReportGenerator:
    def generate(
        self,
        profile: StudentProfile,
        criteria: list[Criterion],
        evaluation: list[CriterionFeedback],
        model_answer: str,
    ) -> str:
        raise NotImplementedError("Implemented in COM-14")
