"""ModelAnswerGenerator tests — Anthropic client mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.criteria_extractor import Criterion
from comseba.model_answer_generator import AI_LABEL, ModelAnswerGenerator
from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback


def _profile() -> StudentProfile:
    return StudentProfile(name="홍길동", career_goal="우주 비행사가 되고 싶다")


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


def test_generate_prepends_ai_label() -> None:
    generator = ModelAnswerGenerator(client=_mock_client("본문 첫 문장.\n둘째 문단."))

    result = generator.generate(_criteria(), _profile())

    assert result.startswith(AI_LABEL)
    assert "본문 첫 문장." in result


def test_generate_does_not_double_label_when_llm_already_includes_it() -> None:
    generator = ModelAnswerGenerator(
        client=_mock_client(f"{AI_LABEL}\n\n이미 라벨이 있는 답안")
    )

    result = generator.generate(_criteria(), _profile())

    assert result.count(AI_LABEL) == 1


def test_generate_includes_career_in_system_prompt() -> None:
    client = _mock_client("답안")
    generator = ModelAnswerGenerator(client=client)

    generator.generate(_criteria(), _profile())

    system = client.messages.create.call_args.kwargs["system"]
    assert "우주 비행사" in system


def test_generate_includes_criteria_in_user_prompt() -> None:
    client = _mock_client("답안")
    generator = ModelAnswerGenerator(client=client)

    generator.generate(_criteria(), _profile())

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "주제 적합성" in prompt
    assert "표현력" in prompt


def test_generate_includes_only_unmet_feedback_when_evaluation_provided() -> None:
    client = _mock_client("답안")
    generator = ModelAnswerGenerator(client=client)
    evaluation = [
        CriterionFeedback("주제 적합성", "주제 잘 잡았으나 결론 약함", met=True),
        CriterionFeedback("표현력", "어휘 반복이 많음", met=False),
    ]

    generator.generate(_criteria(), _profile(), evaluation=evaluation)

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "어휘 반복이 많음" in prompt
    # 충족된 항목 피드백은 보완 블록에 포함되지 않아야 함
    assert "주제 잘 잡았으나" not in prompt


def test_generate_skips_unmet_block_when_all_met() -> None:
    client = _mock_client("답안")
    generator = ModelAnswerGenerator(client=client)
    evaluation = [
        CriterionFeedback("주제 적합성", "ok", met=True),
        CriterionFeedback("표현력", "ok", met=True),
    ]

    generator.generate(_criteria(), _profile(), evaluation=evaluation)

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "미충족 항목" not in prompt


def test_generate_raises_on_empty_criteria() -> None:
    generator = ModelAnswerGenerator(client=_mock_client("답안"))

    with pytest.raises(ValueError):
        generator.generate(criteria=[], profile=_profile())


def test_generate_raises_on_blank_response() -> None:
    generator = ModelAnswerGenerator(client=_mock_client("   "))

    with pytest.raises(RuntimeError):
        generator.generate(_criteria(), _profile())
