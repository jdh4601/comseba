"""SchoolLevel — 학교급 (중등 / 고등) 컨텍스트.

같은 평가 항목이라도 중학생과 고등학생에게 기대하는 분량 / 어휘 / 분석 깊이가
다르다. 모든 LLM 호출의 system prompt 에 학교급을 주입해 모범 답안 / 평가 톤이
대상 학생 수준에 맞도록 한다. 정확히 2값만 — 더 세분화는 본 모듈 범위 밖.
"""

from __future__ import annotations

from enum import Enum


class SchoolLevel(str, Enum):
    """Two-level enum used as system-prompt context across all LLM modules."""

    MIDDLE = "middle"  # 중등
    HIGH = "high"      # 고등

    @property
    def label_ko(self) -> str:
        return _LABELS_KO[self]

    @property
    def short_ko(self) -> str:
        return _SHORT_KO[self]


_LABELS_KO: dict[SchoolLevel, str] = {
    SchoolLevel.MIDDLE: "중등 (중학생)",
    SchoolLevel.HIGH: "고등 (고등학생)",
}

_SHORT_KO: dict[SchoolLevel, str] = {
    SchoolLevel.MIDDLE: "중등",
    SchoolLevel.HIGH: "고등",
}


def format_level_block(level: SchoolLevel | None) -> str:
    """Build the `[학교급] {label}` system-prompt fragment, or empty if None.

    All six modules call this so the wording is identical across the pipeline.
    """
    if level is None:
        return ""
    return f"\n\n[학교급]\n{level.label_ko}"
