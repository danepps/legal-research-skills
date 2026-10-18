#!/usr/bin/env python3
"""Initialize an auditable internal-proofread run directory."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from common import SCHEMA_VERSION, read_json, utc_now, write_json


EMPTY_FILES = (
    "findings.jsonl", "dispositions.jsonl", "verifier-audit.jsonl", "rejection-audit.jsonl",
    "rejection-packets.jsonl", "recall-packets.jsonl", "challenger-findings.jsonl", "challenger-unmatched.jsonl",
)


def run(command: list[str]) -> None:
    completed = subprocess.run(command, text=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def default_run_dir(draft: Path) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", draft.stem.lower()).strip("-") or "draft"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return draft.parent / ".codex-proofread" / "runs" / f"{slug}-{stamp}-{uuid.uuid4().hex[:8]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument(
        "--run-dir", type=Path,
        help="hidden audit directory; defaults to <draft-parent>/.codex-proofread/runs/<unique-run-id>",
    )
    parser.add_argument("--review-depth", choices=("standard", "exhaustive"), default="standard")
    parser.add_argument("--min-words", type=int)
    parser.add_argument("--target-words", type=int)
    parser.add_argument("--max-words", type=int)
    parser.add_argument("--context-words", type=int, default=120)
    args = parser.parse_args()
    defaults = {
        "standard": (1200, 1500, 1800),
        "exhaustive": (800, 1000, 1200),
    }
    default_min, default_target, default_max = defaults[args.review_depth]
    args.min_words = default_min if args.min_words is None else args.min_words
    args.target_words = default_target if args.target_words is None else args.target_words
    args.max_words = default_max if args.max_words is None else args.max_words
    if not (0 < args.min_words <= args.target_words <= args.max_words):
        parser.error("require 0 < min-words <= target-words <= max-words")
    draft = args.draft.expanduser().resolve()
    if not draft.is_file():
        parser.error(f"draft does not exist: {draft}")
    run_dir = (args.run_dir.expanduser().resolve() if args.run_dir else default_run_dir(draft))
    if run_dir.exists() and any(run_dir.iterdir()):
        parser.error(f"run directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot_suffix = draft.suffix.lower() or ".txt"
    snapshot_path = run_dir / f"source-snapshot{snapshot_suffix}"
    shutil.copy2(draft, snapshot_path)
    scripts = Path(__file__).resolve().parent
    document_path = run_dir / "document.json"
    static_path = run_dir / "static-findings.jsonl"
    symbols_path = run_dir / "symbols.json"
    run([sys.executable, str(scripts / "extract_draft.py"), str(snapshot_path), "--output", str(document_path)])
    run([sys.executable, str(scripts / "lint_draft.py"), str(document_path), "--findings", str(static_path), "--symbols", str(symbols_path)])
    run([
        sys.executable, str(scripts / "make_chunks.py"), str(document_path), "--run-dir", str(run_dir),
        "--findings", str(static_path), "--symbols", str(symbols_path),
        "--min-words", str(args.min_words), "--target-words", str(args.target_words),
        "--max-words", str(args.max_words), "--context-words", str(args.context_words),
    ])
    document = read_json(document_path)
    chunks = sum(1 for line in (run_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
    required_lanes = sorted(path.stem for path in (run_dir / "lane-packets").glob("*.md"))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": "0.4.0",
        "run_id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "draft_path": str(snapshot_path),
        "original_draft_path": str(draft),
        "draft_sha256": document.get("input_sha256"),
        "source_snapshot": {
            "path": str(snapshot_path),
            "sha256": document.get("input_sha256"),
            "frozen_at": utc_now(),
        },
        "input_format": document.get("input_format"),
        "tracked_change_view": document.get("tracked_change_view"),
        "status": "initialized",
        "output_mode": "report_only",
        "review_depth": args.review_depth,
        "publication": {
            "visible_output_path": str(draft.with_name(f"{draft.stem} — Proofread.md")),
            "provenance_required": True,
            "collision_policy": "preserve_non_codex_and_fall_back_to_codex_named_report",
        },
        "chunk_policy": {
            "min_words": args.min_words,
            "target_words": args.target_words,
            "max_words": args.max_words,
            "context_words": args.context_words,
        },
        "required_lanes": required_lanes,
        "recall_required": True,
        "rejection_audit_required": True,
        "challenger_reports": [],
        "counts": {"chunks": chunks, "blocks": document.get("statistics", {}).get("reviewable_block_count", 0),
                   "notes": document.get("statistics", {}).get("note_count", 0)},
        "limitations": document.get("limitations", []),
    }
    write_json(run_dir / "run-manifest.json", manifest)
    for name in EMPTY_FILES:
        (run_dir / name).write_text("", encoding="utf-8")
    (run_dir / "report.md").write_text("", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "chunks": chunks, "draft_sha256": manifest["draft_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
