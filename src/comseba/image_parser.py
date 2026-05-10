"""ImageParser — image → structured text via Claude vision.

Single-responsibility wrapper around the Anthropic vision API. Used by
`StudentProfileBuilder`, `EvaluationCriteriaExtractor`, and
`SubmissionEvaluator` so they don't each re-implement base64 encoding,
media-type detection, and Claude vision call shape.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from comseba.client import DEFAULT_VISION_MODEL, get_client

if TYPE_CHECKING:
    from anthropic import Anthropic

# Anthropic vision API supports these media types.
_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# 토큰 비용을 통제하기 위한 상한. OCR / 루브릭 추출 모두 이 안에서 충분.
_DEFAULT_MAX_TOKENS = 2048


class UnsupportedImageFormatError(ValueError):
    """Raised when the image extension is not in `_MEDIA_TYPES`."""


class ImageParser:
    """Calls Claude vision to extract text/JSON from an image."""

    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = DEFAULT_VISION_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client if client is not None else get_client()
        self._model = model
        self._max_tokens = max_tokens

    def parse(self, image_path: Path, prompt: str) -> str:
        """Send the image + prompt to Claude vision and return the text reply.

        Args:
            image_path: Local path to a PNG/JPG/JPEG/WEBP/GIF file.
            prompt: Instruction telling the model what to extract.

        Returns:
            The model's text response, with all text blocks concatenated.

        Raises:
            FileNotFoundError: if `image_path` does not exist.
            UnsupportedImageFormatError: if the extension is not supported.
        """
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {path}")

        media_type = _MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None:
            raise UnsupportedImageFormatError(
                f"지원하지 않는 이미지 포맷입니다: {path.suffix} "
                f"(지원: {', '.join(sorted(_MEDIA_TYPES))})"
            )

        encoded = base64.standard_b64encode(path.read_bytes()).decode("ascii")

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        return "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
