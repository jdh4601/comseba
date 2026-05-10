"""LocalStorage — student-keyed session file I/O (stub)."""

from __future__ import annotations

from pathlib import Path


class LocalStorage:
    def __init__(self, base_dir: Path = Path("students")) -> None:
        self.base_dir = base_dir

    def new_session(self, student_name: str) -> Path:
        raise NotImplementedError("Implemented in COM-7")
