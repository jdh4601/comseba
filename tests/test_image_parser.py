"""ImageParser unit tests — Claude API is mocked, no network calls."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.image_parser import ImageParser, UnsupportedImageFormatError


# Smallest valid 1x1 PNG, used so we never need real fixture files on disk.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _png_file(tmp_path: Path, name: str = "img.png") -> Path:
    p = tmp_path / name
    p.write_bytes(_PNG_1X1)
    return p


def _mock_client(reply_text: str = "추출된 텍스트") -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply_text)],
        model="claude-sonnet-4-6",
    )
    return client


def test_parse_returns_concatenated_text(tmp_path: Path) -> None:
    client = _mock_client("hello")
    parser = ImageParser(client=client)

    result = parser.parse(_png_file(tmp_path), prompt="describe")

    assert result == "hello"


def test_parse_sends_base64_payload_with_correct_media_type(tmp_path: Path) -> None:
    client = _mock_client()
    parser = ImageParser(client=client, model="claude-sonnet-4-6")

    parser.parse(_png_file(tmp_path, "rubric.png"), prompt="OCR 해주세요")

    client.messages.create.assert_called_once()
    kwargs = client.messages.create.call_args.kwargs

    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] > 0

    content = kwargs["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    text_block = next(b for b in content if b["type"] == "text")

    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    assert image_block["source"]["data"] == base64.standard_b64encode(_PNG_1X1).decode(
        "ascii"
    )
    assert text_block["text"] == "OCR 해주세요"


@pytest.mark.parametrize(
    "filename,expected_media_type",
    [
        ("a.jpg", "image/jpeg"),
        ("a.JPEG", "image/jpeg"),
        ("a.webp", "image/webp"),
    ],
)
def test_parse_detects_media_type_from_extension(
    tmp_path: Path, filename: str, expected_media_type: str
) -> None:
    path = tmp_path / filename
    path.write_bytes(_PNG_1X1)  # contents irrelevant — only ext is used
    client = _mock_client()
    parser = ImageParser(client=client)

    parser.parse(path, prompt="x")

    image_block = client.messages.create.call_args.kwargs["messages"][0]["content"][0]
    assert image_block["source"]["media_type"] == expected_media_type


def test_parse_raises_filenotfounderror_for_missing_path(tmp_path: Path) -> None:
    parser = ImageParser(client=_mock_client())

    with pytest.raises(FileNotFoundError):
        parser.parse(tmp_path / "missing.png", prompt="x")


def test_parse_raises_for_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "doc.bmp"
    bad.write_bytes(_PNG_1X1)
    parser = ImageParser(client=_mock_client())

    with pytest.raises(UnsupportedImageFormatError):
        parser.parse(bad, prompt="x")


def test_parse_does_not_call_api_when_validation_fails(tmp_path: Path) -> None:
    client = _mock_client()
    parser = ImageParser(client=client)

    with pytest.raises(FileNotFoundError):
        parser.parse(tmp_path / "nope.png", prompt="x")

    client.messages.create.assert_not_called()
