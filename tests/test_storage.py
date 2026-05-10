"""LocalStorage tests — real filesystem I/O via tmp_path."""

from __future__ import annotations

import json
from datetime import date, datetime
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


# ---------------------------------------------------------------------------
# Student-level profile (COM-20)
# ---------------------------------------------------------------------------


def test_has_profile_returns_false_when_no_profile_exists(
    storage: LocalStorage,
) -> None:
    assert storage.has_profile("홍길동") is False


def test_save_and_load_profile_roundtrip(storage: LocalStorage) -> None:
    storage.save_profile("홍길동", {"career_goal": "간호사", "name": "홍길동"})

    assert storage.has_profile("홍길동")
    loaded = storage.load_profile("홍길동")
    assert loaded["career_goal"] == "간호사"


def test_first_save_profile_creates_no_history(storage: LocalStorage) -> None:
    storage.save_profile("홍길동", {"career_goal": "간호사"})

    assert storage.list_profile_history("홍길동") == []


def test_second_save_profile_archives_previous_with_iso_timestamp(
    storage: LocalStorage,
) -> None:
    storage.save_profile(
        "홍길동",
        {"career_goal": "간호사 v1"},
        now=datetime(2026, 5, 10, 14, 30, 0),
    )
    storage.save_profile(
        "홍길동",
        {"career_goal": "간호사 v2"},
        now=datetime(2026, 6, 1, 9, 0, 0),
    )

    history = storage.list_profile_history("홍길동")
    assert len(history) == 1
    # 두 번째 저장 시 직전(v1) 이 history 로 이동, 파일명은 새 저장 시각 (v2 시점)
    assert history[0].name == "2026-06-01T09-00-00.json"
    archived = json.loads(history[0].read_text(encoding="utf-8"))
    assert archived["career_goal"] == "간호사 v1"
    # 현재 파일은 v2
    assert storage.load_profile("홍길동")["career_goal"] == "간호사 v2"


def test_save_profile_with_archive_disabled_keeps_history_empty(
    storage: LocalStorage,
) -> None:
    storage.save_profile("홍길동", {"career_goal": "v1"})
    storage.save_profile(
        "홍길동", {"career_goal": "v2"}, archive_previous=False
    )

    assert storage.list_profile_history("홍길동") == []
    assert storage.load_profile("홍길동")["career_goal"] == "v2"


def test_save_profile_handles_same_second_collision(storage: LocalStorage) -> None:
    same_time = datetime(2026, 5, 10, 14, 30, 0)
    storage.save_profile("홍길동", {"v": 1})
    storage.save_profile("홍길동", {"v": 2}, now=same_time)
    storage.save_profile("홍길동", {"v": 3}, now=same_time)

    names = sorted(p.name for p in storage.list_profile_history("홍길동"))
    assert names == ["2026-05-10T14-30-00.json", "2026-05-10T14-30-00_2.json"]


def test_migrate_returns_false_when_no_session_profile(
    storage: LocalStorage,
) -> None:
    storage.new_session("홍길동")  # session exists but no profile.json inside

    assert storage.migrate_session_profile_to_student("홍길동") is False
    assert not storage.has_profile("홍길동")


def test_migrate_returns_false_when_already_at_student_level(
    storage: LocalStorage,
) -> None:
    storage.save_profile("홍길동", {"career_goal": "이미 있음"})

    assert storage.migrate_session_profile_to_student("홍길동") is False


def test_migrate_promotes_most_recent_session_profile(
    storage: LocalStorage,
) -> None:
    s1 = storage.new_session("홍길동", today=date(2026, 5, 7))
    s2 = storage.new_session("홍길동", today=date(2026, 5, 8))
    storage.save_json(s1, "profile.json", {"career_goal": "오래된 진로"})
    storage.save_json(s2, "profile.json", {"career_goal": "최신 진로"})

    moved = storage.migrate_session_profile_to_student(
        "홍길동", now=datetime(2026, 6, 1, 12, 0, 0)
    )

    assert moved is True
    assert storage.has_profile("홍길동")
    # 최신 세션의 것이 채택돼야 함
    assert storage.load_profile("홍길동")["career_goal"] == "최신 진로"
    # 마이그레이션 시 history 에 audit 항목 1개
    history = storage.list_profile_history("홍길동")
    assert len(history) == 1
    assert "_migrated.json" in history[0].name


def test_migrate_is_noop_when_already_migrated(storage: LocalStorage) -> None:
    s1 = storage.new_session("홍길동", today=date(2026, 5, 7))
    storage.save_json(s1, "profile.json", {"career_goal": "from session"})

    storage.migrate_session_profile_to_student("홍길동")
    second_run = storage.migrate_session_profile_to_student("홍길동")

    assert second_run is False  # 멱등
