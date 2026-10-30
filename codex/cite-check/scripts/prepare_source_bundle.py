#!/usr/bin/env python3
"""Prepare one source's draft context and cache references for a fresh-context worker.

Does not read cached source text, copy the conversation, or include prior verdicts.
Run after citation resolution; the lead still owns attribution and final judgments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SOURCE_FIELDS = (
    "source_id", "source_type", "canonical_citation", "status", "verification_basis",
    "url", "doi", "zotero_item_key", "source_path", "source_sha256", "retrieval_notes",
    "reason", "unlock_path", "pagination_convention", "first_page", "versions",
    "identifiers", "retrieval_attempts", "library_id",
)
SIBLING_FIELDS = (
    "unit_id", "source_id", "draft_citation_text", "resolved_source_label", "pincite",
    "signal", "xref_status", "antecedent_unit_id",
)


def rows(run: Path, name: str, optional: bool = False) -> list[dict]:
    path = run / name
    if optional and not path.exists():
        return []
    result = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in result):
        raise ValueError(f"{name} must contain JSON objects")
    return result


def location(unit: dict, note_numbers: dict) -> tuple:
    if unit.get("location") == "body":
        value = unit.get("paragraph_number")
        kind = "body"
    else:
        number = unit.get("footnote_number")
        if number is None:
            number = note_numbers.get(unit.get("note_id"))
        value = ("number", number) if number is not None else (
            ("note_id", unit["note_id"]) if unit.get("note_id") else None)
        kind = "footnote"
    # Missing locations must never join all unlocated citations into one packet.
    return (kind, value) if value is not None else ("unit", unit.get("unit_id") or unit.get("prepared_unit_id"))


def build_bundle(run: Path, source_id: str) -> dict:
    run = run.resolve()
    units = rows(run, "citation-units.jsonl")
    sources = rows(run, "source-ledger.jsonl")
    all_prepared = rows(run, "prepared-units.jsonl", True)
    note_numbers = {}
    for unit in units + all_prepared:
        note, number = unit.get("note_id"), unit.get("footnote_number")
        if note and number is not None:
            if note in note_numbers and note_numbers[note] != number:
                raise ValueError("inconsistent note ID/number mapping")
            note_numbers[note] = number
    selected = [u for u in units if u.get("source_id") == source_id]
    source = [s for s in sources if s.get("source_id") == source_id]
    if len(source) > 1 or not selected:
        raise ValueError("source_id needs resolved citation units and at most one source record")
    ids = {u["unit_id"] for u in selected}
    homes = {location(u, note_numbers) for u in selected}
    siblings = [u for u in units if u["unit_id"] not in ids and location(u, note_numbers) in homes]
    checks = [q for q in rows(run, "quote-checks.jsonl", True) if q.get("unit_id") in ids]
    prepared_ids = {p for u in selected for p in u.get("prepared_unit_ids", [])}
    prepared_ids.update(q["prepared_unit_id"] for q in checks if q.get("prepared_unit_id"))
    def relevant_quote(p):
        note_home = location(dict(p, location="footnote"), note_numbers)
        return (p.get("prepared_unit_id") in prepared_ids or location(p, note_numbers) in homes
                or note_home in homes)
    prepared = [p for p in all_prepared if relevant_quote(p)]
    if not prepared_ids.issubset({p["prepared_unit_id"] for p in prepared}):
        raise ValueError("a linked prepared quotation is missing")
    relevant_sources = {source_id} | {u.get("source_id") for u in siblings}
    relevant_sources.update(q.get("source_id") for q in checks)
    return {
        "run_dir": str(run), "source_id": source_id,
        "source_record_available": bool(source),
        "path_base": "Resolve relative source paths against run_dir; read only needed excerpts.",
        "citation_units": selected,
        "prepared_quotes": prepared,
        "quote_scope": "Quotes at the same location are context, not inferred attribution. Use explicit links or resolve attribution from the complete footnote.",
        "support_units": [s for s in rows(run, "support-units.jsonl", True) if s.get("unit_id") in ids],
        "sibling_citations": [{k: u[k] for k in SIBLING_FIELDS if k in u} for u in siblings],
        "sources": [{k: s[k] for k in SOURCE_FIELDS if k in s}
                    for s in sources if s.get("source_id") in relevant_sources],
        "quote_cache_refs": [{k: q[k] for k in
                              ("unit_id", "prepared_unit_id", "source_id", "source_path", "source_sha256")
                              if k in q} for q in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("source_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        # A packet must not overwrite a ledger, draft, or cached source.
        packet_dir = args.run_dir.resolve() / "source-bundles"
        output = args.output.resolve()
        if output.parent != packet_dir or output.suffix != ".json":
            raise ValueError("output must be a .json file directly inside RUN_DIR/source-bundles/")
        bundle = build_bundle(args.run_dir, args.source_id)
        packet_dir.mkdir(exist_ok=True)
        data = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
        output.write_text(data, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"path": str(output), "bytes": len(data.encode("utf-8")),
                      "citation_units": len(bundle["citation_units"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
