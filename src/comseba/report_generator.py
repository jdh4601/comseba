"""ReportGenerator — assemble all session data into a fixed-layout Markdown report.

순수 포매팅 모듈 (LLM 호출 없음). 학생 프로필, 루브릭, 평가 결과, 예시 답안을
받아 PRD 가 정의한 5개 섹션 구조 그대로 마크다운을 만든다. LLM 추론은
업스트림 모듈들이 이미 끝낸 상태 — 여기서는 결정론적 조립만.

개선 권고는 evaluation 의 미충족 항목에서 직접 도출한다 (별도 LLM 호출 X).
"""

from __future__ import annotations

from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback


_MET_MARK = "✅"
_UNMET_MARK = "❌"


class ReportGenerator:
    def generate(
        self,
        profile: StudentProfile,
        criteria: list[Criterion],
        evaluation: list[CriterionFeedback],
        model_answer: str,
        profile_updated_at: str | None = None,
    ) -> str:
        if not criteria:
            raise ValueError("평가 기준이 비어 있습니다.")
        if not evaluation:
            raise ValueError("평가 결과가 비어 있습니다.")

        sections = [
            f"# 수행평가 보고서 — {profile.name}",
            _career_section(profile, profile_updated_at),
            _criteria_section(criteria),
            _evaluation_section(evaluation),
            _model_answer_section(model_answer),
            _recommendations_section(evaluation),
        ]
        return "\n\n".join(sections).rstrip() + "\n"


def _career_section(
    profile: StudentProfile, profile_updated_at: str | None = None
) -> str:
    lines = ["## 학생 진로 요약", "", f"- **이름**: {profile.name}", f"- **진로 / 목표**: {profile.career_goal}"]
    if profile.inferred_needs:
        needs = ", ".join(profile.inferred_needs)
        lines.append(f"- **파악된 니즈**: {needs}")
    if profile.communication_style:
        lines.append(f"- **소통 스타일**: {profile.communication_style}")
    if profile_updated_at:
        lines.append(f"- **프로필 갱신**: {profile_updated_at}")
    return "\n".join(lines)


def _criteria_section(criteria: list[Criterion]) -> str:
    header = "| 항목 | 설명 | 최고점 |\n|---|---|---|"
    rows = [
        f"| {c.name} | {_escape_pipe(c.description)} | "
        f"{c.max_score if c.max_score is not None else '-'} |"
        for c in criteria
    ]
    return "## 평가 기준\n\n" + header + "\n" + "\n".join(rows)


def _evaluation_section(evaluation: list[CriterionFeedback]) -> str:
    blocks = ["## 제출물 평가"]
    for fb in evaluation:
        mark = _MET_MARK if fb.met else _UNMET_MARK
        blocks.append(
            f"### {fb.criterion}\n\n- **충족 여부**: {mark}\n- **피드백**: {fb.feedback}"
        )
    return "\n\n".join(blocks)


def _model_answer_section(model_answer: str) -> str:
    body = model_answer.strip()
    if not body:
        body = "(생성된 예시 답안이 없습니다)"
    return f"## 예시 답안\n\n{body}"


def _recommendations_section(evaluation: list[CriterionFeedback]) -> str:
    unmet = [fb for fb in evaluation if not fb.met]
    if not unmet:
        return (
            "## 개선 권고\n\n"
            "모든 평가 기준을 충족했습니다. 다음 단계로 심화 활동을 권장합니다."
        )
    bullets = "\n".join(
        f"- **{fb.criterion}**: {fb.feedback}" for fb in unmet
    )
    return "## 개선 권고\n\n" + bullets


def _escape_pipe(s: str) -> str:
    """Markdown 표 셀 안에서 `|` 가 컬럼 구분자로 오인되지 않도록 escape."""
    return s.replace("|", "\\|").replace("\n", " ")
