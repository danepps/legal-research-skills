#!/usr/bin/env python3
"""Initialize a resumable cite-check run and perform deterministic extraction."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from extract_cites import extract_document, sha256
from prepare_units import build_prepared_units
from prepare_run_options import parse_footnotes, resolved_selection


LEDGERS = (
    "citation-units.jsonl",
    "source-ledger.jsonl",
    "quote-checks.jsonl",
    "verdicts.jsonl",
    "verifier-audit.jsonl",
    "case-review.jsonl",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scope", choices=("focused", "standard", "deep"))
    parser.add_argument("--options", type=Path, help="resolved prepare_run_options.py preview for this draft")
    parser.add_argument(
        "--publication-policy",
        choices=("matched_pair", "markdown_only", "docx_only"),
        default="markdown_only",
    )
    parser.add_argument("--support", action="store_true", default=None, help="opt in to unquoted proposition-support review")
    parser.add_argument("--support-scope", choices=("pincited", "all"))
    parser.add_argument("--min-quote-words", type=int)
    parser.add_argument("--footnotes", nargs="+", help="Focused footnote numbers or inclusive ranges")
    args = parser.parse_args()
    if not args.draft.is_file():
        parser.error(f"draft not found: {args.draft}")
    options = None
    if args.options:
        if any(value is not None for value in (args.scope, args.support, args.support_scope, args.footnotes, args.min_quote_words)):
            parser.error("--options cannot be combined with scope/support/footnote/quotation overrides")
        try:
            options = json.loads(args.options.read_text(encoding="utf-8"))
            selected = resolved_selection(options, sha256(args.draft))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
        args.scope = selected["depth"]
        args.footnotes = [str(n) for n in selected["footnotes"]] if selected["footnotes"] else None
        args.support = selected["support"] != "off"
        args.support_scope = selected["support"] if args.support else "pincited"
        args.min_quote_words = options["min_quote_words"]
    args.scope = args.scope or "standard"
    args.support_scope = args.support_scope or "pincited"
    args.min_quote_words = args.min_quote_words if args.min_quote_words is not None else 8
    if args.min_quote_words < 1:
        parser.error("quotation threshold must be positive")
    args.run_dir.mkdir(parents=True, exist_ok=False)
    snapshot = args.run_dir / f"source-snapshot{args.draft.suffix}"
    shutil.copyfile(args.draft, snapshot)
    snapshot.chmod(0o444)
    extraction = extract_document(snapshot, args.min_quote_words)
    if options and extraction["input_sha256"] != options["draft_sha256"]:
        parser.error("draft changed while creating the snapshot; regenerate the preview")
    (args.run_dir / "extraction.json").write_text(
        json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    selected_footnotes: set[int] | None = None
    if args.footnotes:
        try:
            available = {n["number"] for n in extraction.get("footnotes", []) if isinstance(n.get("number"), int)}
            selected_footnotes = set(parse_footnotes(args.footnotes, available))
        except ValueError as exc:
            parser.error(str(exc))
    prepared = build_prepared_units(extraction, selected_footnotes)
    (args.run_dir / "prepared-units.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in prepared),
        encoding="utf-8",
    )
    if args.support:
        from support_screen import screen_extraction
        (args.run_dir / "citation-screening.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in screen_extraction(extraction)
                    if selected_footnotes is None or row.get("footnote_number") in selected_footnotes), encoding="utf-8")
        (args.run_dir / "support-units.jsonl").touch()
    now = datetime.now(timezone.utc).isoformat()
    coverage = [
        {"footnote_number": row["number"], "note_id": row.get("note_id"), "status": "pending", "unit_ids": []}
        for row in extraction.get("footnotes", [])
        if selected_footnotes is None or row["number"] in selected_footnotes
    ]
    (args.run_dir / "footnote-coverage.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in coverage), encoding="utf-8"
    )
    (args.run_dir / "body-coverage.jsonl").write_text(
        "".join(json.dumps({"paragraph_number": number, "status": "pending", "unit_ids": []}) + "\n"
                for number in range(1, len(extraction["paragraphs"]) + 1)
                if selected_footnotes is None), encoding="utf-8",
    )
    manifest = {
        "schema_version": 7 if args.support else 6,
        "support_pass": {"enabled": True, "scope": args.support_scope} if args.support else {"enabled": False},
        "draft_path": str(snapshot.resolve()),
        "original_draft_path": str(args.draft.resolve()),
        "draft_sha256": extraction["input_sha256"],
        "scope": "focused" if selected_footnotes is not None else args.scope,
        "review_depth": "deep" if args.scope == "deep" else "standard",
        "publication_policy": args.publication_policy,
        "selected_footnotes": sorted(selected_footnotes) if selected_footnotes else None,
        "created_at": now,
        "updated_at": now,
        "status": "initialized",
        "counts": {"prepared_units": len(prepared)},
    }
    if options:
        options_path = args.run_dir / "run-options.json"
        options_path.write_text(json.dumps(options, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["run_options_sha256"] = sha256(options_path)
        if "library_access" in options:
            manifest["library_access"] = options["library_access"]
    (args.run_dir / "run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name in LEDGERS:
        (args.run_dir / name).touch()
    for issue in extraction.get("blocking_issues", []):
        print(f"BLOCKED: {issue}", file=sys.stderr)
    print(str(args.run_dir.resolve()))
    return 1 if extraction.get("blocking_issues") else 0


if __name__ == "__main__":
    raise SystemExit(main())

