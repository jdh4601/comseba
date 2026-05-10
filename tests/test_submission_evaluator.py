"""SubmissionEvaluator tests — Anthropic client mocked, real PDF generation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.criteria_extractor import Criterion
from comseba.submission_evaluator import (
    CriterionFeedback,
    EvaluationParseError,
    SubmissionEvaluator,
)


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _criteria() -> list[Criterion]:
    return [
        Criterion("주제 적합성", "주제와 일치", 5),
        Criterion("표현력", "어휘 다양성", 5),
        Criterion("논리성", "주장-근거 연결", 5),
    ]


def _feedback_payload(items: list[dict], fenced: bool = False) -> str:
    s = json.dumps({"feedback": items}, ensure_ascii=False)
    return f"```json\n{s}\n```" if fenced else s


def _mock_client(reply: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply)],
        model="claude-sonnet-4-6",
    )
    return client


def _full_payload(items: list[Criterion]) -> str:
    return _feedback_payload(
        [
            {"criterion": c.name, "feedback": f"{c.name} 피드백", "met": True}
            for c in items
        ]
    )


def test_evaluate_text_only_returns_one_feedback_per_criterion() -> None:
    criteria = _criteria()
    evaluator = SubmissionEvaluator(client=_mock_client(_full_payload(criteria)))

    feedback = evaluator.evaluate(criteria, submission_text="학생이 작성한 글입니다.")

    assert len(feedback) == len(criteria)
    assert [f.criterion for f in feedback] == [c.name for c in criteria]
    assert all(isinstance(f, CriterionFeedback) for f in feedback)


def test_evaluate_returns_results_in_criteria_order_even_if_llm_shuffles() -> None:
    criteria = _criteria()
    shuffled = _feedback_payload(
        [
            {"criterion": "논리성", "feedback": "f1", "met": True},
            {"criterion": "주제 적합성", "feedback": "f2", "met": False},
            {"criterion": "표현력", "feedback": "f3", "met": True},
        ]
    )
    evaluator = SubmissionEvaluator(client=_mock_client(shuffled))

    feedback = evaluator.evaluate(criteria, submission_text="x")

    assert [f.criterion for f in feedback] == ["주제 적합성", "표현력", "논리성"]


def test_evaluate_with_image_attaches_image_block(tmp_path: Path) -> None:
    img = tmp_path / "submission.png"
    img.write_bytes(_PNG_1X1)
    criteria = _criteria()
    client = _mock_client(_full_payload(criteria))
    evaluator = SubmissionEvaluator(client=client)

    evaluator.evaluate(criteria, submission_image_paths=[img])

    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["media_type"] == "image/png"


def test_evaluate_with_pdf_extracts_text_into_prompt(tmp_path: Path) -> None:
    # PDF body uses ASCII because Helvetica (Type1) lacks Korean glyphs —
    # the round-trip we're verifying is "PDF text → prompt", not font support.
    pdf = _make_pdf(tmp_path / "essay.pdf", "Student submitted essay body.")
    criteria = _criteria()
    client = _mock_client(_full_payload(criteria))
    evaluator = SubmissionEvaluator(client=client)

    evaluator.evaluate(criteria, submission_pdf_paths=[pdf])

    text_block = next(
        b for b in client.messages.create.call_args.kwargs["messages"][0]["content"]
        if b["type"] == "text"
    )
    assert "Student submitted essay body." in text_block["text"]


def test_evaluate_mixed_text_image_pdf(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "x.pdf", "PDF body text")
    img = tmp_path / "y.png"
    img.write_bytes(_PNG_1X1)
    criteria = _criteria()
    client = _mock_client(_full_payload(criteria))
    evaluator = SubmissionEvaluator(client=client)

    evaluator.evaluate(
        criteria,
        submission_text="직접 입력 텍스트",
        submission_image_paths=[img],
        submission_pdf_paths=[pdf],
    )

    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    text_block = next(b for b in content if b["type"] == "text")
    image_blocks = [b for b in content if b["type"] == "image"]

    assert "직접 입력 텍스트" in text_block["text"]
    assert "PDF body text" in text_block["text"]
    assert len(image_blocks) == 1


def test_evaluate_handles_fenced_json() -> None:
    criteria = _criteria()
    payload = _feedback_payload(
        [
            {"criterion": c.name, "feedback": "f", "met": True}
            for c in criteria
        ],
        fenced=True,
    )
    evaluator = SubmissionEvaluator(client=_mock_client(payload))

    feedback = evaluator.evaluate(criteria, submission_text="x")

    assert len(feedback) == 3


def test_evaluate_raises_on_empty_inputs() -> None:
    evaluator = SubmissionEvaluator(client=_mock_client("{}"))
    with pytest.raises(ValueError):
        evaluator.evaluate(criteria=[], submission_text="x")
    with pytest.raises(ValueError):
        evaluator.evaluate(_criteria())  # no text/image/pdf


def test_evaluate_raises_when_count_mismatch() -> None:
    criteria = _criteria()
    short = _feedback_payload(
        [{"criterion": "주제 적합성", "feedback": "f", "met": True}]
    )
    evaluator = SubmissionEvaluator(client=_mock_client(short))

    with pytest.raises(EvaluationParseError, match="개수"):
        evaluator.evaluate(criteria, submission_text="x")


def test_evaluate_raises_when_unknown_criterion_returned() -> None:
    criteria = _criteria()
    bogus = _feedback_payload(
        [
            {"criterion": "주제 적합성", "feedback": "f", "met": True},
            {"criterion": "표현력", "feedback": "f", "met": True},
            {"criterion": "엉뚱한 항목", "feedback": "f", "met": True},
        ]
    )
    evaluator = SubmissionEvaluator(client=_mock_client(bogus))

    with pytest.raises(EvaluationParseError, match="없는 항목"):
        evaluator.evaluate(criteria, submission_text="x")


def test_evaluate_raises_when_duplicate_criterion_returned() -> None:
    criteria = _criteria()
    dup = _feedback_payload(
        [
            {"criterion": "주제 적합성", "feedback": "f", "met": True},
            {"criterion": "주제 적합성", "feedback": "f", "met": True},
            {"criterion": "표현력", "feedback": "f", "met": True},
        ]
    )
    evaluator = SubmissionEvaluator(client=_mock_client(dup))

    with pytest.raises(EvaluationParseError, match="중복"):
        evaluator.evaluate(criteria, submission_text="x")


def test_evaluate_raises_when_met_is_not_boolean() -> None:
    criteria = _criteria()
    bad = _feedback_payload(
        [
            {"criterion": c.name, "feedback": "f", "met": "true"}  # 문자열
            for c in criteria
        ]
    )
    evaluator = SubmissionEvaluator(client=_mock_client(bad))

    with pytest.raises(EvaluationParseError, match="boolean"):
        evaluator.evaluate(criteria, submission_text="x")


def test_evaluate_raises_for_missing_image(tmp_path: Path) -> None:
    evaluator = SubmissionEvaluator(client=_mock_client("{}"))
    with pytest.raises(FileNotFoundError):
        evaluator.evaluate(
            _criteria(), submission_image_paths=[tmp_path / "missing.png"]
        )


def test_evaluate_raises_for_unsupported_image_extension(tmp_path: Path) -> None:
    bad = tmp_path / "img.bmp"
    bad.write_bytes(_PNG_1X1)
    from comseba.image_parser import UnsupportedImageFormatError

    evaluator = SubmissionEvaluator(client=_mock_client("{}"))
    with pytest.raises(UnsupportedImageFormatError):
        evaluator.evaluate(_criteria(), submission_image_paths=[bad])


def _make_pdf(path: Path, body: str) -> Path:
    """Generate a real one-page PDF with `body` text using pypdf only."""
    # pypdf 자체로 단순 PDF 를 만들어 외부 의존 없이 PDF 추출 경로를 테스트.
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        TextStringObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)

    # Build a minimal content stream that draws `body`.
    safe = body.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(
        f"BT /F1 12 Tf 30 250 Td ({safe}) Tj ET".encode("utf-8")
    )
    page[NameObject("/Contents")] = stream

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    page[NameObject("/Resources")] = resources
    page[NameObject("/MediaBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(300), FloatObject(300)]
    )
    # Force a fresh extract_text path
    _ = TextStringObject(body)

    with path.open("wb") as f:
        writer.write(f)
    return path
