"""HwpParser — extract plain text from HWP / HWPX (Hancom Office) documents.

한국 학교 환경에서 학생 자료 (진로 보고서 등) 는 HWP / HWPX 형식으로 제공되는 경우가
대다수다. 이 모듈은 두 포맷에서 본문 텍스트만 빠르게 뽑아서 LLM 분석 파이프라인에
바로 흘려보낸다.

## 라이브러리 선정 근거

- **HWPX (.hwpx)** — XML/zip 기반 신 포맷. 외부 의존 없이 `zipfile` + `xml.etree` 만으로
  처리. 내부에 `Contents/section*.xml` 들이 들어 있고, 각 텍스트는 `<hp:t>` 태그.

- **HWP 5.x (.hwp)** — 한컴 독자 OLE 컴파운드 포맷. `olefile` 로 컨테이너만 열고
  `PrvText` 스트림 (UTF-16-LE 인코딩된 본문 미리보기) 을 읽는다. PrvText 는 본문 전체를
  다 담지는 않지만 (보통 첫 ~1KB), 진로 텍스트처럼 짧은 문서에는 충분하다. 전체 본문
  추출은 `BodyText/Section*` 스트림을 zlib 풀고 record 형식을 파싱해야 해서 복잡도가
  급격히 올라간다 — 본 모듈 범위 밖. (PrvText 가 빈 경우 명확한 예외로 알린다.)

## 출력 정책

- 각 호출은 단일 텍스트 문자열을 반환.
- HWPX 의 여러 section 은 두 줄 띄움으로 이어붙임.
- 빈 줄은 보존 (학생 글의 단락 구조 유지).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import olefile


_SUPPORTED_SUFFIXES = {".hwp", ".hwpx"}


class UnsupportedHwpFormatError(ValueError):
    """Raised when the file extension is not .hwp or .hwpx."""


class HwpParseError(RuntimeError):
    """Raised when the file is corrupt or no text could be extracted."""


class HwpParser:
    """Extracts plain text from HWP and HWPX files.

    Stateless — safe to share a single instance across threads/calls.
    """

    def parse(self, path: Path) -> str:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"HWP / HWPX 파일을 찾을 수 없습니다: {p}")

        suffix = p.suffix.lower()
        if suffix not in _SUPPORTED_SUFFIXES:
            raise UnsupportedHwpFormatError(
                f"지원하지 않는 한글 파일 포맷입니다: {p.suffix} "
                f"(지원: {', '.join(sorted(_SUPPORTED_SUFFIXES))})"
            )

        if suffix == ".hwpx":
            return _parse_hwpx(p)
        return _parse_hwp(p)


# ---------------------------------------------------------------------------
# HWPX (XML / zip)
# ---------------------------------------------------------------------------

# HWPX 의 section XML 안에서 본문 텍스트는 hp 네임스페이스의 <t> 태그.
_HWPX_TEXT_TAG = "{http://www.hancom.co.kr/hwpml/2011/paragraph}t"
_HWPX_PARA_TAG = "{http://www.hancom.co.kr/hwpml/2011/paragraph}p"


def _parse_hwpx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            section_names = sorted(
                n for n in zf.namelist() if n.startswith("Contents/section") and n.endswith(".xml")
            )
            if not section_names:
                raise HwpParseError(
                    f"HWPX 파일에 본문 섹션이 없습니다: {path}. 손상된 파일일 수 있습니다."
                )
            chunks: list[str] = []
            for name in section_names:
                with zf.open(name) as fp:
                    chunks.append(_extract_hwpx_section(fp.read()))
    except zipfile.BadZipFile as exc:
        raise HwpParseError(
            f"HWPX 파일을 열 수 없습니다 (손상되었거나 zip 이 아닙니다): {path}"
        ) from exc

    text = "\n\n".join(c for c in chunks if c.strip())
    if not text.strip():
        raise HwpParseError(
            f"HWPX 파일에서 텍스트를 추출하지 못했습니다 (빈 문서일 수 있음): {path}"
        )
    return text


def _extract_hwpx_section(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise HwpParseError(f"HWPX 섹션 XML 파싱 실패: {exc}") from exc

    # 단락 (<hp:p>) 단위로 모아서 단락 사이에 줄바꿈을 보존.
    paragraphs: list[str] = []
    for para in root.iter(_HWPX_PARA_TAG):
        runs = [(t.text or "") for t in para.iter(_HWPX_TEXT_TAG)]
        line = "".join(runs).rstrip()
        paragraphs.append(line)
    return "\n".join(paragraphs).strip()


# ---------------------------------------------------------------------------
# HWP 5.x (OLE compound)
# ---------------------------------------------------------------------------

_PRV_TEXT_STREAM = "PrvText"  # OLE 안의 plain-text preview stream (UTF-16-LE)


def _parse_hwp(path: Path) -> str:
    if not olefile.isOleFile(str(path)):
        raise HwpParseError(
            f"HWP 파일이 OLE 컨테이너가 아닙니다 (손상되었거나 다른 포맷일 수 있음): {path}"
        )

    try:
        ole = olefile.OleFileIO(str(path))
    except OSError as exc:
        raise HwpParseError(f"HWP 파일을 열 수 없습니다: {path} ({exc})") from exc

    try:
        if not ole.exists(_PRV_TEXT_STREAM):
            raise HwpParseError(
                f"HWP 파일에 미리보기 텍스트 스트림이 없습니다: {path}. "
                f"본문이 매우 길거나 한컴 외 도구로 만들어진 파일일 수 있습니다 — "
                f"본문을 직접 텍스트로 입력해주세요."
            )
        raw = ole.openstream(_PRV_TEXT_STREAM).read()
    finally:
        ole.close()

    # PrvText 는 UTF-16-LE. 끝부분에 NUL 패딩이 있을 수 있으므로 strip.
    text = raw.decode("utf-16-le", errors="replace").rstrip("\x00").strip()
    if not text:
        raise HwpParseError(
            f"HWP 미리보기 텍스트가 비어 있습니다: {path}. "
            f"본문을 직접 텍스트로 입력해주세요."
        )
    return text
