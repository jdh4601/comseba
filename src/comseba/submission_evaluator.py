"""SubmissionEvaluator — submission (text / image / PDF) → per-criterion feedback.

루브릭과 학생 제출물을 받아 각 항목별로 서술 피드백 + 충족 여부(`met`)를 반환한다.
PDF 는 텍스트 추출 후 본문에 합치고, 이미지는 Claude vision 에 직접 전달한다
(손글씨 / 다이어그램 등 시각 정보를 잃지 않기 위해 OCR 단계를 건너뜀).
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader

from comseba.client import DEFAULT_MODEL, get_client
from comseba.criteria_extractor import Criterion
from comseba.image_parser import (
    UnsupportedImageFormatError,
    _MEDIA_TYPES,  # noqa: PLC2701  — 의도적 재사용
)
from comseba.subject import Subject, format_subject_block

if TYPE_CHECKING:
    from anthropic import Anthropic


@dataclass
class CriterionFeedback:
    criterion: str
    feedback: str
    met: bool


_SYSTEM_PROMPT = (
    "당신은 한국 고등학교 교사를 돕는 수행평가 보조 AI입니다. "
    "학생의 제출물을 평가 기준 항목 하나하나에 따라 평가하고, 항목별로 "
    "충족 여부(met) 와 서술 피드백을 작성합니다. "
    "피드백은 학생이 다음에 무엇을 개선하면 좋을지 구체적으로 안내해야 합니다."
)

_USER_PROMPT_TEMPLATE = """\
[평가 기준]
{criteria_block}

[학생 제출물]
{submission_block}

각 평가 기준 항목에 대해 다음 JSON 형식으로만 답하세요. 다른 텍스트는
절대 포함하지 마세요. **항목 순서와 이름은 위 평가 기준과 정확히 동일하게**
유지하세요.

{{
  "feedback": [
    {{"criterion": "...", "feedback": "...", "met": true}},
    {{"criterion": "...", "feedback": "...", "met": false}}
  ]
}}

- criterion: 위 평가 기준의 name 그대로 (수정 / 의역 금지).
- feedback: 2-4 문장. 잘한 점 + 개선할 점 모두 포함.
- met: 해당 항목을 충족하면 true, 아니면 false."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class EvaluationParseError(RuntimeError):
    """Raised when the evaluation response can't be parsed or aligned."""


class SubmissionEvaluator:
    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> None:
        self._client = client if client is not None else get_client()
        self._model = model
        self._max_tokens = max_tokens

    def evaluate(
        self,
        criteria: list[Criterion],
        submission_text: str | None = None,
        submission_image_paths: list[Path] | None = None,
        submission_pdf_paths: list[Path] | None = None,
        subject: Subject | None = None,
    ) -> list[CriterionFeedback]:
        if not criteria:
            raise ValueError("평가 기준이 비어 있습니다.")

        text_parts: list[str] = []
        if submission_text and submission_text.strip():
            text_parts.append(submission_text.strip())
        for pdf in submission_pdf_paths or []:
            text_parts.append(_extract_pdf_text(pdf))

        image_blocks = [
            _image_block(p) for p in (submission_image_paths or [])
        ]

        if not text_parts and not image_blocks:
            raise ValueError(
                "제출물이 비어 있습니다 — text / image / pdf 중 최소 하나는 필요합니다."
            )

        submission_block = (
            "\n\n---\n\n".join(text_parts) if text_parts else "(텍스트 없음 — 첨부 이미지 참고)"
        )
        prompt_text = _USER_PROMPT_TEMPLATE.format(
            criteria_block=_format_criteria(criteria),
            submission_block=submission_block,
        )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        content.extend(image_blocks)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT + format_subject_block(subject),
            messages=[{"role": "user", "content": content}],
        )
        raw = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )
        return _parse_feedback(raw, criteria)


def _format_criteria(criteria: list[Criterion]) -> str:
    return "\n".join(
        f"- {c.name}"
        + (f" ({c.max_score}점)" if c.max_score is not None else "")
        + f": {c.description}"
        for c in criteria
    )


def _image_block(path: Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"제출물 이미지를 찾을 수 없습니다: {p}")
    media_type = _MEDIA_TYPES.get(p.suffix.lower())
    if media_type is None:
        raise UnsupportedImageFormatError(
            f"지원하지 않는 이미지 포맷입니다: {p.suffix}"
        )
    encoded = base64.standard_b64encode(p.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": encoded},
    }


def _extract_pdf_text(path: Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"제출물 PDF 를 찾을 수 없습니다: {p}")
    reader = PdfReader(str(p))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(p for p in pages if p)
    if not text:
        raise EvaluationParseError(
            f"PDF 에서 텍스트를 추출하지 못했습니다 (스캔된 이미지 PDF 일 수 있음): {p}"
        )
    return text


def _parse_feedback(
    raw: str, criteria: list[Criterion]
) -> list[CriterionFeedback]:
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvaluationParseError(
            f"평가 JSON 파싱 실패: {exc.msg} (원문 일부: {raw[:120]!r})"
        ) from exc

    items = data.get("feedback") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise EvaluationParseError("응답에 'feedback' 배열이 없습니다.")

    if len(items) != len(criteria):
        raise EvaluationParseError(
            f"피드백 개수가 평가 기준 개수와 다릅니다: "
            f"{len(items)} vs {len(criteria)}"
        )

    by_name = {c.name: c for c in criteria}
    seen: set[str] = set()
    result: list[CriterionFeedback] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise EvaluationParseError(f"feedback 항목이 객체가 아닙니다: {raw_item!r}")
        name = (raw_item.get("criterion") or "").strip()
        feedback = (raw_item.get("feedback") or "").strip()
        met = raw_item.get("met")
        if name not in by_name:
            raise EvaluationParseError(
                f"평가 기준에 없는 항목이 응답에 등장했습니다: {name!r}"
            )
        if name in seen:
            raise EvaluationParseError(f"동일 항목이 중복 등장했습니다: {name!r}")
        if not feedback:
            raise EvaluationParseError(f"feedback 이 비어 있습니다: {name!r}")
        if not isinstance(met, bool):
            raise EvaluationParseError(
                f"met 가 boolean 이 아닙니다 ({name!r}): {met!r}"
            )
        seen.add(name)
        result.append(CriterionFeedback(criterion=name, feedback=feedback, met=met))

    # 평가 기준 순서대로 정렬해서 반환 — 다운스트림 (보고서 / SMS) 가 안전하게 인덱싱.
    result.sort(key=lambda f: list(by_name).index(f.criterion))
    return result
