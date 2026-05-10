"""Acceptance-criteria tests required by COM-16.

PRD §Testing Decisions 가 4개 핵심 모듈에 대해 명시한 시나리오를 conftest 의
공통 fixture 로 단일 출처에서 검증한다. 함수명은 `test_{action}_{condition}_{expected_result}`
규약을 따른다. 기존 모듈별 단위 테스트는 더 세밀한 분기를 커버하고, 이 파일은
PRD 가 약속한 외부 계약을 한 곳에서 명시적으로 점검한다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

from comseba.criteria_extractor import (
    Criterion,
    EvaluationCriteriaExtractor,
)
from comseba.profile_builder import StudentProfile
from comseba.report_generator import ReportGenerator
from comseba.sms_generator import SmsContentGenerator
from comseba.submission_evaluator import (
    CriterionFeedback,
    SubmissionEvaluator,
)


# ---------------------------------------------------------------------------
# EvaluationCriteriaExtractor (COM-8)
# ---------------------------------------------------------------------------


def test_extract_known_rubric_text_returns_expected_criterion_names(
    tmp_path: Path,
    criteria: list[Criterion],
    criteria_json_reply: str,
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "주제 적합성 / 표현력 / 논리성 — 각 항목 설명"
    rubric_image = tmp_path / "rubric.png"
    rubric_image.write_bytes(b"x")
    extractor = EvaluationCriteriaExtractor(
        client=mock_anthropic_client(criteria_json_reply),
        image_parser=image_parser,
    )

    result = extractor.extract([rubric_image])

    assert [c.name for c in result] == [c.name for c in criteria]


def test_extract_returns_well_formed_criteria_with_required_fields(
    tmp_path: Path,
    criteria_json_reply: str,
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR 텍스트"
    rubric_image = tmp_path / "rubric.png"
    rubric_image.write_bytes(b"x")
    extractor = EvaluationCriteriaExtractor(
        client=mock_anthropic_client(criteria_json_reply),
        image_parser=image_parser,
    )

    result = extractor.extract([rubric_image])

    for c in result:
        assert isinstance(c.name, str) and c.name
        assert isinstance(c.description, str) and c.description


# ---------------------------------------------------------------------------
# SubmissionEvaluator (COM-11)
# ---------------------------------------------------------------------------


def test_evaluate_known_rubric_includes_every_criterion_in_result(
    criteria: list[Criterion],
    evaluation_json_reply: str,
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    evaluator = SubmissionEvaluator(client=mock_anthropic_client(evaluation_json_reply))

    result = evaluator.evaluate(criteria, submission_text="학생이 작성한 본문입니다.")

    assert {f.criterion for f in result} == {c.name for c in criteria}


def test_evaluate_returns_feedback_with_required_string_and_boolean_fields(
    criteria: list[Criterion],
    evaluation_json_reply: str,
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    evaluator = SubmissionEvaluator(client=mock_anthropic_client(evaluation_json_reply))

    result = evaluator.evaluate(criteria, submission_text="본문")

    for f in result:
        assert isinstance(f.feedback, str) and f.feedback
        assert isinstance(f.met, bool)


# ---------------------------------------------------------------------------
# ReportGenerator (COM-14)
# ---------------------------------------------------------------------------


def test_generate_report_contains_all_five_required_section_headings(
    student_profile: StudentProfile,
    criteria: list[Criterion],
    evaluation: list[CriterionFeedback],
) -> None:
    report = ReportGenerator().generate(
        student_profile, criteria, evaluation, model_answer="[AI 생성 예시 답안]\n본문"
    )

    for heading in (
        "## 학생 진로 요약",
        "## 평가 기준",
        "## 제출물 평가",
        "## 예시 답안",
        "## 개선 권고",
    ):
        assert heading in report, f"누락된 섹션: {heading}"


def test_generate_report_includes_student_name_in_document_title(
    student_profile: StudentProfile,
    criteria: list[Criterion],
    evaluation: list[CriterionFeedback],
) -> None:
    report = ReportGenerator().generate(
        student_profile, criteria, evaluation, model_answer="x"
    )

    title_line = report.splitlines()[0]
    assert title_line.startswith("# ")
    assert student_profile.name in title_line


# ---------------------------------------------------------------------------
# SmsContentGenerator (COM-13)
# ---------------------------------------------------------------------------


def _sms_payload() -> str:
    import json as _json

    return _json.dumps(
        {
            "summary": "오늘 학생이 적극적으로 참여했습니다.",
            "bullets": ["서론 흐름이 명확", "결론 보강이 더 필요"],
        },
        ensure_ascii=False,
    )


def test_generate_sms_includes_student_name_in_first_line(
    student_profile: StudentProfile,
    evaluation: list[CriterionFeedback],
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    sms = SmsContentGenerator(client=mock_anthropic_client(_sms_payload())).generate(
        student_profile, evaluation, assessment_name="환경 보고서"
    )

    first_line = sms.splitlines()[0]
    assert student_profile.name in first_line


def test_generate_sms_wraps_assessment_name_in_single_quotes(
    student_profile: StudentProfile,
    evaluation: list[CriterionFeedback],
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    sms = SmsContentGenerator(client=mock_anthropic_client(_sms_payload())).generate(
        student_profile, evaluation, assessment_name="과학 글쓰기"
    )

    assert "'과학 글쓰기'" in sms


def test_generate_sms_contains_at_least_one_arrow_bullet(
    student_profile: StudentProfile,
    evaluation: list[CriterionFeedback],
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    sms = SmsContentGenerator(client=mock_anthropic_client(_sms_payload())).generate(
        student_profile, evaluation, assessment_name="x"
    )

    bullet_lines = [line for line in sms.splitlines() if line.startswith("-> ")]
    assert len(bullet_lines) >= 1


def test_generate_sms_ends_with_required_closing_phrase(
    student_profile: StudentProfile,
    evaluation: list[CriterionFeedback],
    mock_anthropic_client: Callable[[str], MagicMock],
) -> None:
    sms = SmsContentGenerator(client=mock_anthropic_client(_sms_payload())).generate(
        student_profile, evaluation, assessment_name="x"
    )

    assert sms.rstrip().endswith(
        "생기부에 더 좋은 내용들이 담길 수 있도록 돕겠습니다 ! ^^"
    )
