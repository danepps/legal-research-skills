#!/usr/bin/env python3
"""Shared helpers for internal-proofread scripts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: expected a JSON object")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def validate_finding_location(row: dict, blocks: dict[str, dict]) -> None:
    """Reject unlocatable findings instead of publishing invented anchors."""
    location = row.get("location")
    if not isinstance(location, dict):
        raise ValueError("finding requires a location object")
    block = blocks.get(location.get("block_id"))
    if block is None:
        raise ValueError(f"finding references unknown block {location.get('block_id')!r}")
    text = str(block.get("text", ""))
    start, end = location.get("char_start"), location.get("char_end")
    if (type(start) is not int or type(end) is not int
            or not 0 <= start <= end <= len(text)):
        raise ValueError("finding character range is missing or outside its source block")
    excerpt = normalize_space(str(row.get("excerpt") or "")).strip("…")
    if not excerpt or excerpt not in normalize_space(text):
        raise ValueError("finding excerpt is missing or absent from its source block")


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE))


def stable_id(*parts: object, prefix: str = "F") -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return prefix + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12].upper()


def excerpt_around(text: str, start: int, end: int, radius: int = 80) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = "…" if left else ""
    suffix = "…" if right < len(text) else ""
    return prefix + normalize_space(text[left:right]) + suffix
