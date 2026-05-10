"""LocalStorage — student-keyed session file I/O.

Layout:

    students/
      {studentName}/
        profile.json              # 학생 단위 영속 프로필 (세션 간 공유)
        profile_history/          # 갱신 이력 (ISO 시각 기준 스냅샷)
          2026-05-10T14-30-00.json
        YYYY-MM-DD_session{N}/
          session.json            # 진행 상태 + 완료된 스텝 + profile_updated_at
          rubric.json
          evaluation.json
          report.md
          sms.txt

학생 프로필은 *학생 단위* 데이터이므로 세션 디렉토리가 아니라 학생 디렉토리에 둔다.
같은 학생의 여러 세션이 같은 프로필 컨텍스트를 공유하고, 학기 동안 진로가 바뀌면
직전 버전을 `profile_history/` 에 ISO 시각 파일명으로 보존한다.

All reads/writes are UTF-8. JSON is written with `ensure_ascii=False` so Korean
content stays human-readable in the saved files.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

_SESSION_FILE = "session.json"
_STUDENT_PROFILE_FILE = "profile.json"
_PROFILE_HISTORY_DIR = "profile_history"


class LocalStorage:
    """Per-student session directories under `base_dir`."""

    def __init__(self, base_dir: Path | str = Path("students")) -> None:
        self.base_dir = Path(base_dir)

    def new_session(
        self, student_name: str, today: date | None = None
    ) -> Path:
        """Create a new session directory and return its path.

        The name is `YYYY-MM-DD_session{N}` where N auto-increments per day.
        Initializes `session.json` with an empty completed-steps list so callers
        can immediately call `load_session_state()` without a None check.
        """
        if not student_name or not student_name.strip():
            raise ValueError("학생 이름이 비어 있습니다.")

        student_dir = self.base_dir / student_name
        student_dir.mkdir(parents=True, exist_ok=True)

        today = today or date.today()
        date_prefix = today.isoformat()  # 2026-05-10

        n = 1
        while (student_dir / f"{date_prefix}_session{n}").exists():
            n += 1

        session_path = student_dir / f"{date_prefix}_session{n}"
        session_path.mkdir()

        self.save_json(
            session_path,
            _SESSION_FILE,
            {
                "student_name": student_name,
                "created_at": date_prefix,
                "completed_steps": [],
            },
        )
        return session_path

    def save_json(
        self, session_path: Path, filename: str, data: dict[str, Any]
    ) -> None:
        path = session_path / filename
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_json(self, session_path: Path, filename: str) -> dict[str, Any]:
        path = session_path / filename
        return json.loads(path.read_text(encoding="utf-8"))

    def save_text(self, session_path: Path, filename: str, content: str) -> None:
        (session_path / filename).write_text(content, encoding="utf-8")

    def load_text(self, session_path: Path, filename: str) -> str:
        return (session_path / filename).read_text(encoding="utf-8")

    def list_sessions(self, student_name: str) -> list[Path]:
        """Return existing session dirs for a student, oldest first.

        Returns an empty list if the student has no folder yet — callers can
        treat "no sessions" and "new student" the same way.
        """
        student_dir = self.base_dir / student_name
        if not student_dir.is_dir():
            return []
        return sorted(p for p in student_dir.iterdir() if p.is_dir())

    def load_session_state(self, session_path: Path) -> dict[str, Any]:
        """Read `session.json` — the source of truth for resume support."""
        return self.load_json(session_path, _SESSION_FILE)

    def mark_step_completed(self, session_path: Path, step: str) -> None:
        """Append a step to `completed_steps` (idempotent)."""
        state = self.load_session_state(session_path)
        steps: list[str] = state.setdefault("completed_steps", [])
        if step not in steps:
            steps.append(step)
            self.save_json(session_path, _SESSION_FILE, state)

    # ------------------------------------------------------------------
    # Student-level profile (shared across sessions)
    # ------------------------------------------------------------------

    def student_dir(self, student_name: str) -> Path:
        """Return (and create) the student's directory."""
        if not student_name or not student_name.strip():
            raise ValueError("학생 이름이 비어 있습니다.")
        path = self.base_dir / student_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def has_profile(self, student_name: str) -> bool:
        return (self.base_dir / student_name / _STUDENT_PROFILE_FILE).is_file()

    def load_profile(self, student_name: str) -> dict[str, Any]:
        path = self.base_dir / student_name / _STUDENT_PROFILE_FILE
        return json.loads(path.read_text(encoding="utf-8"))

    def save_profile(
        self,
        student_name: str,
        data: dict[str, Any],
        archive_previous: bool = True,
        now: datetime | None = None,
    ) -> None:
        """Write the student's profile, archiving the previous version.

        If `archive_previous` is True and a profile already exists, it is moved
        into `profile_history/{ISO timestamp}.json` before the new version is
        written. Pass `now` for deterministic tests.
        """
        student_dir = self.student_dir(student_name)
        target = student_dir / _STUDENT_PROFILE_FILE

        if archive_previous and target.is_file():
            history_dir = student_dir / _PROFILE_HISTORY_DIR
            history_dir.mkdir(exist_ok=True)
            stamp = (now or datetime.now()).strftime("%Y-%m-%dT%H-%M-%S")
            archive_name = f"{stamp}.json"
            # 같은 초에 두 번 갱신되면 충돌 방지를 위해 `_2`, `_3` 접미.
            archive_path = history_dir / archive_name
            n = 2
            while archive_path.exists():
                archive_path = history_dir / f"{stamp}_{n}.json"
                n += 1
            archive_path.write_bytes(target.read_bytes())

        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_profile_history(self, student_name: str) -> list[Path]:
        history_dir = self.base_dir / student_name / _PROFILE_HISTORY_DIR
        if not history_dir.is_dir():
            return []
        return sorted(history_dir.glob("*.json"))

    def migrate_session_profile_to_student(
        self, student_name: str, now: datetime | None = None
    ) -> bool:
        """One-shot migration for legacy sessions.

        If the student directory has no `profile.json` but at least one session
        contains one, copy the most recent session's profile to the student
        level and snapshot it into `profile_history/`. Returns True if work was
        done, False otherwise (no-op when already migrated or no source).
        """
        if self.has_profile(student_name):
            return False
        sessions = self.list_sessions(student_name)
        # 가장 최근 (정렬상 마지막) 세션부터 역순으로 살펴보며 profile.json 발견 시 채택.
        for session_path in reversed(sessions):
            candidate = session_path / _STUDENT_PROFILE_FILE
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                # 첫 저장이라 archive_previous 효과 없음 — 대신 history 에 동일 사본을
                # 명시적으로 추가해 "이 시점에 이 프로필을 사용했다" 라는 audit trail.
                self.save_profile(student_name, data, archive_previous=False, now=now)
                stamp = (now or datetime.now()).strftime("%Y-%m-%dT%H-%M-%S")
                history_dir = self.base_dir / student_name / _PROFILE_HISTORY_DIR
                history_dir.mkdir(exist_ok=True)
                (history_dir / f"{stamp}_migrated.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return True
        return False
