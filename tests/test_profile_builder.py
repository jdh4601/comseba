"""StudentProfileBuilder tests — Anthropic client + ImageParser are mocked."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.profile_builder import (
    ProfileParseError,
    StudentProfile,
    StudentProfileBuilder,
)


def _mock_client(reply: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply)],
        model="claude-sonnet-4-6",
    )
    return client


def _profile_json(
    needs: list[str], style: str | None = None, fenced: bool = False
) -> str:
    payload = json.dumps(
        {"inferred_needs": needs, "communication_style": style},
        ensure_ascii=False,
    )
    return f"```json\n{payload}\n```" if fenced else payload


def test_build_text_only_returns_profile_with_needs(tmp_path: Path) -> None:
    client = _mock_client(_profile_json(["글쓰기 구조화 연습", "AI 윤리 사례 학습"]))
    builder = StudentProfileBuilder(client=client)

    profile = builder.build(
        name="홍길동",
        career_text="AI 연구자가 되고 싶어요. 특히 NLP 분야에 관심이 있습니다.",
    )

    assert isinstance(profile, StudentProfile)
    assert profile.name == "홍길동"
    assert profile.career_goal.startswith("AI 연구자")
    assert profile.inferred_needs == ["글쓰기 구조화 연습", "AI 윤리 사례 학습"]
    assert profile.communication_style is None


def test_build_without_kakao_does_not_invoke_image_parser(tmp_path: Path) -> None:
    client = _mock_client(_profile_json(["x"]))
    image_parser = MagicMock()
    builder = StudentProfileBuilder(client=client, image_parser=image_parser)

    builder.build(name="홍길동", career_text="진로")

    image_parser.parse.assert_not_called()


def test_build_with_kakao_uses_image_parser_and_includes_text(
    tmp_path: Path,
) -> None:
    img1 = tmp_path / "kakao1.png"
    img2 = tmp_path / "kakao2.png"
    img1.write_bytes(b"x")
    img2.write_bytes(b"x")

    image_parser = MagicMock()
    image_parser.parse.side_effect = [
        "학생: 안녕하세요\n교사: 오늘 과제 어땠어?",
        "학생: 어려웠어요",
    ]
    client = _mock_client(
        _profile_json(["불안감 완화", "단계별 안내"], style="조심스럽고 짧게 답함")
    )
    builder = StudentProfileBuilder(client=client, image_parser=image_parser)

    profile = builder.build(
        name="홍길동",
        career_text="간호사가 되고 싶어요",
        kakao_image_paths=[img1, img2],
    )

    assert image_parser.parse.call_count == 2
    assert profile.communication_style == "조심스럽고 짧게 답함"

    # 두 이미지에서 추출된 텍스트가 LLM 프롬프트에 모두 포함됐는지 확인
    user_prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "학생: 안녕하세요" in user_prompt
    assert "어려웠어요" in user_prompt


def test_system_prompt_includes_career_context(tmp_path: Path) -> None:
    client = _mock_client(_profile_json([]))
    builder = StudentProfileBuilder(client=client)

    builder.build(name="홍길동", career_text="우주 비행사가 되고 싶어요")

    system = client.messages.create.call_args.kwargs["system"]
    assert "우주 비행사" in system


def test_build_handles_fenced_json(tmp_path: Path) -> None:
    client = _mock_client(_profile_json(["a", "b"], fenced=True))
    builder = StudentProfileBuilder(client=client)

    profile = builder.build(name="홍길동", career_text="진로")

    assert profile.inferred_needs == ["a", "b"]


def test_build_raises_profile_parse_error_on_bad_json(tmp_path: Path) -> None:
    client = _mock_client("이건 JSON 이 아닙니다")
    builder = StudentProfileBuilder(client=client)

    with pytest.raises(ProfileParseError):
        builder.build(name="홍길동", career_text="진로")


def test_build_rejects_empty_name_or_career(tmp_path: Path) -> None:
    builder = StudentProfileBuilder(client=_mock_client(_profile_json([])))

    with pytest.raises(ValueError):
        builder.build(name="  ", career_text="진로")
    with pytest.raises(ValueError, match="진로 정보"):
        builder.build(name="홍길동", career_text="")
    with pytest.raises(ValueError, match="진로 정보"):
        builder.build(name="홍길동")  # neither text nor hwp


def test_build_with_hwp_paths_only_uses_extracted_text(tmp_path: Path) -> None:
    hwp = tmp_path / "career.hwpx"
    hwp.write_bytes(b"x")

    hwp_parser = MagicMock()
    hwp_parser.parse.return_value = "HWP 에서 추출한 진로: 응급실 간호사가 되고 싶다."
    client = _mock_client(_profile_json(["응급 의료 사례 학습"]))
    builder = StudentProfileBuilder(client=client, hwp_parser=hwp_parser)

    profile = builder.build(name="홍길동", career_hwp_paths=[hwp])

    hwp_parser.parse.assert_called_once_with(hwp)
    assert "응급실 간호사" in profile.career_goal
    # System prompt 의 personalization anchor 에도 들어가야 함
    system = client.messages.create.call_args.kwargs["system"]
    assert "응급실 간호사" in system


def test_build_with_text_and_hwp_combines_both_into_career_goal(
    tmp_path: Path,
) -> None:
    hwp = tmp_path / "career.hwp"
    hwp.write_bytes(b"x")

    hwp_parser = MagicMock()
    hwp_parser.parse.return_value = "HWP 본문"
    builder = StudentProfileBuilder(
        client=_mock_client(_profile_json(["x"])),
        hwp_parser=hwp_parser,
    )

    profile = builder.build(
        name="홍길동",
        career_text="짧은 텍스트 입력",
        career_hwp_paths=[hwp],
    )

    assert "짧은 텍스트 입력" in profile.career_goal
    assert "HWP 본문" in profile.career_goal


def test_build_does_not_invoke_hwp_parser_when_not_provided(tmp_path: Path) -> None:
    hwp_parser = MagicMock()
    builder = StudentProfileBuilder(
        client=_mock_client(_profile_json([])), hwp_parser=hwp_parser
    )

    builder.build(name="홍길동", career_text="진로")

    hwp_parser.parse.assert_not_called()
