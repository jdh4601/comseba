"""AssessmentSuggestionEngine — profile + rubric → tailored activity ideas.

이 스텝은 PRD 상 선택적(skippable)이다. CLI 가 사용자에게 묻고 스킵을 선택하면
이 모듈을 호출하지 않고 빈 리스트로 다음 단계에 넘긴다 — 모듈 자체는 호출되면
항상 의미 있는 결과를 만들어 반환한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from comseba.client import DEFAULT_MODEL, get_client
from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile

if TYPE_CHECKING:
    from anthropic import Anthropic


@dataclass
class AssessmentIdea:
    title: str
    description: str
    rationale: str  # 이 학생의 진로와 어떻게 연결되는지


_MIN_IDEAS = 3
_MAX_IDEAS = 5

_SYSTEM_PROMPT = (
    "당신은 한국 고등학교 교사를 돕는 수행평가 보조 AI입니다. "
    "학생의 진로 / 관심사와 평가 기준을 모두 만족하는 수행평가 활동 아이디어를 "
    "제안합니다. 평가 기준에 없는 항목으로 점수를 받게 하지 마세요."
)

_PROMPT_TEMPLATE = """\
다음 학생에게 맞춰 수행평가 아이디어 {count}개를 제안해주세요.

[학생]
이름: {name}
진로 / 목표: {career}
파악된 학습 니즈: {needs}

[평가 기준]
{criteria_block}

다음 JSON 형식으로만 답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "ideas": [
    {{
      "title": "활동 제목 (10자 이내)",
      "description": "활동 진행 방식과 산출물 (2-3문장)",
      "rationale": "이 학생의 진로와 어떻게 연결되는지 (1-2문장)"
    }}
  ]
}}

- 정확히 {count}개 — 더도 덜도 안 됨.
- title 은 짧고 구체적으로.
- rationale 은 일반론이 아니라 *이 학생의* 진로 / 니즈를 명시적으로 언급."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class SuggestionParseError(RuntimeError):
    """Raised when the LLM response can't be parsed into ideas."""


class AssessmentSuggestionEngine:
    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = client if client is not None else get_client()
        self._model = model

    def suggest(
        self,
        profile: StudentProfile,
        criteria: list[Criterion],
        count: int = 4,
    ) -> list[AssessmentIdea]:
        if not (_MIN_IDEAS <= count <= _MAX_IDEAS):
            raise ValueError(
                f"count 는 {_MIN_IDEAS}~{_MAX_IDEAS} 사이여야 합니다 (받은 값: {count})"
            )
        if not criteria:
            raise ValueError("평가 기준이 비어 있습니다 — 먼저 EvaluationCriteriaExtractor 를 실행하세요.")

        prompt = _PROMPT_TEMPLATE.format(
            count=count,
            name=profile.name,
            career=profile.career_goal,
            needs=", ".join(profile.inferred_needs) or "(추가 정보 없음)",
            criteria_block=_format_criteria(criteria),
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT
            + f"\n\n[현재 분석 대상 학생의 진로]\n{profile.career_goal}",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )
        ideas = _parse_ideas(raw)

        # LLM 이 정확히 count 를 안 지킬 수도 있다 — 너무 많으면 자르고,
        # 너무 적으면 (3개 미만) 실패. 3-5 범위 안이면 그대로 사용.
        if len(ideas) > count:
            ideas = ideas[:count]
        if len(ideas) < _MIN_IDEAS:
            raise SuggestionParseError(
                f"수행평가 아이디어가 {_MIN_IDEAS}개 미만으로 생성되었습니다 (받은 개수: {len(ideas)})"
            )
        return ideas


def _format_criteria(criteria: list[Criterion]) -> str:
    return "\n".join(
        f"- {c.name}"
        + (f" ({c.max_score}점)" if c.max_score is not None else "")
        + f": {c.description}"
        for c in criteria
    )


def _parse_ideas(raw: str) -> list[AssessmentIdea]:
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SuggestionParseError(
            f"수행평가 아이디어 JSON 파싱 실패: {exc.msg} (원문 일부: {raw[:120]!r})"
        ) from exc

    items = data.get("ideas") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SuggestionParseError("응답에 'ideas' 배열이 없습니다.")

    ideas: list[AssessmentIdea] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise SuggestionParseError(f"ideas 항목이 객체가 아닙니다: {raw_item!r}")
        title = (raw_item.get("title") or "").strip()
        description = (raw_item.get("description") or "").strip()
        rationale = (raw_item.get("rationale") or "").strip()
        if not (title and description and rationale):
            raise SuggestionParseError(
                f"ideas 항목에 title / description / rationale 중 빈 값이 있습니다: {raw_item!r}"
            )
        ideas.append(
            AssessmentIdea(title=title, description=description, rationale=rationale)
        )
    return ideas
