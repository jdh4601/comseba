"""ModelAnswerGenerator — rubric + profile (+ optional feedback) → 예시 답안.

PRD 의 핵심 안전 장치: 반환 텍스트의 첫 줄을 `[AI 생성 예시 답안]` 으로
강제해 학생/교사 모두 이 글이 사람의 답안이 아님을 즉시 인지하도록 한다.
LLM 출력에 의존하지 않고 코드 단에서 prefix 를 prepend 하므로
"라벨이 빠질 가능성" 자체를 차단한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from comseba.client import DEFAULT_MODEL, get_client
from comseba.criteria_extractor import Criterion
from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback

if TYPE_CHECKING:
    from anthropic import Anthropic


AI_LABEL = "[AI 생성 예시 답안]"

_SYSTEM_PROMPT = (
    "당신은 한국 고등학교 교사를 돕는 수행평가 보조 AI입니다. "
    "주어진 평가 기준을 모두 만족하는 모범 답안을 학생의 진로 / 관심사에 맞게 "
    "작성합니다. 답안은 자연스러운 한국어 문장으로 작성하고, 평가 기준에 없는 "
    "내용으로 분량을 채우지 마세요."
)

_BASE_PROMPT_TEMPLATE = """\
다음 학생의 수행평가에 사용할 모범 답안을 작성해주세요.

[학생]
이름: {name}
진로 / 목표: {career}

[평가 기준]
{criteria_block}

작성 지침:
- 평가 기준의 모든 항목을 명시적으로 충족할 것.
- 학생의 진로 / 관심사를 답안 본문에 자연스럽게 반영할 것.
- 분량은 학생이 참고하기에 적절한 정도 (보통 3-6 문단).
- 머리말 / 인사말 / 메타 설명 ("이것은 모범 답안입니다" 등) 은 쓰지 말 것 —
  본문만 작성."""

_FEEDBACK_BLOCK_TEMPLATE = """\

[학생의 직전 제출물 평가 — 미충족 항목 우선 보완]
{unmet_block}"""


class ModelAnswerGenerator:
    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 2048,
    ) -> None:
        self._client = client if client is not None else get_client()
        self._model = model
        self._max_tokens = max_tokens

    def generate(
        self,
        criteria: list[Criterion],
        profile: StudentProfile,
        evaluation: list[CriterionFeedback] | None = None,
    ) -> str:
        if not criteria:
            raise ValueError("평가 기준이 비어 있습니다.")

        prompt = _BASE_PROMPT_TEMPLATE.format(
            name=profile.name,
            career=profile.career_goal,
            criteria_block=_format_criteria(criteria),
        )
        unmet_block = _format_unmet(evaluation)
        if unmet_block:
            prompt += _FEEDBACK_BLOCK_TEMPLATE.format(unmet_block=unmet_block)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT
            + f"\n\n[현재 분석 대상 학생의 진로]\n{profile.career_goal}",
            messages=[{"role": "user", "content": prompt}],
        )
        body = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ).strip()
        if not body:
            raise RuntimeError("모범 답안 생성 결과가 비어 있습니다.")

        # LLM 이 우연히 라벨을 적었으면 중복 방지.
        if body.startswith(AI_LABEL):
            return body
        return f"{AI_LABEL}\n\n{body}"


def _format_criteria(criteria: list[Criterion]) -> str:
    return "\n".join(
        f"- {c.name}"
        + (f" ({c.max_score}점)" if c.max_score is not None else "")
        + f": {c.description}"
        for c in criteria
    )


def _format_unmet(evaluation: list[CriterionFeedback] | None) -> str:
    if not evaluation:
        return ""
    unmet = [e for e in evaluation if not e.met]
    if not unmet:
        return ""
    return "\n".join(f"- {e.criterion}: {e.feedback}" for e in unmet)
