"""HwpParser tests — real HWPX fixture (built from scratch), HWP via olefile."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import olefile
import pytest

from comseba.hwp_parser import (
    HwpParseError,
    HwpParser,
    UnsupportedHwpFormatError,
)


# ---------------------------------------------------------------------------
# Fixture builders — generate real, parser-readable files in tmp_path.
# These exercise the production parsing paths instead of mocking parsers.
# ---------------------------------------------------------------------------


def _make_hwpx(path: Path, paragraphs: list[str]) -> Path:
    """Build a minimal valid HWPX file with one section containing the given
    paragraphs. Uses the hp namespace the parser scans for.
    """
    ns = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    para_xml = "\n".join(
        f'  <hp:p xmlns:hp="{ns}"><hp:run><hp:t>{_xml_escape(p)}</hp:t></hp:run></hp:p>'
        for p in paragraphs
    )
    section = f'<?xml version="1.0" encoding="utf-8"?>\n<hp:sec xmlns:hp="{ns}">\n{para_xml}\n</hp:sec>'

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Contents/section0.xml", section)
        zf.writestr("META-INF/container.xml", "<container/>")  # filler
    return path


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _make_hwp(path: Path, body: str) -> Path:
    """Build a minimal HWP-compatible OLE file containing only a PrvText
    stream (UTF-16-LE encoded body). The parser reads exactly this stream.
    """
    encoded = body.encode("utf-16-le")
    ole = olefile.OleFileIO(_make_minimal_ole_with_stream("PrvText", encoded))
    # We can't easily *write* with olefile, so build raw bytes via a helper.
    raise RuntimeError("unreachable — see _write_hwp_with_prvtext")  # pragma: no cover


def _write_hwp_with_prvtext(path: Path, body: str) -> Path:
    """Write an OLE compound file containing one PrvText stream.

    Building OLE2 from scratch is non-trivial; we instead use olefile's
    backing primitive: create an in-memory file with required header sectors.
    To stay test-only and simple, we leverage a tiny prebuilt OLE skeleton
    and inject the PrvText bytes.
    """
    # Smallest path: use olefile's roundtrip on a known-valid HWP shell would
    # require a third-party library to write. Instead, construct a real OLE2
    # by hand with the exact sectors needed for one short stream.
    payload = _build_ole2_with_prvtext(body.encode("utf-16-le"))
    path.write_bytes(payload)
    return path


def _build_ole2_with_prvtext(stream_data: bytes) -> bytes:
    """Construct a minimal valid OLE2 compound document with exactly one
    short stream named 'PrvText'. Short stream means data lives in the
    mini-stream (sector size 64), keeping the file under one 512-byte sector.

    Reference: MS-CFB §2.6 (compound file structure).
    """
    # Header (512 bytes), sector size 512, mini sector size 64.
    SECTOR = 512
    MINI = 64

    # Stream rounded up to mini-sector multiple
    pad = (-len(stream_data)) % MINI
    mini_payload = stream_data + b"\x00" * pad
    mini_sector_count = len(mini_payload) // MINI  # number of 64-byte mini sectors

    # Sector layout (one regular sector each):
    #   sector 0: FAT
    #   sector 1: directory
    #   sector 2: mini-FAT
    #   sector 3: mini-stream container
    SECT_FAT, SECT_DIR, SECT_MINI_FAT, SECT_MINI_STREAM = 0, 1, 2, 3

    # ---- FAT (512 bytes = 128 entries) ----
    fat = bytearray(b"\xff\xff\xff\xff" * 128)  # FREESECT
    # Each used regular sector marks itself ENDOFCHAIN (or chained).
    def _set(i: int, v: int) -> None:
        fat[i * 4 : i * 4 + 4] = v.to_bytes(4, "little", signed=False)

    _set(SECT_FAT, 0xFFFFFFFD)        # FATSECT
    _set(SECT_DIR, 0xFFFFFFFE)        # ENDOFCHAIN
    _set(SECT_MINI_FAT, 0xFFFFFFFE)   # ENDOFCHAIN
    _set(SECT_MINI_STREAM, 0xFFFFFFFE)  # ENDOFCHAIN

    # ---- Mini-FAT ----
    mini_fat = bytearray(b"\xff\xff\xff\xff" * 128)
    for i in range(mini_sector_count):
        nxt = i + 1 if i + 1 < mini_sector_count else 0xFFFFFFFE
        mini_fat[i * 4 : i * 4 + 4] = nxt.to_bytes(4, "little", signed=False)

    # ---- Directory: 4 entries × 128 bytes = 512 bytes ----
    def _dir_entry(
        name: str, type_: int, color: int, left: int, right: int, child: int,
        clsid: bytes, sect: int, size: int,
    ) -> bytes:
        name_utf16 = name.encode("utf-16-le")
        name_field = name_utf16 + b"\x00" * (64 - len(name_utf16))
        return (
            name_field
            + struct.pack("<H", len(name_utf16) + 2)  # name length incl NUL
            + struct.pack("<B", type_)                 # 1=storage, 2=stream, 5=root
            + struct.pack("<B", color)                 # 0=red 1=black
            + struct.pack("<I", left)
            + struct.pack("<I", right)
            + struct.pack("<I", child)
            + clsid                                    # 16 bytes CLSID
            + b"\x00" * 4                               # state bits
            + b"\x00" * 8                               # creation time
            + b"\x00" * 8                               # modify time
            + struct.pack("<I", sect)                   # starting sector
            + struct.pack("<Q", size)                   # stream size
        )

    free = 0xFFFFFFFF
    clsid = b"\x00" * 16

    # Root entry: child = 1 (PrvText)
    root = _dir_entry(
        "Root Entry", 5, 1, free, free, 1, clsid, SECT_MINI_STREAM, len(mini_payload)
    )
    # PrvText stream: starts at mini-stream offset 0, real size
    prv = _dir_entry("PrvText", 2, 1, free, free, free, clsid, 0, len(stream_data))
    # Two unused slots (required to fill 512-byte directory sector)
    empty = b"\x00" * 128

    directory = root + prv + empty + empty
    assert len(directory) == 512

    # ---- Mini-stream container ----
    mini_stream = mini_payload + b"\x00" * (SECTOR - len(mini_payload))
    assert len(mini_stream) == SECTOR

    # ---- Header (512 bytes) ----
    header = bytearray(SECTOR)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # OLE2 signature
    header[8:24] = b"\x00" * 16                          # CLSID
    header[24:26] = b"\x3e\x00"                          # minor version
    header[26:28] = b"\x03\x00"                          # major version (3 = 512-byte sectors)
    header[28:30] = b"\xfe\xff"                          # byte order (little-endian)
    header[30:32] = b"\x09\x00"                          # sector shift (2^9 = 512)
    header[32:34] = b"\x06\x00"                          # mini-sector shift (2^6 = 64)
    header[34:40] = b"\x00" * 6                          # reserved
    header[40:44] = b"\x00" * 4                          # # directory sectors (0 for v3)
    struct.pack_into("<I", header, 44, 1)                # # FAT sectors
    struct.pack_into("<I", header, 48, SECT_DIR)         # first directory sector
    header[52:56] = b"\x00" * 4                          # transaction signature
    struct.pack_into("<I", header, 56, 0x1000)           # mini-stream cutoff size (4096)
    struct.pack_into("<I", header, 60, SECT_MINI_FAT)    # first mini-FAT sector
    struct.pack_into("<I", header, 64, 1)                # # mini-FAT sectors
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)       # first DIFAT sector (none)
    struct.pack_into("<I", header, 72, 0)                # # DIFAT sectors
    # DIFAT (109 entries) starts at offset 76
    struct.pack_into("<I", header, 76, SECT_FAT)         # FAT lives in sector 0
    for i in range(1, 109):
        struct.pack_into("<I", header, 76 + i * 4, 0xFFFFFFFF)  # FREESECT

    # ---- Assemble: header + 4 sectors ----
    return bytes(header) + bytes(fat) + bytes(directory) + bytes(mini_fat) + bytes(mini_stream)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_hwpx_returns_paragraph_text(tmp_path: Path) -> None:
    path = _make_hwpx(
        tmp_path / "career.hwpx",
        ["저는 간호사가 되고 싶습니다.", "응급실 근무에 관심이 많습니다."],
    )

    text = HwpParser().parse(path)

    assert "간호사가 되고 싶습니다." in text
    assert "응급실 근무에 관심이 많습니다." in text


def test_parse_hwpx_preserves_paragraph_separation(tmp_path: Path) -> None:
    path = _make_hwpx(tmp_path / "x.hwpx", ["첫 단락", "둘째 단락"])

    text = HwpParser().parse(path)

    # Two paragraphs separated by at least a newline
    assert "첫 단락\n둘째 단락" in text


def test_parse_hwp_returns_prvtext_body(tmp_path: Path) -> None:
    path = _write_hwp_with_prvtext(tmp_path / "career.hwp", "저는 간호사가 되고 싶습니다.")

    text = HwpParser().parse(path)

    assert "간호사가 되고 싶습니다." in text


def test_parse_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        HwpParser().parse(tmp_path / "nope.hwpx")


def test_parse_raises_for_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "doc.docx"
    bad.write_bytes(b"x")

    with pytest.raises(UnsupportedHwpFormatError):
        HwpParser().parse(bad)


def test_parse_raises_for_corrupt_hwpx_zip(tmp_path: Path) -> None:
    bad = tmp_path / "broken.hwpx"
    bad.write_bytes(b"this is not a zip")

    with pytest.raises(HwpParseError, match="HWPX"):
        HwpParser().parse(bad)


def test_parse_raises_for_hwpx_without_section_xml(tmp_path: Path) -> None:
    path = tmp_path / "empty.hwpx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", "<container/>")

    with pytest.raises(HwpParseError, match="본문 섹션"):
        HwpParser().parse(path)


def test_parse_raises_for_hwp_without_prvtext(tmp_path: Path) -> None:
    # Build OLE with empty PrvText so olefile sees the stream but we error on empty
    path = _write_hwp_with_prvtext(tmp_path / "blank.hwp", "")

    with pytest.raises(HwpParseError, match="비어 있"):
        HwpParser().parse(path)


def test_parse_raises_for_non_ole_hwp(tmp_path: Path) -> None:
    bad = tmp_path / "fake.hwp"
    bad.write_bytes(b"not an OLE compound document")

    with pytest.raises(HwpParseError, match="OLE 컨테이너"):
        HwpParser().parse(bad)


def test_built_ole_is_readable_by_olefile(tmp_path: Path) -> None:
    """Sanity check: our hand-built OLE file is well-formed enough for
    olefile to open and read the PrvText stream. Guards against accidentally
    changing the fixture builder in a way the parser would still tolerate.
    """
    path = _write_hwp_with_prvtext(tmp_path / "x.hwp", "테스트")
    assert olefile.isOleFile(str(path))
    ole = olefile.OleFileIO(str(path))
    try:
        assert ole.exists("PrvText")
        raw = ole.openstream("PrvText").read()
    finally:
        ole.close()
    assert raw.decode("utf-16-le") == "테스트"
