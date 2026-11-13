#!/usr/bin/env python3
"""Search unresolved quotations in reachable cached texts; never change verdicts.

Writes RUN_DIR/cache-recovery.json and cache-recovery.md. These are working
artifacts. Copy the generated coverage lines into Couldn't check. Matching words
are leads for attribution, version, alteration and pagination review, not clearance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from source_resolution import resolution_errors, recovery_lines
from verify_quotes import check_quote, file_sha256, normalize, page_spans

MATCHES = {"verbatim", "normalized", "altered"}
INPUTS = ("citation-units.jsonl", "source-ledger.jsonl", "prepared-units.jsonl",
          "quote-checks.jsonl", "verdicts.jsonl", "resolution-context.jsonl")
LOOKUP_STATES = {"record_no_attachment", "record_unreadable", "not_found", "unavailable", "not_assessed"}


def rows(run, name):
    path = run / name
    if not path.exists():
        return []
    result = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in result):
        raise ValueError(f"{name}: expected JSON objects")
    return result


def home(row, note_numbers=None):
    if row.get("location") == "body":
        return ("body", row.get("paragraph_number")) if row.get("paragraph_number") else None
    number = row.get("footnote_number")
    if number is None:
        number = (note_numbers or {}).get(row.get("note_id"))
    if number is not None:
        return ("note", number)
    return ("note_id", row["note_id"]) if row.get("note_id") else None


def source_state(run, source, selection):
    """Use observed files before lookup claims; never infer absence from no item key."""
    state = {"source_id": source["source_id"], "library_id": source.get("library_id"),
             "zotero_item_key": source.get("zotero_item_key")}
    is_library = bool(state["library_id"] or state["zotero_item_key"] or source.get("verification_basis") == "local_library_full_text")
    if (selection or {}).get("status") == "skipped" and is_library:
        return dict(state, status="skipped")
    if (selection or {}).get("status") == "selected" and is_library and state["library_id"] != selection.get("id"):
        return dict(state, status="not_selected")
    name = source.get("source_path")
    if name:
        path = (run / name).resolve()
        try:
            digest = file_sha256(path)
            if source.get("source_sha256") != digest:
                return dict(state, status="cache_hash_mismatch", source_path=str(path), source_sha256=digest)
            return dict(state, status="text_cached", source_path=str(path), source_sha256=digest)
        except OSError:
            return dict(state, status="cache_unreadable", source_path=str(path))
    if (selection or {}).get("status") == "skipped":
        return dict(state, status="skipped")
    lookup = source.get("library_lookup") or {}
    status = lookup.get("status", "not_assessed")
    if status not in LOOKUP_STATES:
        raise ValueError(f"{source['source_id']}: invalid library_lookup status")
    if status != "not_assessed" and not str(lookup.get("evidence") or "").strip():
        raise ValueError(f"{source['source_id']}: library lookup needs evidence")
    if status in {"record_no_attachment", "record_unreadable"} and not (state["library_id"] and state["zotero_item_key"]):
        raise ValueError(f"{source['source_id']}: record status needs library ID and item key")
    return dict(state, status=status, lookup_evidence=lookup.get("evidence"))


def build_recovery(run):
    run = Path(run).resolve()
    data = {name: rows(run, name) for name in INPUTS}
    units, sources = data[INPUTS[0]], data[INPUTS[1]]
    context = data["resolution-context.jsonl"]
    all_units = units + context
    if len({u["unit_id"] for u in all_units}) != len(all_units):
        raise ValueError("duplicate citation/context unit IDs")
    note_numbers = {}
    for row in all_units + data["prepared-units.jsonl"]:
        note, number = row.get("note_id"), row.get("footnote_number")
        if note and number is not None:
            if note in note_numbers and note_numbers[note] != number:
                raise ValueError("inconsistent note ID/number mapping")
            note_numbers[note] = number
    errors = resolution_errors(all_units, sources, data["verdicts.jsonl"])
    if errors:
        raise ValueError("; ".join(errors))
    manifest = json.loads((run / "run-manifest.json").read_text())
    selection = manifest.get("library_access", {}).get("selection")
    by_id = {u["unit_id"]: u for u in all_units}
    by_source = {s["source_id"]: s for s in sources}
    verdicts = {v["unit_id"]: v for v in data["verdicts.jsonl"]}
    states, files, results = {}, {}, []
    for quote in data["prepared-units.jsonl"]:
        pid = quote["prepared_unit_id"]
        linked = {u["unit_id"] for u in units if pid in u.get("prepared_unit_ids", [])}
        linked.update(c["unit_id"] for c in data["quote-checks.jsonl"] if c.get("prepared_unit_id") == pid)
        if len(linked) > 1:
            raise ValueError(f"{pid}: ambiguous citation-unit mapping")
        uid = next(iter(linked), None)
        if uid and uid not in by_id:
            raise ValueError(f"{pid}: unknown citation unit {uid}")
        # Verified and mismatch verdicts already have their ordinary match/audit gates.
        verdict = verdicts.get(uid, {})
        if uid and verdict.get("status") in {"verified", "mismatch", "not_applicable"} and verdict.get("category") != "not_found_in_sources_checked":
            continue
        location = home(by_id[uid], note_numbers) if uid else home(quote, note_numbers)
        pending = [u["unit_id"] for u in units if location is not None and home(u, note_numbers) == location]
        if uid:
            pending.append(uid)
        visited, candidate_ids = set(), set()
        while pending:
            current_id = pending.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            u = by_id[current_id]
            candidate_ids.add(u["source_id"])
            current_home = home(u, note_numbers)
            if current_home is not None:
                pending.extend(s["unit_id"] for s in all_units if home(s, note_numbers) == current_home and s["unit_id"] not in visited)
            target = (u.get("xref_recovery") or {}).get("candidate_unit_id") if u.get("xref_status") == "recovered" else u.get("antecedent_unit_id")
            if target in by_id:
                pending.append(target)
        attempts = []
        for sid in sorted(candidate_ids):
            if sid not in by_source:
                raise ValueError(f"{pid}: unknown source {sid}")
            if sid not in states:
                states[sid] = source_state(run, by_source[sid], selection)
            state = states[sid]
            attempt = dict(state)
            if state["status"] == "text_cached":
                path = state["source_path"]
                if path not in files:
                    try:
                        raw = Path(path).read_text(encoding="utf-8")
                        spans, marker = page_spans(raw)
                        views = {fold: normalize(raw, fold=fold, spans=spans) for fold in (False, True)}
                        views["dehyphenated"] = normalize(raw, fold=True, spans=spans, dehyphenate_line_breaks=True)
                        files[path] = (raw, views, marker)
                    except (UnicodeError, OSError):
                        files[path] = None
                if files[path] is None:
                    attempt["status"] = "cache_unreadable"
                else:
                    raw, views, marker = files[path]
                    match = check_quote(raw, views, marker, None, {"quote": quote["quote"]})
                    # Deliberately omit page fields: the sweep does not calibrate pagination.
                    attempt["match"] = {k: match[k] for k in ("status", "match_excerpt", "bracket_map", "warnings", "occurrences") if k in match}
            attempts.append(attempt)
        results.append({"prepared_unit_id": pid, "unit_id": uid,
                        "assigned_source_id": by_id[uid]["source_id"] if uid else None,
                        "attempts": attempts})
    return {"version": 1, "library_selection": selection,
            "input_sha256": {name: file_sha256(run / name) if (run / name).exists() else None for name in INPUTS},
            "results": results}


def coverage_lines(recovery):
    lines = []
    for row in recovery["results"]:
        details = []
        for a in row["attempts"]:
            tag = f"{a['source_id']}={a['status']}"
            if a.get("library_id") or a.get("zotero_item_key"):
                tag += f" ({a.get('library_id') or 'library unknown'}/{a.get('zotero_item_key') or 'item unknown'})"
            if a.get("match"):
                tag += f", searched={a['match']['status']}"
            details.append(tag)
        lines.append(f"Cache recovery {row['prepared_unit_id']} ({row['unit_id'] or 'unmapped'}): " + ("; ".join(details) or "no reachable source recorded") + ".")
    return lines


def validate_recovery(run, report):
    errors = []
    try:
        expected = build_recovery(run)
        actual = json.loads((run / "cache-recovery.json").read_text())
        if actual != expected:
            errors.append("cache-recovery.json is stale or inconsistent; regenerate after ledger/cache changes")
        reviews = rows(run, "cache-recovery-reviews.jsonl")
        for row in expected["results"]:
            for attempt in row["attempts"]:
                if attempt.get("status") == "cache_hash_mismatch":
                    errors.append(f"{attempt['source_id']}: reconcile changed cache hash before publication")
                if attempt.get("match", {}).get("status") not in MATCHES:
                    continue
                matching = [r for r in reviews if r.get("prepared_unit_id") == row["prepared_unit_id"]
                            and r.get("source_id") == attempt["source_id"]
                            and r.get("source_sha256") == attempt["source_sha256"]]
                if not any(r.get("disposition") in {"attribution_issue", "version_issue", "alteration_issue", "pagination_unresolved", "context_issue"}
                           and str(r.get("evidence") or "").strip() for r in matching):
                    errors.append(f"{row['prepared_unit_id']}/{attempt['source_id']}: cached match needs review or reconciled verdict")
        for line in coverage_lines(expected) + recovery_lines(rows(run, "citation-units.jsonl")):
            if line not in report:
                errors.append(f"report.md omits recovery coverage: {line}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"cache recovery: {exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        result = build_recovery(args.run_dir)
        (args.run_dir / "cache-recovery.json").write_text(json.dumps(result, indent=2) + "\n")
        lines = coverage_lines(result) + recovery_lines(rows(args.run_dir, "citation-units.jsonl"))
        (args.run_dir / "cache-recovery.md").write_text("\n".join(lines) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Recovery checked {len(result['results'])} unresolved quotation rows; verdicts unchanged.")


if __name__ == "__main__":
    main()
