"""AssessmentSuggestionEngine tests — Anthropic client mocked."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.suggestion_engine import (
    AssessmentIdea,
    AssessmentSuggestionEngine,
    SuggestionParseError,
)


def _profile() -> StudentProfile:
    return StudentProfile(
        name="홍길동",
        career_goal="AI 연구자가 되고 싶다",
        inferred_needs=["글쓰기 구조화", "최신 사례 학습"],
    )


def _criteria() -> list[Criterion]:
    return [
        Criterion("주제 적합성", "주제와 일치", 5),
        Criterion("표현력", "어휘 다양성", 5),
    ]


def _mock_client(reply: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply)],
        model="claude-sonnet-4-6",
    )
    return client


def _payload(n: int, fenced: bool = False) -> str:
    ideas = [
        {"title": f"제목{i}", "description": f"설명{i}", "rationale": f"근거{i}"}
        for i in range(n)
    ]
    s = json.dumps({"ideas": ideas}, ensure_ascii=False)
    return f"```json\n{s}\n```" if fenced else s


def test_suggest_returns_requested_count_with_full_fields() -> None:
    engine = AssessmentSuggestionEngine(client=_mock_client(_payload(4)))

    ideas = engine.suggest(_profile(), _criteria(), count=4)

    assert len(ideas) == 4
    assert all(isinstance(i, AssessmentIdea) for i in ideas)
    assert all(i.title and i.description and i.rationale for i in ideas)


def test_suggest_includes_career_in_system_prompt() -> None:
    client = _mock_client(_payload(4))
    engine = AssessmentSuggestionEngine(client=client)

    engine.suggest(_profile(), _criteria())

    system = client.messages.create.call_args.kwargs["system"]
    assert "AI 연구자" in system


def test_suggest_includes_criteria_and_needs_in_user_prompt() -> None:
    client = _mock_client(_payload(4))
    engine = AssessmentSuggestionEngine(client=client)

    engine.suggest(_profile(), _criteria())

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "주제 적합성" in prompt
    assert "표현력" in prompt
    assert "글쓰기 구조화" in prompt


def test_suggest_handles_fenced_json() -> None:
    engine = AssessmentSuggestionEngine(client=_mock_client(_payload(3, fenced=True)))

    ideas = engine.suggest(_profile(), _criteria(), count=3)

    assert len(ideas) == 3


def test_suggest_trims_excess_ideas_to_count() -> None:
    engine = AssessmentSuggestionEngine(client=_mock_client(_payload(5)))

    ideas = engine.suggest(_profile(), _criteria(), count=3)

    assert len(ideas) == 3


def test_suggest_raises_when_under_minimum() -> None:
    engine = AssessmentSuggestionEngine(client=_mock_client(_payload(2)))

    with pytest.raises(SuggestionParseError):
        engine.suggest(_profile(), _criteria())


@pytest.mark.parametrize("count", [0, 1, 2, 6, 10])
def test_suggest_rejects_count_outside_range(count: int) -> None:
    engine = AssessmentSuggestionEngine(client=_mock_client(_payload(4)))

    with pytest.raises(ValueError):
        engine.suggest(_profile(), _criteria(), count=count)


def test_suggest_raises_on_empty_criteria() -> None:
    engine = AssessmentSuggestionEngine(client=_mock_client(_payload(4)))

    with pytest.raises(ValueError):
        engine.suggest(_profile(), criteria=[])


def test_suggest_raises_on_invalid_json() -> None:
    engine = AssessmentSuggestionEngine(client=_mock_client("not json"))

    with pytest.raises(SuggestionParseError):
        engine.suggest(_profile(), _criteria())


def test_suggest_raises_on_blank_field_in_idea() -> None:
    bad = json.dumps(
        {
            "ideas": [
                {"title": "a", "description": "d", "rationale": "r"},
                {"title": "", "description": "d", "rationale": "r"},
            ]
        }
    )
    engine = AssessmentSuggestionEngine(client=_mock_client(bad))

    with pytest.raises(SuggestionParseError):
        engine.suggest(_profile(), _criteria())
