"""SchoolLevel value-object tests."""

from __future__ import annotations

import pytest

from comseba.level import SchoolLevel, format_level_block


def test_enum_has_exactly_two_members() -> None:
    assert set(SchoolLevel) == {SchoolLevel.MIDDLE, SchoolLevel.HIGH}


@pytest.mark.parametrize(
    "level,short,label_substr",
    [
        (SchoolLevel.MIDDLE, "중등", "중학생"),
        (SchoolLevel.HIGH, "고등", "고등학생"),
    ],
)
def test_label_and_short_korean_strings(
    level: SchoolLevel, short: str, label_substr: str
) -> None:
    assert level.short_ko == short
    assert label_substr in level.label_ko


def test_format_level_block_returns_empty_string_when_none() -> None:
    assert format_level_block(None) == ""


def test_format_level_block_includes_label_under_school_level_header() -> None:
    block = format_level_block(SchoolLevel.MIDDLE)

    assert "[학교급]" in block
    assert "중학생" in block


def test_string_value_is_serialization_safe() -> None:
    """Storing as session.json: str(SchoolLevel) must round-trip cleanly."""
    assert SchoolLevel.MIDDLE.value == "middle"
    assert SchoolLevel.HIGH.value == "high"
    assert SchoolLevel("middle") == SchoolLevel.MIDDLE
    assert SchoolLevel("high") == SchoolLevel.HIGH
