"""ModelAnswerGenerator — rubric + profile → model answer (stub)."""

from __future__ import annotations

from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback


class ModelAnswerGenerator:
    def generate(
        self,
        criteria: list[Criterion],
        profile: StudentProfile,
        evaluation: list[CriterionFeedback] | None = None,
    ) -> str:
        raise NotImplementedError("Implemented in COM-12")
