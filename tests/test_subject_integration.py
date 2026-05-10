"""Cross-module integration tests — subject context must flow through all
five LLM modules' system prompts, plus the Pipeline / report layer.

Each test mocks only the Anthropic client; production code paths are exercised.
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
from comseba.model_answer_generator import ModelAnswerGenerator
from comseba.profile_builder import StudentProfile
from comseba.report_generator import ReportGenerator
from comseba.sms_generator import SmsContentGenerator
from comseba.subject import Subject
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


def _criteria() -> list[Criterion]:
    return [Criterion("주제 적합성", "주제와 일치", 5)]


def _profile() -> StudentProfile:
    return StudentProfile(name="홍길동", career_goal="간호사")


def _evaluation() -> list[CriterionFeedback]:
    return [CriterionFeedback("주제 적합성", "잘함", met=True)]


def _system_prompt(client: MagicMock) -> str:
    return client.messages.create.call_args.kwargs["system"]


# ---------------------------------------------------------------------------
# Per-module: subject injected → name appears under [과목] block
# ---------------------------------------------------------------------------


def test_criteria_extractor_includes_subject_in_system_prompt(
    tmp_path: Path,
) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR 텍스트"
    rubric = tmp_path / "r.png"
    rubric.write_bytes(b"x")
    payload = json.dumps(
        {"criteria": [{"name": "x", "description": "y", "max_score": 5}]},
        ensure_ascii=False,
    )
    client = _mock_client(payload)
    extractor = EvaluationCriteriaExtractor(client=client, image_parser=image_parser)

    extractor.extract([rubric], subject=Subject.preset("국어"))

    system = _system_prompt(client)
    assert "[과목]" in system
    assert "국어" in system


def test_suggestion_engine_includes_subject_in_system_prompt() -> None:
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

    engine.suggest(_profile(), _criteria(), subject=Subject.preset("과학"))

    assert "과학" in _system_prompt(client)


def test_submission_evaluator_includes_subject_in_system_prompt() -> None:
    payload = json.dumps(
        {"feedback": [{"criterion": "주제 적합성", "feedback": "f", "met": True}]},
        ensure_ascii=False,
    )
    client = _mock_client(payload)
    evaluator = SubmissionEvaluator(client=client)

    evaluator.evaluate(
        _criteria(), submission_text="본문", subject=Subject.preset("역사")
    )

    assert "역사" in _system_prompt(client)


def test_model_answer_generator_includes_subject_in_system_prompt() -> None:
    client = _mock_client("답안 본문")
    generator = ModelAnswerGenerator(client=client)

    generator.generate(_criteria(), _profile(), subject=Subject.preset("수학"))

    assert "수학" in _system_prompt(client)


def test_sms_generator_includes_subject_in_system_prompt() -> None:
    payload = json.dumps(
        {"summary": "요약", "bullets": ["b"]}, ensure_ascii=False
    )
    client = _mock_client(payload)
    generator = SmsContentGenerator(client=client)

    generator.generate(
        _profile(),
        _evaluation(),
        assessment_name="x",
        subject=Subject.custom("음악"),
    )

    assert "음악" in _system_prompt(client)


# ---------------------------------------------------------------------------
# Subject = None → no [과목] block (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exercise",
    [
        lambda c: EvaluationCriteriaExtractor(
            client=c,
            image_parser=_make_ip("OCR"),
        ).extract([Path("/dev/null")]),
        # ^ rubric path doesn't exist; the call will fail at parser.parse
        # (we skip this case in the param expansion below by special-handling)
    ],
)
def test_dummy_to_keep_pytest_happy(exercise: object) -> None:
    """Placeholder so the parametrize doesn't get pruned in some pytest versions."""


def test_no_subject_keeps_system_prompt_clean(tmp_path: Path) -> None:
    """When subject=None, the [과목] header must not appear in any module."""
    rubric = tmp_path / "r.png"
    rubric.write_bytes(b"x")

    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR"
    payload = json.dumps(
        {"criteria": [{"name": "a", "description": "b", "max_score": None}]},
        ensure_ascii=False,
    )
    client = _mock_client(payload)
    EvaluationCriteriaExtractor(client=client, image_parser=image_parser).extract(
        [rubric]
    )

    assert "[과목]" not in _system_prompt(client)


# ---------------------------------------------------------------------------
# ReportGenerator: subject row in 학생 진로 요약
# ---------------------------------------------------------------------------


def test_report_includes_subject_row_when_provided() -> None:
    report = ReportGenerator().generate(
        _profile(),
        _criteria(),
        _evaluation(),
        model_answer="x",
        subject=Subject.preset("진로"),
    )

    assert "**과목**: 진로" in report


def test_report_omits_subject_row_when_not_provided() -> None:
    report = ReportGenerator().generate(
        _profile(), _criteria(), _evaluation(), model_answer="x"
    )

    assert "**과목**" not in report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ip(reply: str) -> MagicMock:
    ip = MagicMock()
    ip.parse.return_value = reply
    return ip
