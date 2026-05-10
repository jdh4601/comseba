"""SmsContentGenerator — fixed-template parent SMS draft.

PRD 의 "SMS 템플릿은 고정" 원칙을 구조적으로 보장하기 위해, LLM 이 만드는 것은
**가변 부분** (한 줄 요약 + 불릿 내용) 뿐이고 인사 / 종료 / 불릿 prefix 는
Python 코드가 직접 조립한다. 이렇게 하면 LLM 이 형식을 어긋나게 답해도
출력은 항상 템플릿을 따른다.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from comseba.client import DEFAULT_MODEL, get_client
from comseba.profile_builder import StudentProfile
from comseba.submission_evaluator import CriterionFeedback

if TYPE_CHECKING:
    from anthropic import Anthropic


OPENING_TEMPLATE = (
    "안녕하세요 {name} 어머님^^ 오늘 {name}(이) '{assessment}' 초안 작성해주었습니다."
)
CLOSING_TEMPLATE = (
    "앞으로도 {name}(이) 생기부에 더 좋은 내용들이 담길 수 있도록 돕겠습니다 ! ^^"
)
BULLET_PREFIX = "-> "

_SYSTEM_PROMPT = (
    "당신은 한국 고등학교 교사를 돕는 AI입니다. 학부모에게 보낼 따뜻하고 격려하는 "
    "어조로 학생의 수행평가 진행 상황을 짧게 정리합니다. 학생을 비난하거나 부정적인 "
    "표현은 사용하지 마세요. 출력은 반드시 지정된 JSON 형식만 따릅니다."
)

_PROMPT_TEMPLATE = """\
다음 학생의 수행평가 평가 결과를 학부모에게 알리는 짧은 메시지의 *내용 부분*을
작성해주세요. 인사말 / 마무리는 제가 따로 붙일 것이므로 빼주세요.

[학생]
이름: {name}
진로: {career}

[수행평가명]
{assessment}

[항목별 평가 결과]
{evaluation_block}

다음 JSON 형식으로만 답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "summary": "오늘 학생이 어떤 활동을 어떻게 진행했는지 한 문장 (따뜻한 어조).",
  "bullets": [
    "잘한 점 또는 의미 있는 시도 1 (한 문장)",
    "잘한 점 또는 의미 있는 시도 2",
    "다음에 더 챙기면 좋을 부분 1 (있다면, 부드러운 어조)"
  ]
}}

- summary: 1 문장.
- bullets: 2-4개. 각각 짧은 한 문장. 부정적 표현 금지 — '아쉽지만', '잘 못했다' 등 X."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class SmsParseError(RuntimeError):
    """Raised when the LLM's SMS payload can't be parsed."""


class SmsContentGenerator:
    def __init__(
        self,
        client: Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
    ) -> None:
        self._client = client if client is not None else get_client()
        self._model = model
        self._max_tokens = max_tokens

    def generate(
        self,
        profile: StudentProfile,
        evaluation: list[CriterionFeedback],
        assessment_name: str,
    ) -> str:
        if not assessment_name.strip():
            raise ValueError("수행평가명이 비어 있습니다.")
        if not evaluation:
            raise ValueError("평가 결과가 비어 있습니다.")

        name = profile.name.strip()
        assessment = assessment_name.strip()

        prompt = _PROMPT_TEMPLATE.format(
            name=name,
            career=profile.career_goal,
            assessment=assessment,
            evaluation_block=_format_evaluation(evaluation),
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )
        summary, bullets = _parse_payload(raw)

        opening = OPENING_TEMPLATE.format(name=name, assessment=assessment)
        closing = CLOSING_TEMPLATE.format(name=name)
        bullet_lines = "\n".join(f"{BULLET_PREFIX}{b}" for b in bullets)

        return f"{opening}\n\n{summary}\n{bullet_lines}\n\n{closing}"


def _format_evaluation(evaluation: list[CriterionFeedback]) -> str:
    return "\n".join(
        f"- [{ '충족' if e.met else '미충족' }] {e.criterion}: {e.feedback}"
        for e in evaluation
    )


def _parse_payload(raw: str) -> tuple[str, list[str]]:
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SmsParseError(
            f"SMS JSON 파싱 실패: {exc.msg} (원문 일부: {raw[:120]!r})"
        ) from exc

    if not isinstance(data, dict):
        raise SmsParseError("SMS JSON 이 객체가 아닙니다.")
    summary = (data.get("summary") or "").strip()
    bullets_raw = data.get("bullets")
    if not summary:
        raise SmsParseError("summary 가 비어 있습니다.")
    if not isinstance(bullets_raw, list) or not bullets_raw:
        raise SmsParseError("bullets 가 비어 있거나 배열이 아닙니다.")
    bullets = [str(b).strip() for b in bullets_raw if str(b).strip()]
    if not bullets:
        raise SmsParseError("bullets 에 사용 가능한 항목이 없습니다.")
    return summary, bullets
