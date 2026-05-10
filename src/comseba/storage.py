"""LocalStorage — student-keyed session file I/O.

Layout:

    students/
      {studentName}/
        YYYY-MM-DD_session{N}/
          session.json    # 진행 상태 + 완료된 스텝
          rubric.json
          evaluation.json
          report.md
          sms.txt

All reads/writes are UTF-8. JSON is written with `ensure_ascii=False` so Korean
content stays human-readable in the saved files.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

_SESSION_FILE = "session.json"


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
