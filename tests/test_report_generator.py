"""ReportGenerator tests — pure formatting, no LLM."""

from __future__ import annotations

import pytest

from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.report_generator import ReportGenerator
from comseba.submission_evaluator import CriterionFeedback


def _profile() -> StudentProfile:
    return StudentProfile(
        name="홍길동",
        career_goal="간호사가 되고 싶다",
        inferred_needs=["글쓰기 구조화", "사례 학습"],
        communication_style="조심스럽고 짧게 답함",
    )


def _criteria() -> list[Criterion]:
    return [
        Criterion("주제 적합성", "주제와 일치", 5),
        Criterion("표현력", "어휘 다양성", 5),
        Criterion("논리성", "주장-근거 연결", None),
    ]


def _evaluation(*, all_met: bool = False) -> list[CriterionFeedback]:
    return [
        CriterionFeedback("주제 적합성", "주제 잘 잡았음", met=True),
        CriterionFeedback(
            "표현력", "어휘 다양성 보완 필요", met=True if all_met else False
        ),
        CriterionFeedback("논리성", "근거 추가 필요", met=True if all_met else False),
    ]


def test_report_includes_all_five_section_headings() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="[AI 생성 예시 답안]\n본문"
    )

    assert "# 수행평가 보고서 — 홍길동" in report
    assert "## 학생 진로 요약" in report
    assert "## 평가 기준" in report
    assert "## 제출물 평가" in report
    assert "## 예시 답안" in report
    assert "## 개선 권고" in report


def test_report_career_section_contains_profile_fields() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )

    assert "간호사가 되고 싶다" in report
    assert "글쓰기 구조화, 사례 학습" in report
    assert "조심스럽고 짧게 답함" in report


def _section_after(report: str, heading: str) -> str:
    """Extract the content of a `## heading` section.

    Splits on `\\n## ` (with leading newline) so that `### sub-headings` —
    which contain the substring `## ` — don't accidentally split the section.
    """
    after = report.split(f"## {heading}", 1)[1]
    return after.split("\n## ", 1)[0]


def test_report_criteria_table_has_one_row_per_criterion() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )
    section = _section_after(report, "평가 기준")

    rows = [line for line in section.splitlines() if line.startswith("|")]
    assert len(rows) == 1 + 1 + 3  # header + separator + 3 criteria


def test_report_max_score_dash_when_none() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )
    table_section = _section_after(report, "평가 기준")

    logic_row = next(line for line in table_section.splitlines() if "논리성" in line)
    assert logic_row.endswith("| - |")


def test_report_evaluation_section_has_check_and_cross_marks() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )
    eval_section = _section_after(report, "제출물 평가")

    assert "✅" in eval_section
    assert "❌" in eval_section


def test_report_includes_model_answer_body() -> None:
    answer = "[AI 생성 예시 답안]\n\n첫 문단입니다.\n\n둘째 문단입니다."
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer=answer
    )

    assert answer in report


def test_report_recommendations_lists_only_unmet_criteria() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )
    rec_section = report.split("## 개선 권고")[1]

    assert "표현력" in rec_section
    assert "논리성" in rec_section
    assert "주제 적합성" not in rec_section  # met=True 라 제외


def test_report_recommendations_for_all_met_says_advance() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(all_met=True), model_answer="x"
    )

    rec = report.split("## 개선 권고")[1]
    assert "심화 활동" in rec


def test_report_escapes_pipe_in_description() -> None:
    criteria = [Criterion("a", "설명 | with | pipes", 1)]
    evaluation = [CriterionFeedback("a", "f", met=True)]

    report = ReportGenerator().generate(_profile(), criteria, evaluation, model_answer="x")

    assert "설명 \\| with \\| pipes" in report


def test_report_raises_on_empty_criteria_or_evaluation() -> None:
    gen = ReportGenerator()
    with pytest.raises(ValueError):
        gen.generate(_profile(), criteria=[], evaluation=_evaluation(), model_answer="x")
    with pytest.raises(ValueError):
        gen.generate(_profile(), _criteria(), evaluation=[], model_answer="x")


def test_report_ends_with_single_trailing_newline() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )

    assert report.endswith("\n")
    assert not report.endswith("\n\n")


def test_report_includes_profile_updated_at_when_provided() -> None:
    report = ReportGenerator().generate(
        _profile(),
        _criteria(),
        _evaluation(),
        model_answer="x",
        profile_updated_at="2026-05-10T14:30:00",
    )

    assert "**프로필 갱신**: 2026-05-10T14:30:00" in report


def test_report_omits_profile_updated_at_when_not_provided() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )

    assert "프로필 갱신" not in report
