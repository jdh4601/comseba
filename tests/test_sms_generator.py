"""SmsContentGenerator tests — fixed-template structural assertions."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.profile_builder import StudentProfile
from comseba.sms_generator import SmsContentGenerator, SmsParseError
from comseba.submission_evaluator import CriterionFeedback


def _profile() -> StudentProfile:
    return StudentProfile(name="홍길동", career_goal="간호사가 되고 싶다")


def _evaluation() -> list[CriterionFeedback]:
    return [
        CriterionFeedback("주제 적합성", "주제와 잘 맞음", met=True),
        CriterionFeedback("표현력", "어휘 다양성 좋음", met=True),
    ]


def _payload(summary: str, bullets: list[str], fenced: bool = False) -> str:
    s = json.dumps({"summary": summary, "bullets": bullets}, ensure_ascii=False)
    return f"```json\n{s}\n```" if fenced else s


def _mock_client(reply: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply)],
        model="claude-sonnet-4-6",
    )
    return client


def test_generate_starts_with_opening_line() -> None:
    gen = SmsContentGenerator(client=_mock_client(_payload("요약", ["bullet1"])))

    sms = gen.generate(_profile(), _evaluation(), assessment_name="과학 글쓰기")

    assert sms.startswith(
        "안녕하세요 홍길동 어머님^^ 오늘 홍길동(이) '과학 글쓰기' 초안 작성해주었습니다."
    )


def test_generate_wraps_assessment_name_in_single_quotes() -> None:
    gen = SmsContentGenerator(client=_mock_client(_payload("요약", ["b"])))

    sms = gen.generate(_profile(), _evaluation(), assessment_name="환경 보고서")

    assert "'환경 보고서'" in sms


def test_generate_includes_arrow_bullets_for_each_item() -> None:
    gen = SmsContentGenerator(
        client=_mock_client(_payload("요약", ["하나", "둘", "셋"]))
    )

    sms = gen.generate(_profile(), _evaluation(), assessment_name="과학 글쓰기")

    assert "-> 하나" in sms
    assert "-> 둘" in sms
    assert "-> 셋" in sms


def test_generate_includes_summary_line_above_bullets() -> None:
    gen = SmsContentGenerator(
        client=_mock_client(_payload("오늘 열심히 작성했습니다.", ["b1"]))
    )

    sms = gen.generate(_profile(), _evaluation(), assessment_name="x")

    summary_idx = sms.index("오늘 열심히 작성했습니다.")
    first_bullet_idx = sms.index("-> b1")
    assert summary_idx < first_bullet_idx


def test_generate_ends_with_closing_phrase() -> None:
    gen = SmsContentGenerator(client=_mock_client(_payload("요약", ["b"])))

    sms = gen.generate(_profile(), _evaluation(), assessment_name="과학")

    assert sms.rstrip().endswith(
        "앞으로도 홍길동(이) 생기부에 더 좋은 내용들이 담길 수 있도록 돕겠습니다 ! ^^"
    )


def test_generate_handles_fenced_json() -> None:
    gen = SmsContentGenerator(
        client=_mock_client(_payload("요약", ["b"], fenced=True))
    )

    sms = gen.generate(_profile(), _evaluation(), assessment_name="x")

    assert "-> b" in sms


def test_generate_filters_blank_bullets() -> None:
    gen = SmsContentGenerator(
        client=_mock_client(_payload("요약", ["진짜 불릿", "  ", ""]))
    )

    sms = gen.generate(_profile(), _evaluation(), assessment_name="x")

    assert "-> 진짜 불릿" in sms
    # 빈 불릿이 라인을 만들지 않아야 함
    assert "->  \n" not in sms
    assert "-> \n" not in sms


def test_generate_raises_on_blank_assessment_name() -> None:
    gen = SmsContentGenerator(client=_mock_client(_payload("요약", ["b"])))

    with pytest.raises(ValueError):
        gen.generate(_profile(), _evaluation(), assessment_name="   ")


def test_generate_raises_on_empty_evaluation() -> None:
    gen = SmsContentGenerator(client=_mock_client(_payload("요약", ["b"])))

    with pytest.raises(ValueError):
        gen.generate(_profile(), evaluation=[], assessment_name="x")


def test_generate_raises_on_invalid_json() -> None:
    gen = SmsContentGenerator(client=_mock_client("not json"))

    with pytest.raises(SmsParseError):
        gen.generate(_profile(), _evaluation(), assessment_name="x")


def test_generate_raises_when_summary_blank() -> None:
    gen = SmsContentGenerator(client=_mock_client(_payload("", ["b"])))

    with pytest.raises(SmsParseError):
        gen.generate(_profile(), _evaluation(), assessment_name="x")


def test_generate_raises_when_all_bullets_blank() -> None:
    gen = SmsContentGenerator(client=_mock_client(_payload("요약", ["", "  "])))

    with pytest.raises(SmsParseError):
        gen.generate(_profile(), _evaluation(), assessment_name="x")
