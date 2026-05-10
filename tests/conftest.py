"""Shared pytest fixtures for unit tests.

PRD §Testing Decisions: Claude API 는 mock, 입력은 fixture 로 결정론적이고
빠른 실행을 보장한다. 이 conftest 가 4개 핵심 모듈 (CriteriaExtractor,
SubmissionEvaluator, ReportGenerator, SmsContentGenerator) 의 공통 입력
객체와 mock 클라이언트 팩토리를 제공한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback


@pytest.fixture
def student_profile() -> StudentProfile:
    """Default profile for downstream module tests."""
    return StudentProfile(
        name="홍길동",
        career_goal="간호사가 되고 싶다",
        inferred_needs=["사례 학습", "글쓰기 구조화"],
        communication_style="조심스럽고 짧게 답함",
    )


@pytest.fixture
def criteria() -> list[Criterion]:
    """Default rubric: 3 items, mix of scored and unscored."""
    return [
        Criterion(name="주제 적합성", description="주제와 일치", max_score=5),
        Criterion(name="표현력", description="어휘 다양성", max_score=5),
        Criterion(name="논리성", description="주장-근거 연결", max_score=None),
    ]


@pytest.fixture
def evaluation() -> list[CriterionFeedback]:
    """Default evaluation: mix of met and unmet."""
    return [
        CriterionFeedback(criterion="주제 적합성", feedback="주제 잘 잡았음", met=True),
        CriterionFeedback(criterion="표현력", feedback="어휘 반복 보완 필요", met=False),
        CriterionFeedback(criterion="논리성", feedback="근거 보강 필요", met=False),
    ]


@pytest.fixture
def mock_anthropic_client() -> Callable[[str], MagicMock]:
    """Factory: build a mock Anthropic client whose `messages.create` returns
    a single text block with the given reply.

    Usage:
        def test_x(mock_anthropic_client):
            client = mock_anthropic_client("응답 텍스트")
    """

    def _build(reply_text: str) -> MagicMock:
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=reply_text)],
            model="claude-sonnet-4-6",
        )
        return client

    return _build


@pytest.fixture
def criteria_json_reply(criteria: list[Criterion]) -> str:
    """JSON payload that EvaluationCriteriaExtractor expects from the LLM,
    populated from the `criteria` fixture so name/desc match exactly.
    """
    return json.dumps(
        {
            "criteria": [
                {
                    "name": c.name,
                    "description": c.description,
                    "max_score": c.max_score,
                }
                for c in criteria
            ]
        },
        ensure_ascii=False,
    )


@pytest.fixture
def evaluation_json_reply(criteria: list[Criterion]) -> str:
    """JSON payload that SubmissionEvaluator expects from the LLM, with one
    item per criterion so the length-matching guard passes.
    """
    return json.dumps(
        {
            "feedback": [
                {
                    "criterion": c.name,
                    "feedback": f"{c.name} 에 대한 피드백입니다.",
                    "met": True,
                }
                for c in criteria
            ]
        },
        ensure_ascii=False,
    )
