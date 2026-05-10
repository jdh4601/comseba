"""SubmissionEvaluator — submission → per-criterion feedback (stub)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from comseba.criteria_extractor import Criterion


@dataclass
class CriterionFeedback:
    criterion: str
    feedback: str
    met: bool


class SubmissionEvaluator:
    def evaluate(
        self,
        criteria: list[Criterion],
        submission_text: str | None = None,
        submission_image_paths: list[Path] | None = None,
    ) -> list[CriterionFeedback]:
        raise NotImplementedError("Implemented in COM-11")
