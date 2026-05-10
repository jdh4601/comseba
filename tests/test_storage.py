"""LocalStorage tests — real filesystem I/O via tmp_path."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from comseba.storage import LocalStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(base_dir=tmp_path / "students")


def test_new_session_creates_dated_session1_dir(storage: LocalStorage) -> None:
    session = storage.new_session("홍길동", today=date(2026, 5, 7))

    assert session.is_dir()
    assert session.name == "2026-05-07_session1"
    assert session.parent.name == "홍길동"


def test_new_session_increments_for_same_day(storage: LocalStorage) -> None:
    today = date(2026, 5, 7)
    s1 = storage.new_session("홍길동", today=today)
    s2 = storage.new_session("홍길동", today=today)
    s3 = storage.new_session("홍길동", today=today)

    assert s1.name == "2026-05-07_session1"
    assert s2.name == "2026-05-07_session2"
    assert s3.name == "2026-05-07_session3"


def test_new_session_resets_counter_per_day(storage: LocalStorage) -> None:
    storage.new_session("홍길동", today=date(2026, 5, 7))
    next_day = storage.new_session("홍길동", today=date(2026, 5, 8))

    assert next_day.name == "2026-05-08_session1"


def test_new_session_initializes_session_json(storage: LocalStorage) -> None:
    session = storage.new_session("홍길동", today=date(2026, 5, 7))

    state = storage.load_session_state(session)
    assert state["student_name"] == "홍길동"
    assert state["created_at"] == "2026-05-07"
    assert state["completed_steps"] == []


def test_new_session_rejects_blank_name(storage: LocalStorage) -> None:
    with pytest.raises(ValueError):
        storage.new_session("   ")


def test_save_and_load_json_roundtrip_preserves_korean(
    storage: LocalStorage,
) -> None:
    session = storage.new_session("홍길동")
    payload = {"항목": "글쓰기 능력", "점수": 4, "메모": "구성이 탄탄함"}

    storage.save_json(session, "rubric.json", payload)
    loaded = storage.load_json(session, "rubric.json")

    assert loaded == payload
    raw = (session / "rubric.json").read_text(encoding="utf-8")
    assert "글쓰기 능력" in raw  # not \uXXXX escaped


def test_save_and_load_text_roundtrip(storage: LocalStorage) -> None:
    session = storage.new_session("홍길동")

    storage.save_text(session, "report.md", "# 보고서\n\n내용입니다.")

    assert storage.load_text(session, "report.md") == "# 보고서\n\n내용입니다."


def test_list_sessions_returns_empty_for_unknown_student(
    storage: LocalStorage,
) -> None:
    assert storage.list_sessions("없는학생") == []


def test_list_sessions_returns_sorted_session_dirs(storage: LocalStorage) -> None:
    storage.new_session("홍길동", today=date(2026, 5, 7))
    storage.new_session("홍길동", today=date(2026, 5, 8))
    storage.new_session("홍길동", today=date(2026, 5, 7))

    names = [p.name for p in storage.list_sessions("홍길동")]
    assert names == [
        "2026-05-07_session1",
        "2026-05-07_session2",
        "2026-05-08_session1",
    ]


def test_mark_step_completed_appends_and_is_idempotent(
    storage: LocalStorage,
) -> None:
    session = storage.new_session("홍길동")

    storage.mark_step_completed(session, "rubric_extracted")
    storage.mark_step_completed(session, "submission_evaluated")
    storage.mark_step_completed(session, "rubric_extracted")  # duplicate

    state = storage.load_session_state(session)
    assert state["completed_steps"] == ["rubric_extracted", "submission_evaluated"]
