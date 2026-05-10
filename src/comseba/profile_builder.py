"""StudentProfileBuilder — career text + KakaoTalk → profile (stub)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StudentProfile:
    name: str
    career_goal: str
    inferred_needs: list[str] = field(default_factory=list)
    communication_style: str | None = None


class StudentProfileBuilder:
    def build(
        self,
        name: str,
        career_text: str,
        kakao_image_paths: list[Path] | None = None,
    ) -> StudentProfile:
        raise NotImplementedError("Implemented in COM-9")
