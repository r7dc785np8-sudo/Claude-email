"""Extract text from PDFs, falling back to OCR for scanned pages.

Arabic in many office-generated PDFs has a broken text layer (letters out of
order or mapped to the wrong glyphs), so pages that look like garbled Arabic
are OCR'd as well.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

MIN_CHARS_PER_PAGE = 40
OCR_DPI = 300
OCR_LANGS = "ara+eng"

_ARABIC = re.compile(r"[؀-ۿ]")
# Presentation-form glyphs and invisible bidi marks are a sign of a poor text layer.
_BROKEN_ARABIC = re.compile(r"[ﭐ-﷿ﹰ-﻿‪-‮‎‏]")
# Very common Arabic words; a real Arabic text layer contains several of them.
_COMMON_ARABIC_WORDS = ("في", "من", "على", "إلى", "مع", "ضرورة", "الفندق", "التي", "أو", "عن")


@dataclass
class PageText:
    number: int
    text: str
    method: str  # "text" or "ocr"


def looks_garbled_arabic(text: str) -> bool:
    arabic = len(_ARABIC.findall(text))
    if arabic < 30:
        return False
    if len(_BROKEN_ARABIC.findall(text)) > arabic * 0.05:
        return True
    words = set(re.findall(r"[؀-ۿ]+", text))
    hits = sum(1 for w in _COMMON_ARABIC_WORDS if w in words)
    return hits < 2


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None


def extract_pdf(path: Path, ocr: str = "auto") -> list[PageText]:
    """ocr: "auto" (OCR scanned/garbled pages), "always", or "never"."""
    pages: list[PageText] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            pages.append(PageText(number, text, "text"))

    needs_ocr = [
        p for p in pages
        if ocr == "always"
        or (ocr == "auto" and (len(p.text) < MIN_CHARS_PER_PAGE or looks_garbled_arabic(p.text)))
    ]
    if needs_ocr:
        if not ocr_available():
            print("  OCR needed but tesseract/poppler are not installed "
                  "(macOS: brew install tesseract tesseract-lang poppler)")
        else:
            for page in needs_ocr:
                ocr_text = _ocr_page(path, page.number)
                if ocr_text.strip():
                    page.text, page.method = ocr_text.strip(), "ocr"
    return pages


def _ocr_page(path: Path, number: int) -> str:
    import pytesseract
    from pdf2image import convert_from_path

    images = convert_from_path(str(path), dpi=OCR_DPI, first_page=number, last_page=number)
    return "\n".join(pytesseract.image_to_string(img, lang=OCR_LANGS) for img in images)


def write_text(pages: list[PageText], target: Path) -> Path:
    body = "\n\n".join(f"===== Page {p.number} ({p.method}) =====\n{p.text}" for p in pages)
    target.write_text(body + "\n", encoding="utf-8")
    return target
