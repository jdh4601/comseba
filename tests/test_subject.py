"""Subject value object + system prompt plumbing tests."""

from __future__ import annotations

import pytest

from comseba.subject import SUBJECT_PRESETS, Subject, format_subject_block


def test_presets_match_required_seven_subjects() -> None:
    assert SUBJECT_PRESETS == ("국어", "영어", "수학", "과학", "역사", "진로", "독서")


@pytest.mark.parametrize("name", SUBJECT_PRESETS)
def test_subject_preset_marks_is_custom_false(name: str) -> None:
    s = Subject.preset(name)

    assert s.name == name
    assert s.is_custom is False


def test_subject_preset_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="알 수 없는 프리셋"):
        Subject.preset("국어II")


def test_subject_custom_marks_is_custom_true_and_strips() -> None:
    s = Subject.custom("  음악  ")

    assert s.name == "음악"
    assert s.is_custom is True


def test_subject_custom_rejects_blank() -> None:
    with pytest.raises(ValueError):
        Subject.custom("   ")


def test_subject_roundtrips_through_to_dict_from_dict() -> None:
    original = Subject.custom("통합사회")

    restored = Subject.from_dict(original.to_dict())

    assert restored == original


def test_format_subject_block_returns_empty_string_when_none() -> None:
    assert format_subject_block(None) == ""


def test_format_subject_block_includes_name_under_subject_header() -> None:
    block = format_subject_block(Subject.preset("과학"))

    assert "[과목]" in block
    assert "과학" in block
