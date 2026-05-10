"""AssessmentSuggestionEngine — profile + rubric → activity ideas (stub)."""

from __future__ import annotations

from dataclasses import dataclass

from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile


@dataclass
class AssessmentIdea:
    title: str
    description: str
    rationale: str


class AssessmentSuggestionEngine:
    def suggest(
        self,
        profile: StudentProfile,
        criteria: list[Criterion],
        count: int = 4,
    ) -> list[AssessmentIdea]:
        raise NotImplementedError("Implemented in COM-10")
