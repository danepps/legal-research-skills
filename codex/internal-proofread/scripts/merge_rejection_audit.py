#!/usr/bin/env python3
"""Validate and merge rejection-audit packet results into the canonical ledger."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from common import read_json, read_jsonl, write_jsonl
from replacements import bind_audit, clear, without_replacements


VALID = {"confirmed_rejection", "reopen", "revised"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    manifest = read_json(run_dir / "run-manifest.json")
    replacements = manifest.get("replacements", False)
    source_hash = str(manifest.get("draft_sha256") or "")
    packets = read_jsonl(run_dir / "rejection-packets.jsonl")
    expected = [finding_id for packet in packets for finding_id in packet.get("finding_ids", [])]
    if len(expected) != len(set(expected)):
        raise SystemExit("rejection packet manifest contains duplicate finding IDs")

    rows = []
    for packet in packets:
        packet_id = str(packet.get("packet_id"))
        path = run_dir / "rejection-results" / f"{packet_id}.jsonl"
        if not path.is_file():
            raise SystemExit(f"missing rejection result: {path}")
        rows.extend(read_jsonl(path))
    by_id = {}
    for row in rows:
        finding_id = row.get("finding_id")
        if finding_id in by_id:
            raise SystemExit(f"duplicate rejection audit row: {finding_id}")
        if finding_id not in set(expected):
            raise SystemExit(f"unexpected rejection audit row: {finding_id}")
        if row.get("source_sha256") != source_hash:
            raise SystemExit(f"stale rejection audit row: {finding_id}")
        if row.get("rejection_status") not in VALID:
            raise SystemExit(f"invalid rejection status: {finding_id}")
        if not str(row.get("rationale", "")).strip():
            raise SystemExit(f"missing rejection rationale: {finding_id}")
        by_id[finding_id] = row
    missing = [finding_id for finding_id in expected if finding_id not in by_id]
    if missing:
        raise SystemExit(f"missing rejection audit rows: {', '.join(missing[:10])}")

    ordered = [by_id[finding_id] for finding_id in expected]
    if replacements:
        findings = read_jsonl(run_dir / "findings.jsonl")
        document = read_json(run_dir / "document.json")
        blocks = {row.get("block_id"): row for row in document.get("blocks", []) + document.get("notes", [])}
        finding_by_id = {row.get("finding_id"): row for row in findings}
        ordered = [bind_audit(row, finding_by_id.get(row["finding_id"], {}), blocks) for row in ordered]
        withdraw = {row["finding_id"] for row in ordered if row.get("rejection_status") == "confirmed_rejection"
                    or any(key in row for key in ("revised_suggestion", "revised_excerpt", "revised_location", "revised_severity", "revised_replacement"))}
        for name, records in (("findings.jsonl", findings), ("dispositions.jsonl", read_jsonl(run_dir / "dispositions.jsonl"))):
            updated = [clear(dict(row)) if row.get("finding_id") in withdraw else row for row in records]
            if updated != records:
                write_jsonl(run_dir / name, updated)
    else:
        ordered = without_replacements(ordered)
    write_jsonl(run_dir / "rejection-audit.jsonl", ordered)
    counts = Counter(row["rejection_status"] for row in ordered)
    print(f"merged {len(ordered)} rejection audits: {dict(sorted(counts.items()))}")
    if counts.get("reopen", 0) or counts.get("revised", 0):
        print("lead action required: update every reopened or revised disposition before readiness validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
