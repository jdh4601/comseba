"""Anthropic client factory.

Centralizes API key loading and client construction so every module gets a
consistently configured `anthropic.Anthropic` instance.
"""

from __future__ import annotations

import os
from functools import lru_cache

from anthropic import Anthropic
from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_VISION_MODEL = "claude-sonnet-4-6"


class MissingApiKeyError(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is not configured."""


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    """Return a singleton Anthropic client built from the environment.

    Loads `.env` (if present) so local development works without exporting
    variables manually. Raises `MissingApiKeyError` with a clear remediation
    message when the key is absent — never silently uses an empty key.
    """
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise MissingApiKeyError(
            "ANTHROPIC_API_KEY 가 설정되어 있지 않습니다. "
            ".env 파일을 만들고 키를 입력하세요 (.env.example 참고)."
        )
    return Anthropic(api_key=api_key)
