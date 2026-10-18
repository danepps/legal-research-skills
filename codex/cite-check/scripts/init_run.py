#!/usr/bin/env python3
"""Initialize a resumable cite-check run and perform deterministic extraction."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from extract_cites import extract_document
from prepare_units import build_prepared_units


LEDGERS = (
    "citation-units.jsonl",
    "source-ledger.jsonl",
    "quote-checks.jsonl",
    "verdicts.jsonl",
    "verifier-audit.jsonl",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scope", choices=("focused", "standard", "deep"), default="standard")
    parser.add_argument(
        "--publication-policy",
        choices=("matched_pair", "markdown_only", "docx_only"),
        default="markdown_only",
    )
    parser.add_argument("--min-quote-words", type=int, default=8)
    parser.add_argument("--footnotes", nargs="+", help="Focused footnote numbers or inclusive ranges")
    args = parser.parse_args()
    if not args.draft.is_file():
        parser.error(f"draft not found: {args.draft}")
    args.run_dir.mkdir(parents=True, exist_ok=False)
    snapshot = args.run_dir / f"source-snapshot{args.draft.suffix}"
    shutil.copyfile(args.draft, snapshot)
    snapshot.chmod(0o444)
    extraction = extract_document(snapshot, args.min_quote_words)
    (args.run_dir / "extraction.json").write_text(
        json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    selected_footnotes: set[int] | None = None
    if args.footnotes:
        selected_footnotes = set()
        for token in args.footnotes:
            if "-" in token:
                lower, upper = (int(value) for value in token.split("-", 1))
                if lower > upper:
                    parser.error(f"invalid descending footnote range: {token}")
                selected_footnotes.update(range(lower, upper + 1))
            else:
                selected_footnotes.add(int(token))
    prepared = build_prepared_units(extraction, selected_footnotes)
    (args.run_dir / "prepared-units.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in prepared),
        encoding="utf-8",
    )
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": 3,
        "draft_path": str(snapshot.resolve()),
        "original_draft_path": str(args.draft.resolve()),
        "draft_sha256": extraction["input_sha256"],
        "scope": args.scope,
        "publication_policy": args.publication_policy,
        "selected_footnotes": sorted(selected_footnotes) if selected_footnotes else None,
        "created_at": now,
        "updated_at": now,
        "status": "initialized",
        "counts": {"prepared_units": len(prepared)},
    }
    (args.run_dir / "run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in LEDGERS:
        (args.run_dir / name).touch()
    print(str(args.run_dir.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
