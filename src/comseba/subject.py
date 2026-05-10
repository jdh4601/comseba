"""Subject — 과목 컨텍스트 데이터 객체 + 사전 정의 프리셋.

평가 기준의 표현 / 항목 / 채점 관행은 과목별로 다르므로, 모든 LLM 호출의
system prompt 에 과목 정보를 주입해 편향을 줄인다. 사용자는 7개 프리셋 중
하나를 고르거나 "직접 입력" 으로 자유 텍스트 (음악 / 체육 / 통합사회 등) 를
지정할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 사용자에게 보여줄 순서 그대로. 직접 입력은 별도 처리.
SUBJECT_PRESETS: tuple[str, ...] = (
    "국어",
    "영어",
    "수학",
    "과학",
    "역사",
    "진로",
    "독서",
)


@dataclass(frozen=True)
class Subject:
    """Subject context for downstream LLM calls."""

    name: str
    is_custom: bool = False

    @classmethod
    def preset(cls, name: str) -> "Subject":
        if name not in SUBJECT_PRESETS:
            raise ValueError(
                f"알 수 없는 프리셋 과목: {name!r} "
                f"(가능: {', '.join(SUBJECT_PRESETS)})"
            )
        return cls(name=name, is_custom=False)

    @classmethod
    def custom(cls, name: str) -> "Subject":
        cleaned = (name or "").strip()
        if not cleaned:
            raise ValueError("과목명이 비어 있습니다.")
        return cls(name=cleaned, is_custom=True)

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "is_custom": self.is_custom}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Subject":
        return cls(name=str(data["name"]), is_custom=bool(data.get("is_custom", False)))


def format_subject_block(subject: Subject | None) -> str:
    """Build the `[과목] {name}` system-prompt fragment, or empty string if None.

    All five LLM modules call this so the injected wording is identical
    across the pipeline — change once, applies everywhere.
    """
    if subject is None:
        return ""
    return f"\n\n[과목]\n{subject.name}"
