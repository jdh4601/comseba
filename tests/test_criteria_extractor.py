"""EvaluationCriteriaExtractor tests — ImageParser + Anthropic client mocked."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comseba.criteria_extractor import (
    CriteriaParseError,
    Criterion,
    EvaluationCriteriaExtractor,
)


def _mock_client(reply: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=reply)],
        model="claude-sonnet-4-6",
    )
    return client


def _criteria_payload(items: list[dict], fenced: bool = False) -> str:
    payload = json.dumps({"criteria": items}, ensure_ascii=False)
    return f"```json\n{payload}\n```" if fenced else payload


def _img(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"x")
    return p


def test_extract_returns_criterion_list_from_single_image(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "글의 구성 5점 / 주제 적합성 5점 / 표현력 5점"
    client = _mock_client(
        _criteria_payload(
            [
                {"name": "글의 구성", "description": "서론-본론-결론 명확", "max_score": 5},
                {"name": "주제 적합성", "description": "주제와 일치", "max_score": 5},
                {"name": "표현력", "description": "어휘와 문장 다양성", "max_score": 5},
            ]
        )
    )
    extractor = EvaluationCriteriaExtractor(client=client, image_parser=image_parser)

    criteria = extractor.extract([_img(tmp_path, "rubric.png")])

    assert criteria == [
        Criterion("글의 구성", "서론-본론-결론 명확", 5),
        Criterion("주제 적합성", "주제와 일치", 5),
        Criterion("표현력", "어휘와 문장 다양성", 5),
    ]
    image_parser.parse.assert_called_once()


def test_extract_merges_multiple_images_into_one_ocr_payload(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.side_effect = ["페이지1 OCR 텍스트", "페이지2 OCR 텍스트"]
    client = _mock_client(
        _criteria_payload(
            [{"name": "항목 A", "description": "설명 A", "max_score": None}]
        )
    )
    extractor = EvaluationCriteriaExtractor(client=client, image_parser=image_parser)

    extractor.extract([_img(tmp_path, "p1.png"), _img(tmp_path, "p2.png")])

    assert image_parser.parse.call_count == 2
    user_prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "페이지1 OCR 텍스트" in user_prompt
    assert "페이지2 OCR 텍스트" in user_prompt


def test_extract_handles_fenced_json_response(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR"
    client = _mock_client(
        _criteria_payload(
            [{"name": "x", "description": "y", "max_score": 3}], fenced=True
        )
    )
    extractor = EvaluationCriteriaExtractor(client=client, image_parser=image_parser)

    criteria = extractor.extract([_img(tmp_path, "r.png")])

    assert criteria == [Criterion("x", "y", 3)]


def test_extract_coerces_string_score_and_drops_invalid(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR"
    client = _mock_client(
        _criteria_payload(
            [
                {"name": "a", "description": "d", "max_score": "10"},
                {"name": "b", "description": "d", "max_score": "n/a"},
                {"name": "c", "description": "d"},  # missing key
            ]
        )
    )
    extractor = EvaluationCriteriaExtractor(client=client, image_parser=image_parser)

    criteria = extractor.extract([_img(tmp_path, "r.png")])

    assert criteria[0].max_score == 10
    assert criteria[1].max_score is None
    assert criteria[2].max_score is None


def test_extract_requires_at_least_one_image(tmp_path: Path) -> None:
    extractor = EvaluationCriteriaExtractor(
        client=_mock_client(_criteria_payload([])), image_parser=MagicMock()
    )

    with pytest.raises(ValueError):
        extractor.extract([])


def test_extract_raises_when_ocr_returns_blank(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "   "
    extractor = EvaluationCriteriaExtractor(
        client=_mock_client(_criteria_payload([])), image_parser=image_parser
    )

    with pytest.raises(CriteriaParseError):
        extractor.extract([_img(tmp_path, "r.png")])


def test_extract_raises_on_invalid_json(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR"
    extractor = EvaluationCriteriaExtractor(
        client=_mock_client("not json at all"), image_parser=image_parser
    )

    with pytest.raises(CriteriaParseError):
        extractor.extract([_img(tmp_path, "r.png")])


def test_extract_raises_when_criteria_array_missing(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR"
    extractor = EvaluationCriteriaExtractor(
        client=_mock_client(json.dumps({"foo": "bar"})), image_parser=image_parser
    )

    with pytest.raises(CriteriaParseError):
        extractor.extract([_img(tmp_path, "r.png")])


def test_extract_raises_when_required_field_blank(tmp_path: Path) -> None:
    image_parser = MagicMock()
    image_parser.parse.return_value = "OCR"
    extractor = EvaluationCriteriaExtractor(
        client=_mock_client(
            _criteria_payload([{"name": "", "description": "desc"}])
        ),
        image_parser=image_parser,
    )

    with pytest.raises(CriteriaParseError):
        extractor.extract([_img(tmp_path, "r.png")])


def test_display_prints_numbered_list(capsys: pytest.CaptureFixture[str]) -> None:
    extractor = EvaluationCriteriaExtractor(
        client=MagicMock(), image_parser=MagicMock()
    )
    extractor.display(
        [
            Criterion("글의 구성", "서론-본론-결론", 5),
            Criterion("표현력", "어휘 다양성", None),
        ]
    )
    out = capsys.readouterr().out

    assert "1. 글의 구성 [5점]" in out
    assert "서론-본론-결론" in out
    assert "2. 표현력" in out
    assert "[" not in out.split("2. 표현력")[1].split("\n")[0]  # no score bracket


def test_to_dict_list_serializes_for_storage() -> None:
    out = EvaluationCriteriaExtractor.to_dict_list(
        [Criterion("a", "b", 5), Criterion("c", "d", None)]
    )
    assert out == [
        {"name": "a", "description": "b", "max_score": 5},
        {"name": "c", "description": "d", "max_score": None},
    ]
