"""Smoke test: ping the Claude API to verify wiring.

Usage:
    python scripts/smoke_test.py

Exits 0 on success, 1 on any failure with the error printed to stderr.
"""

from __future__ import annotations

import sys

from comseba.client import DEFAULT_MODEL, MissingApiKeyError, get_client


def main() -> int:
    try:
        client = get_client()
    except MissingApiKeyError as exc:
        print(f"[smoke] {exc}", file=sys.stderr)
        return 1

    try:
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=64,
            messages=[
                {
                    "role": "user",
                    "content": "한 단어로만 답해주세요: 안녕하세요라고 답하세요.",
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001 — surface any API error for the operator
        print(f"[smoke] Claude API 호출 실패: {exc}", file=sys.stderr)
        return 1

    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    print(f"[smoke] OK — model={response.model} reply={text!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
