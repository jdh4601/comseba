"""SmsContentGenerator — evaluation + profile → parent SMS draft (stub)."""

from __future__ import annotations

from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback


class SmsContentGenerator:
    def generate(
        self,
        profile: StudentProfile,
        evaluation: list[CriterionFeedback],
        assessment_name: str,
    ) -> str:
        raise NotImplementedError("Implemented in COM-13")
