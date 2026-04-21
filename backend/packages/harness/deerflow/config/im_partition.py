"""IM user id path partitioning (safe filesystem segments)."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sanitize_im_user_id(raw: str) -> str:
    """Return a stable SHA-256 hex digest of the stripped UTF-8 user id."""
    s = raw.strip()
    if not s:
        raise ValueError("im user id must be non-empty after stripping whitespace")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def im_user_root(global_base: Path, safe_segment: str, *, segment_dir: str = "im_users") -> Path:
    """Resolve the per-user root under *global_base* / *segment_dir* / *safe_segment*."""
    if not safe_segment:
        raise ValueError("safe_segment must be non-empty")
    if "/" in safe_segment or ".." in safe_segment:
        raise ValueError("safe_segment must not contain '/' or '..'")
    return (Path(global_base) / segment_dir / safe_segment).resolve()
