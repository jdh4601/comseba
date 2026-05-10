"""EvaluationCriteriaExtractor — rubric image → JSON criteria (stub)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Criterion:
    name: str
    description: str
    max_score: int | None = None


class EvaluationCriteriaExtractor:
    def extract(self, image_paths: list[Path]) -> list[Criterion]:
        raise NotImplementedError("Implemented in COM-8")
