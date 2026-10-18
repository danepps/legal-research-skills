#!/usr/bin/env python3
"""Initialize hidden run state for a Zotero library build."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def parse_library(value: str) -> dict[str, str]:
    try:
        kind, library_id = value.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("library must be user:<id> or group:<id>") from exc
    if kind not in {"user", "group"} or not library_id.strip():
        raise argparse.ArgumentTypeError("library must be user:<id> or group:<id>")
    return {"type": kind, "id": library_id.strip()}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:48].rstrip("-") or "library")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--request", required=True)
    parser.add_argument("--library", type=parse_library)
    parser.add_argument("--collection-name", default="")
    parser.add_argument("--collection-key", default="")
    parser.add_argument("--require-pdfs", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args()

    now = datetime.now().astimezone()
    run_id = args.run_id or f"{now:%Y%m%d-%H%M%S}-{slugify(args.collection_name or args.request)}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", run_id):
        parser.error("run id must contain only letters, digits, dot, underscore, or hyphen")

    run_dir = args.project_dir.expanduser().resolve() / ".codex-zotero" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    run = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": now.isoformat(timespec="seconds"),
        "request": args.request,
        "library": args.library or {"type": "", "id": ""},
        "collection": {
            "name": args.collection_name,
            "key": args.collection_key,
            "created": False,
        },
        "require_pdfs": args.require_pdfs,
        "status": "planning",
    }
    write_json(run_dir / "run.json", run)
    write_json(run_dir / "planned-items.json", [])
    (run_dir / "candidates.jsonl").write_text("", encoding="utf-8")
    (run_dir / "manual-verifications.jsonl").write_text("", encoding="utf-8")
    (run_dir / "reuse-results.jsonl").write_text("", encoding="utf-8")
    (run_dir / "attachment-results.jsonl").write_text("", encoding="utf-8")

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
