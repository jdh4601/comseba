"""EvaluationCriteriaExtractor — rubric image(s) → list[Criterion].

ImageParser 가 OCR 을 담당하고, 별도 LLM 호출이 자유 텍스트 OCR 결과를
구조화된 루브릭으로 정규화한다. 두 단계로 분리한 이유:

- vision 단계는 "보이는 그대로" 텍스트화에 집중 → 누락 위험 최소화.
- 정규화 단계는 텍스트만 다루므로 이미지 없이도 재실행 가능 (저렴, 결정론적).

여러 장의 이미지가 들어오면 OCR 결과를 이어붙여 단일 루브릭으로 합친다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from comseba.client import DEFAULT_MODEL, get_client
from comseba.image_parser import ImageParser

if TYPE_CHECKING:
    from anthropic import Anthropic


@dataclass
class Criterion:
    name: str
    description: str
    max_score: int | None = None


_OCR_PROMPT = (
    "이 이미지는 한국 고등학교 수행평가 채점 기준표(루브릭)입니다. "
    "표 / 항목 / 점수 / 설명 등 보이는 모든 텍스트를 누락 없이 그대로 옮겨주세요. "
    "표 형태라면 행과 열의 관계를 알 수 있도록 정리해주세요."
)

_NORMALIZE_SYSTEM = (
    "당신은 한국 고등학교 교사를 돕는 수행평가 보조 AI입니다. "
    "OCR 로 추출된 평가 기준 원문을 받아 구조화된 JSON 으로 정규화합니다. "
    "원문에 없는 항목을 만들어내지 마세요."
)

_NORMALIZE_PROMPT_TEMPLATE = """\
다음은 평가 기준표를 OCR 한 원문입니다. 여러 이미지에서 추출되었을 수 있으니
중복은 하나로 합쳐주세요.

[OCR 원문]
{ocr_text}

다음 JSON 형식으로만 답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "criteria": [
    {{"name": "...", "description": "...", "max_score": 5}},
    {{"name": "...", "description": "...", "max_score": null}}
  ]
}}

- name: 평가 항목명 (예: "글의 구성", "주제 적합성")
- description: 평가 기준 설명 (원문 그대로 또는 요약)
- max_score: 만점 (원문에 점수가 있으면 정수, 없으면 null)"""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class CriteriaParseError(RuntimeError):
    """Raised when the normalization LLM response can't be parsed."""


class EvaluationCriteriaExtractor:
    def __init__(
        self,
        client: Anthropic | None = None,
        image_parser: ImageParser | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = client if client is not None else get_client()
        self._image_parser = image_parser
        self._model = model

    def extract(self, image_paths: list[Path]) -> list[Criterion]:
        if not image_paths:
            raise ValueError("평가 기준 이미지가 최소 1장 필요합니다.")

        parser = self._image_parser or ImageParser()
        chunks = [parser.parse(p, _OCR_PROMPT) for p in image_paths]
        ocr_text = "\n\n---\n\n".join(c.strip() for c in chunks if c.strip())
        if not ocr_text:
            raise CriteriaParseError(
                "OCR 결과가 비어 있습니다 — 이미지가 너무 흐리거나 빈 페이지일 수 있습니다."
            )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=_NORMALIZE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": _NORMALIZE_PROMPT_TEMPLATE.format(ocr_text=ocr_text),
                }
            ],
        )
        raw = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )
        return _parse_criteria(raw)

    def display(self, criteria: list[Criterion]) -> None:
        """Print criteria so the teacher can confirm before continuing."""
        if not criteria:
            print("(추출된 평가 항목이 없습니다)")
            return
        print("\n=== 추출된 평가 기준 ===")
        for i, c in enumerate(criteria, start=1):
            score = f" [{c.max_score}점]" if c.max_score is not None else ""
            print(f"{i}. {c.name}{score}")
            print(f"   {c.description}")
        print()

    @staticmethod
    def to_dict_list(criteria: list[Criterion]) -> list[dict[str, Any]]:
        """Serialize for storage.save_json."""
        return [asdict(c) for c in criteria]


def _parse_criteria(raw: str) -> list[Criterion]:
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CriteriaParseError(
            f"평가 기준 JSON 파싱 실패: {exc.msg} (원문 일부: {raw[:120]!r})"
        ) from exc

    items = data.get("criteria") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise CriteriaParseError(
            "평가 기준 JSON 에 'criteria' 배열이 없거나 비어 있습니다."
        )

    criteria: list[Criterion] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise CriteriaParseError(f"criteria 항목이 객체가 아닙니다: {raw_item!r}")
        name = (raw_item.get("name") or "").strip()
        description = (raw_item.get("description") or "").strip()
        if not name or not description:
            raise CriteriaParseError(
                f"criteria 항목에 name 또는 description 이 비어 있습니다: {raw_item!r}"
            )
        criteria.append(
            Criterion(
                name=name,
                description=description,
                max_score=_coerce_score(raw_item.get("max_score")),
            )
        )
    return criteria


def _coerce_score(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool 은 int 의 하위 — 명시 차단
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
