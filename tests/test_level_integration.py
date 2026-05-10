"""Cross-module integration tests for SchoolLevel context plumbing.

Same shape as test_subject_integration.py — verifies all six modules expose a
`level` parameter that flows into the system prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.criteria_extractor import (
    Criterion,
    EvaluationCriteriaExtractor,
)
from comseba.level import SchoolLevel
from comseba.model_answer_generator import ModelAnswerGenerator
from comseba.profile_builder import StudentProfile, StudentProfileBuilder
from comseba.report_generator import ReportGenerator
from comseba.sms_generator import SmsContentGenerator
from comseba.submission_evaluator import (
    CriterionFeedback,
    SubmissionEvaluator,
)
from comseba.suggestion_engine import AssessmentSuggestionEngine


def _mock_client(reply: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply)],
        model="claude-sonnet-4-6",
    )
    return client


def _system(client: MagicMock) -> str:
    return client.messages.create.call_args.kwargs["system"]


def _criteria() -> list[Criterion]:
    return [Criterion("주제 적합성", "주제와 일치", 5)]


def _profile() -> StudentProfile:
    return StudentProfile(name="홍길동", career_goal="간호사")


def _evaluation() -> list[CriterionFeedback]:
    return [CriterionFeedback("주제 적합성", "잘함", met=True)]


# ---------------------------------------------------------------------------
# Each module: level injected → label appears under [학교급]
# ---------------------------------------------------------------------------


def test_profile_builder_includes_level_in_system_prompt() -> None:
    payload = json.dumps(
        {"inferred_needs": [], "communication_style": None}, ensure_ascii=False
    )
    client = _mock_client(payload)
    builder = StudentProfileBuilder(client=client)

    builder.build("홍길동", career_text="진로", level=SchoolLevel.HIGH)

    system = _system(client)
    assert "[학교급]" in system
    assert "고등학생" in system


def test_criteria_extractor_includes_level_in_system_prompt(
    tmp_path: Path,
) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR"
    rubric = tmp_path / "r.png"
    rubric.write_bytes(b"x")
    payload = json.dumps(
        {"criteria": [{"name": "x", "description": "y", "max_score": None}]},
        ensure_ascii=False,
    )
    client = _mock_client(payload)
    extractor = EvaluationCriteriaExtractor(client=client, image_parser=image_parser)

    extractor.extract([rubric], level=SchoolLevel.MIDDLE)

    assert "중학생" in _system(client)


def test_suggestion_engine_includes_level_in_system_prompt() -> None:
    payload = json.dumps(
        {
            "ideas": [
                {"title": f"제목{i}", "description": f"설명{i}", "rationale": f"근거{i}"}
                for i in range(4)
            ]
        },
        ensure_ascii=False,
    )
    client = _mock_client(payload)
    engine = AssessmentSuggestionEngine(client=client)

    engine.suggest(_profile(), _criteria(), level=SchoolLevel.HIGH)

    assert "고등학생" in _system(client)


def test_submission_evaluator_includes_level_in_system_prompt() -> None:
    payload = json.dumps(
        {"feedback": [{"criterion": "주제 적합성", "feedback": "f", "met": True}]},
        ensure_ascii=False,
    )
    client = _mock_client(payload)
    evaluator = SubmissionEvaluator(client=client)

    evaluator.evaluate(_criteria(), submission_text="본문", level=SchoolLevel.MIDDLE)

    assert "중학생" in _system(client)


def test_model_answer_generator_includes_level_in_system_prompt() -> None:
    client = _mock_client("답안")
    generator = ModelAnswerGenerator(client=client)

    generator.generate(_criteria(), _profile(), level=SchoolLevel.HIGH)

    assert "고등학생" in _system(client)


def test_sms_generator_includes_level_in_system_prompt() -> None:
    payload = json.dumps(
        {"summary": "요약", "bullets": ["b"]}, ensure_ascii=False
    )
    client = _mock_client(payload)
    generator = SmsContentGenerator(client=client)

    generator.generate(
        _profile(),
        _evaluation(),
        assessment_name="x",
        level=SchoolLevel.MIDDLE,
    )

    assert "중학생" in _system(client)


# ---------------------------------------------------------------------------
# level=None → no [학교급] header (regression guard)
# ---------------------------------------------------------------------------


def test_no_level_keeps_system_prompt_clean() -> None:
    payload = json.dumps(
        {"inferred_needs": [], "communication_style": None}, ensure_ascii=False
    )
    client = _mock_client(payload)
    StudentProfileBuilder(client=client).build("홍길동", career_text="진로")

    assert "[학교급]" not in _system(client)


# ---------------------------------------------------------------------------
# ReportGenerator: level row in 학생 진로 요약
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected_short",
    [(SchoolLevel.MIDDLE, "중등"), (SchoolLevel.HIGH, "고등")],
)
def test_report_includes_level_row_when_provided(
    level: SchoolLevel, expected_short: str
) -> None:
    report = ReportGenerator().generate(
        _profile(),
        _criteria(),
        _evaluation(),
        model_answer="x",
        level=level,
    )

    assert f"**학교급**: {expected_short}" in report


def test_report_omits_level_row_when_not_provided() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )

    assert "**학교급**" not in report
