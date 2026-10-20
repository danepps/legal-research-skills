#!/usr/bin/env python3
"""Save content-keyed findings or compare two cite-check snapshots (offline).

Create: findings_diff.py --run-dir RUN --output RUN/findings.json
Compare: findings_diff.py PREVIOUS.json CURRENT.json [--json] [--output FILE]
Numbering and run-local IDs never form part of a finding key. Duplicate occurrences
are retained together. An incomplete/narrower rerun cannot silently resolve issues.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def norm(value):
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold()).strip()


def without_note_number(value):
    return re.sub(r"\b(supra|infra)\s+notes?\s+\d+(?:\s*[-–,]\s*\d+)*", r"\1 note", value or "", flags=re.I)


def key_of(item):
    # Recompute; trusting a stale caller-supplied key would hide content changes.
    kind = item.get("kind", "")
    if kind == "quote":
        fields = [kind, item.get("quote"), item.get("source"), item.get("verdict")]
    elif kind == "form":
        fields = [kind, without_note_number(item.get("find")), item.get("source"), item.get("problem")]
    elif kind in {"existence", "history", "treatment", "secondary"}:
        fields = [kind, item.get("cite") or item.get("source"), item.get("verdict"), item.get("problem")]
    else:
        fields = [kind, item.get("source"), item.get("quote"), without_note_number(item.get("find")), item.get("verdict"), item.get("problem")]
    return hashlib.sha256(json.dumps([norm(v) for v in fields], ensure_ascii=False).encode()).hexdigest()


def index_items(items):
    groups = {}
    for item in items:
        key = key_of(item)
        if key not in groups:
            groups[key] = dict(item, key=key, occurrences=[])
        groups[key]["occurrences"].append({k: item.get(k) for k in ("footnote", "note_id", "paragraph_number", "unit_id")})
    return groups


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def snapshot(run):
    manifest = json.loads((run / "run-manifest.json").read_text())
    units = {u["unit_id"]: u for u in read_rows(run / "citation-units.jsonl")}
    sources = {s["source_id"]: s for s in read_rows(run / "source-ledger.jsonl")}
    quotes = {}
    for check in read_rows(run / "quote-checks.jsonl"):
        bucket = quotes.setdefault(check["unit_id"], [])
        if check["quote"] not in bucket:
            bucket.append(check["quote"])
    items = []
    for verdict in read_rows(run / "verdicts.jsonl"):
        if verdict["status"] not in {"mismatch", "partial", "unverified"}:
            continue
        unit = units[verdict["unit_id"]]
        source = sources[unit["source_id"]]["canonical_citation"]
        items.append({"kind": "quote" if unit["unit_id"] in quotes else "citation",
                      "quote": "\n".join(sorted(quotes.get(unit["unit_id"], []))), "source": source, "cite": source,
                      "verdict": verdict["category"], "find": verdict.get("draft_find_string"),
                      "problem": verdict["category"], "label": verdict["suggested_action"],
                      "unit_id": unit["unit_id"], "footnote": unit.get("footnote_number"),
                      "note_id": unit.get("note_id"), "paragraph_number": unit.get("paragraph_number")})
    reviews = run / "case-review.jsonl"
    if reviews.exists():
        for row in read_rows(reviews):
            for finding in row.get("findings", []):
                unit = units[finding["unit_id"]]
                source = sources[row["source_id"]]["canonical_citation"]
                items.append({**finding, "source": source, "cite": source,
                              "footnote": unit.get("footnote_number"), "note_id": unit.get("note_id"),
                              "paragraph_number": unit.get("paragraph_number")})
    for item in items:
        item["key"] = key_of(item)
    return {"schema_version": 1, "snapshotSha256": manifest["draft_sha256"],
            "date": manifest.get("created_at"), "scope": manifest["scope"],
            "coverage_complete": manifest.get("completion_target", manifest.get("status")) == "complete"
                and manifest["scope"] in {"standard", "deep"},
            "items": items}


def diff(previous, current):
    before, after = index_items(previous["items"]), index_items(current["items"])
    absent = [before[k] for k in before.keys() - after.keys()]
    comparable = previous.get("coverage_complete") is True and current.get("coverage_complete") is True
    return {"new": [after[k] for k in sorted(after.keys() - before.keys())],
            "still_open": [after[k] for k in sorted(after.keys() & before.keys())],
            "resolved": sorted(absent, key=lambda r: r["key"]) if comparable else [],
            "not_rechecked": [] if comparable else sorted(absent, key=lambda r: r["key"]),
            "renumbered": [after[k] for k in sorted(after.keys() & before.keys())
                           if [o.get("footnote") for o in before[k]["occurrences"]] != [o.get("footnote") for o in after[k]["occurrences"]]]}


def render(previous, current, changes):
    lines = ["## Since the last report", "",
             f"{len(changes['new'])} new, {len(changes['still_open'])} still open, {len(changes['resolved'])} resolved (no longer reported), {len(changes['not_rechecked'])} not rechecked.",
             "Identity uses finding content, never footnote numbers. Resolved means absent from a comparable complete review, not independent proof of a correction.", ""]
    for field, heading in (("new", "New"), ("still_open", "Still open"), ("resolved", "Resolved"), ("not_rechecked", "Not rechecked / coverage changed")):
        lines += [f"### {heading}", ""]
        for row in changes[field]:
            locations = [f"n.{o['footnote']}" if o.get("footnote") is not None else o.get("note_id") or f"paragraph {o.get('paragraph_number')}" for o in row["occurrences"]]
            lines.append(f"- {', '.join(locations)}: {row.get('label') or row.get('problem') or row.get('verdict')} [{row['key'][:12]}]")
        if not changes[field]:
            lines.append("- none")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.run_dir:
        if args.files:
            parser.error("use --run-dir or two findings files, not both")
        text = json.dumps(snapshot(args.run_dir), ensure_ascii=False, indent=2) + "\n"
    else:
        if len(args.files) != 2:
            parser.error("supply PREVIOUS.json CURRENT.json")
        previous, current = [json.loads(p.read_text()) for p in args.files]
        changes = diff(previous, current)
        text = json.dumps(changes, ensure_ascii=False, indent=2) + "\n" if args.json else render(previous, current, changes)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
