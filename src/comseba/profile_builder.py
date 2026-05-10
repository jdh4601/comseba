"""StudentProfileBuilder — career text + optional KakaoTalk → StudentProfile.

The student's career goal is the personalization anchor for every downstream
LLM call (suggestions, evaluation, model answer, SMS). KakaoTalk screenshots
are optional context — when provided they're OCR'd via `ImageParser` and fed
into the same analysis prompt that produces `inferred_needs` and
`communication_style`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from comseba.client import DEFAULT_MODEL, get_client
from comseba.image_parser import ImageParser

if TYPE_CHECKING:
    from anthropic import Anthropic


@dataclass
class StudentProfile:
    name: str
    career_goal: str
    inferred_needs: list[str] = field(default_factory=list)
    communication_style: str | None = None


_SYSTEM_PROMPT = (
    "당신은 한국 고등학교 교사를 돕는 수행평가 보조 AI입니다. "
    "학생의 진로와 대화 맥락을 분석해 그 학생에게 어떤 학습 / 평가 지원이 필요한지 "
    "추론합니다. 출력은 반드시 지정된 JSON 형식만 따릅니다."
)

_PROMPT_TEMPLATE = """\
다음 학생의 정보를 바탕으로 프로필을 추론해주세요.

[학생 이름]
{name}

[학생이 직접 적은 진로 / 목표]
{career_text}

{kakao_block}

다음 JSON 형식으로만 답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "inferred_needs": ["...", "...", "..."],
  "communication_style": "한 문장으로 학생의 소통 스타일 요약 (카카오톡 자료 없으면 null)"
}}

- inferred_needs: 이 학생이 수행평가 지도를 받을 때 교사가 신경 써야 할 학습 / 진로
  관점의 니즈 2~5개 (한국어, 짧은 명사구).
- communication_style: 카카오톡 대화 자료가 있을 때만 채우고, 없으면 null."""

_KAKAO_BLOCK_TEMPLATE = "[카카오톡 대화에서 추출한 내용]\n{kakao_text}\n"
_KAKAO_OCR_PROMPT = (
    "이 카카오톡 스크린샷에서 학생과 교사(또는 학생 간) 대화 내용을 시간 순서대로 "
    "텍스트로 추출하세요. 누가 말했는지 알 수 있으면 표시해주세요."
)


class ProfileParseError(RuntimeError):
    """Raised when the LLM response can't be parsed as the expected JSON."""


class StudentProfileBuilder:
    def __init__(
        self,
        client: Anthropic | None = None,
        image_parser: ImageParser | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = client if client is not None else get_client()
        # ImageParser 는 자체적으로 client.get_client() 를 호출하므로,
        # 명시 주입이 없을 때만 lazy 로 생성한다 (테스트에서는 주입).
        self._image_parser = image_parser
        self._model = model

    def build(
        self,
        name: str,
        career_text: str,
        kakao_image_paths: list[Path] | None = None,
    ) -> StudentProfile:
        if not name.strip():
            raise ValueError("학생 이름이 비어 있습니다.")
        if not career_text.strip():
            raise ValueError("학생 진로 텍스트가 비어 있습니다.")

        kakao_text = self._extract_kakao_text(kakao_image_paths)
        prompt = self._render_prompt(name, career_text, kakao_text)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT + f"\n\n[현재 분석 대상 학생의 진로]\n{career_text}",
            messages=[{"role": "user", "content": prompt}],
        )

        raw = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )
        parsed = _parse_profile_json(raw)

        return StudentProfile(
            name=name.strip(),
            career_goal=career_text.strip(),
            inferred_needs=[str(n) for n in parsed.get("inferred_needs", [])],
            communication_style=_normalize_style(parsed.get("communication_style")),
        )

    def _extract_kakao_text(
        self, kakao_image_paths: list[Path] | None
    ) -> str | None:
        if not kakao_image_paths:
            return None
        parser = self._image_parser or ImageParser()
        chunks = [parser.parse(p, _KAKAO_OCR_PROMPT) for p in kakao_image_paths]
        return "\n\n---\n\n".join(c.strip() for c in chunks if c.strip()) or None

    @staticmethod
    def _render_prompt(name: str, career_text: str, kakao_text: str | None) -> str:
        kakao_block = (
            _KAKAO_BLOCK_TEMPLATE.format(kakao_text=kakao_text)
            if kakao_text
            else "[카카오톡 대화 자료]\n(없음)\n"
        )
        return _PROMPT_TEMPLATE.format(
            name=name, career_text=career_text, kakao_block=kakao_block
        )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_profile_json(raw: str) -> dict[str, Any]:
    """Parse the LLM JSON, tolerating ```json fenced output."""
    text = raw.strip()
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileParseError(
            f"프로필 JSON 파싱 실패: {exc.msg} (원문 일부: {raw[:120]!r})"
        ) from exc
    if not isinstance(data, dict):
        raise ProfileParseError(f"프로필 JSON 이 객체가 아닙니다: {type(data).__name__}")
    return data


def _normalize_style(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return str(value)
