"""Save email attachments safely under attachments/YYYY-MM-DD/."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from pathlib import Path

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


@dataclass
class SavedAttachment:
    path: Path
    content_type: str
    skipped_existing: bool = False


def safe_filename(name: str | None, fallback: str = "attachment") -> str:
    """Strip directories and characters that are unsafe on macOS/Windows/Linux."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name)
    stem, dot, ext = name.rpartition(".")
    if dot:
        name = f"{stem.strip(' .')}.{ext.strip()}"
    name = name.strip(" .")
    if not name or name in (".", ".."):
        name = fallback
    if len(name.encode("utf-8")) > 200:
        stem, dot, ext = name.rpartition(".")
        keep = stem if dot else name
        while len((keep + dot + ext).encode("utf-8")) > 200:
            keep = keep[:-1]
        name = keep + dot + ext if dot else keep
    return name


def save_attachments(
    msg: EmailMessage,
    msg_date: date,
    root: Path,
    pdf_only: bool = False,
) -> list[SavedAttachment]:
    root = root.resolve()
    folder = root / msg_date.isoformat()
    saved: list[SavedAttachment] = []
    for index, part in enumerate(msg.iter_attachments(), start=1):
        content_type = part.get_content_type()
        filename = safe_filename(part.get_filename(), fallback=f"attachment-{index}")
        is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")
        if pdf_only and not is_pdf:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        if len(payload) > MAX_ATTACHMENT_BYTES:
            print(f"  skipping {filename}: larger than {MAX_ATTACHMENT_BYTES // 2**20} MB")
            continue

        folder.mkdir(parents=True, exist_ok=True)
        target = _unique_target(folder, filename, payload)
        if target.resolve().parent != folder:  # defence in depth against path tricks
            raise ValueError(f"refusing to write outside {folder}: {filename!r}")
        if target.exists():
            saved.append(SavedAttachment(target, content_type, skipped_existing=True))
            continue
        target.write_bytes(payload)
        saved.append(SavedAttachment(target, content_type))
    return saved


def _unique_target(folder: Path, filename: str, payload: bytes) -> Path:
    """Reuse an identical existing file; otherwise pick a free name."""
    target = folder / filename
    if not target.exists() or _same_content(target, payload):
        return target
    stem, suffix = target.stem, target.suffix
    n = 2
    while True:
        candidate = folder / f"{stem} ({n}){suffix}"
        if not candidate.exists() or _same_content(candidate, payload):
            return candidate
        n += 1


def _same_content(path: Path, payload: bytes) -> bool:
    return (
        path.stat().st_size == len(payload)
        and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(payload).digest()
    )
