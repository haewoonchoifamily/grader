"""시험지/정답지 파일 리더: HWP, HWPX, PDF, 이미지 -> (텍스트, 페이지 이미지 목록)

반환값 Doc:
  text   : 추출된 텍스트 (없으면 빈 문자열)
  images : PNG/JPEG bytes 리스트 (스캔본·이미지·그림이 필요한 경우 Claude 비전에 전달)
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
SUPPORTED_EXTS = {".hwp", ".hwpx", ".pdf"} | IMAGE_EXTS

MAX_IMAGE_SIDE = 1800  # 비전 입력 최대 변 길이(px)
MIN_TEXT_CHARS_PER_PDF_PAGE = 30  # 이보다 적으면 스캔본으로 간주


@dataclass
class Doc:
    path: str
    text: str = ""
    images: list = field(default_factory=list)  # list[tuple[bytes, media_type]]
    note: str = ""


# ----------------------------------------------------------------------------
# 이미지
# ----------------------------------------------------------------------------
def _normalize_image(data: bytes) -> tuple[bytes, str]:
    """어떤 이미지든 크기를 줄여 JPEG/PNG bytes로 변환."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # 스마트폰 사진 회전 보정
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    scale = MAX_IMAGE_SIDE / max(w, h)
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


def read_image(path: str) -> Doc:
    data = Path(path).read_bytes()
    if Path(path).suffix.lower() in {".tif", ".tiff"}:
        # 다중 페이지 TIFF 지원
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        pages = []
        n = getattr(im, "n_frames", 1)
        for i in range(n):
            im.seek(i)
            b = io.BytesIO()
            im.convert("RGB").save(b, format="PNG")
            pages.append(_normalize_image(b.getvalue()))
        return Doc(path, images=pages)
    return Doc(path, images=[_normalize_image(data)])


# ----------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------
def read_pdf(path: str) -> Doc:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    texts, images = [], []
    scanned_pages = 0
    for page in doc:
        t = page.get_text("text").strip()
        texts.append(t)
        if len(t) < MIN_TEXT_CHARS_PER_PDF_PAGE:
            scanned_pages += 1
            pix = page.get_pixmap(dpi=170)
            images.append(_normalize_image(pix.tobytes("png")))
    note = ""
    if scanned_pages:
        note = f"스캔본으로 보이는 {scanned_pages}페이지는 이미지로 인식합니다."
    return Doc(path, text="\n".join(x for x in texts if x), images=images, note=note)


# ----------------------------------------------------------------------------
# HWPX (zip + XML)
# ----------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_hwpx(path: str) -> Doc:
    paras: list[str] = []
    images = []
    with zipfile.ZipFile(path) as z:
        sections = sorted(
            n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)
        )
        for name in sections:
            root = ET.fromstring(z.read(name))
            # <hp:p> 문단 단위로 <hp:t> 텍스트를 모은다
            for p in root.iter():
                if _local(p.tag) != "p":
                    continue
                buf = []
                for el in p.iter():
                    ln = _local(el.tag)
                    if ln == "t":
                        buf.append("".join(el.itertext()))
                    elif ln == "lineBreak":
                        buf.append("\n")
                    elif ln == "tab":
                        buf.append("\t")
                s = "".join(buf).strip()
                if s:
                    paras.append(s)
        # 본문에 그림으로 들어간 정답/답안(손글씨 스캔 등)도 보내기 위해 BinData 이미지 수집
        for n in z.namelist():
            if n.startswith("BinData/") and Path(n).suffix.lower() in IMAGE_EXTS:
                try:
                    images.append(_normalize_image(z.read(n)))
                except Exception:
                    pass
    text = _dedupe_nested("\n".join(paras))
    return Doc(path, text=text, images=images[:10])


def _dedupe_nested(text: str) -> str:
    """표 안의 문단이 바깥 문단에도 포함되어 중복되는 경우 줄 단위로 연속 중복 제거."""
    out, prev = [], None
    for line in text.split("\n"):
        if line != prev:
            out.append(line)
        prev = line
    return "\n".join(out)


# ----------------------------------------------------------------------------
# HWP 5.x (OLE 복합 파일) — 본문 텍스트 직접 파싱
# ----------------------------------------------------------------------------
HWPTAG_BEGIN = 0x10
HWPTAG_PARA_TEXT = HWPTAG_BEGIN + 51  # 67

# 16바이트(문자 2 + 부가정보 14)를 차지하는 컨트롤 문자: 1~9(탭 포함), 11, 12, 14~23
_SKIP16 = set(range(1, 10)) | {11, 12} | set(range(14, 24))


def _parse_para_text(data: bytes) -> str:
    out = []
    i, n = 0, len(data)
    while i + 1 < n:
        ch = struct.unpack_from("<H", data, i)[0]
        if ch >= 32:
            out.append(chr(ch))
            i += 2
        elif ch in (10, 13):
            out.append("\n")
            i += 2
        elif ch == 24:  # 하이픈
            out.append("-")
            i += 2
        elif ch in (30, 31):  # 묶음 빈칸, 고정폭 빈칸
            out.append(" ")
            i += 2
        elif ch == 9:  # 탭: 인라인 컨트롤(16바이트)
            out.append("\t")
            i += 16
        elif ch in _SKIP16:
            i += 16
        else:
            i += 2
    return "".join(out)


def _iter_records(data: bytes):
    i, n = 0, len(data)
    while i + 4 <= n:
        header = struct.unpack_from("<I", data, i)[0]
        i += 4
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            if i + 4 > n:
                break
            size = struct.unpack_from("<I", data, i)[0]
            i += 4
        yield tag, data[i : i + size]
        i += size


def read_hwp(path: str) -> Doc:
    import olefile

    if not olefile.isOleFile(path):
        # 확장자만 .hwp인 HWPX(zip)인 경우
        if zipfile.is_zipfile(path):
            return read_hwpx(path)
        raise ValueError("올바른 HWP 파일이 아닙니다.")

    ole = olefile.OleFileIO(path)
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        compressed = bool(flags & 1)
        encrypted = bool(flags & 2)
        if encrypted:
            raise ValueError("암호가 걸린 HWP 파일입니다. 암호를 해제한 뒤 사용해 주세요.")

        sections = sorted(
            (e for e in ole.listdir() if e[0] == "BodyText" and e[-1].startswith("Section")),
            key=lambda e: int(re.sub(r"\D", "", e[-1]) or 0),
        )
        paras = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            for tag, payload in _iter_records(raw):
                if tag == HWPTAG_PARA_TEXT:
                    s = _parse_para_text(payload).strip()
                    if s:
                        paras.append(s)

        images = []
        for entry in ole.listdir():
            if entry[0] == "BinData" and Path(entry[-1]).suffix.lower() in IMAGE_EXTS:
                try:
                    images.append(_normalize_image(ole.openstream(entry).read()))
                except Exception:
                    pass
        return Doc(path, text="\n".join(paras), images=images[:10])
    finally:
        ole.close()


# ----------------------------------------------------------------------------
def read_any(path: str) -> Doc:
    ext = Path(path).suffix.lower()
    if ext == ".hwp":
        return read_hwp(path)
    if ext == ".hwpx":
        return read_hwpx(path)
    if ext == ".pdf":
        return read_pdf(path)
    if ext in IMAGE_EXTS:
        return read_image(path)
    raise ValueError(f"지원하지 않는 형식입니다: {ext}")
