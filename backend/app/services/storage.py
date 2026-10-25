"""Local filesystem object storage (replaces MinIO in the no-Docker profile)."""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from app.core.config import settings

_SAFE_NAME = re.compile(r"[^\w.\-\u4e00-\u9fff]+")


def safe_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", name).strip("._")
    return cleaned[:120] or "file"


def save_bytes(data: bytes, filename: str) -> tuple[Path, str]:
    ext = Path(filename).suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = settings.uploads_dir / stored_name
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def write_text_snapshot(text: str, suffix: str = ".html") -> tuple[Path, str]:
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    path = settings.uploads_dir / stored_name
    path.write_text(text, encoding="utf-8")
    return path, hashlib.sha256(text.encode("utf-8")).hexdigest()


def delete_file(path_str: str | None) -> None:
    if not path_str:
        return
    try:
        path = Path(path_str)
        if path.is_file() and settings.uploads_dir in path.parents:
            path.unlink()
    except OSError:
        pass
