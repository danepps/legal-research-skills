#!/usr/bin/env python3
"""Offline source-folder matching for an initialized Codex cite-check run.

local_lookup.py RUN_DIR [--folder DIR ...] [--project DIR] [--apply]
Reads resolved source-ledger rows. Writes local-lookup.json and content-hashed
text under cached-sources/local/. --apply attaches only unambiguous matches to
source_path/source_sha256; it never assigns quotation or citation verdicts.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from local_sources import (digest, discover_folders, index_folders, match, protect_output,
                           version_evidence, words, write_json, editions, extract_chosen, public_candidate)
from source_options import validate_plan

KINDS = {"article", "book", "other", "internet", "secondary", "scholarship"}
ARTICLE = re.compile(r"^(?P<authors>.+?),\s+(?P<title>.+?),\s+(?P<volume>\d+)\s+"
                     r"(?P<journal>[A-Z][A-Za-z.&'’\-\s]+?)\s+(?P<first>\d+)"
                     r"(?:,\s*[\d\s–-]+)?\s*\((?P<year>(?:1[6-9]|20)\d{2})\)")
BOOK = re.compile(r"^(?P<authors>.+?),\s+(?P<title>.+?)(?:\s+\d+(?:[–-]\d+)?)?"
                  r"\s*\([^)]*?\b(?P<year>(?:1[6-9]|20)\d{2})\)")


def parse_citation(cite):
    cite = re.sub(r"^(?:(?:See|see|also|Cf\.|cf\.|But|but)\s+)+", "", cite.strip()).rstrip(".;")
    parsed = ARTICLE.match(cite) or BOOK.match(cite)
    fields = {"title": "", "authors": "", "lastNames": [], "journal": "", "volume": "", "first": "", "year": ""}
    if parsed:
        fields.update(parsed.groupdict())
        fields["pattern"] = "article" if fields["journal"] else "book"
        fields["edition"] = next(iter(editions(cite)), "")
        fields["title"] = fields["title"].split(", in ", 1)[0]
        authors = re.sub(r"\s+et\s+al\.?", "", fields["authors"])
        fields["lastNames"] = [words(n)[-1] for n in re.split(r"\s*(?:&|\band\b|,)\s*", authors) if words(n)]
    return fields


def read_rows(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("source ledger must contain JSON objects")
    ids = [r.get("source_id") for r in rows]
    if not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("source ledger requires unique source IDs")
    return rows


def build_lookup(sources, folders, cache, *, exclude=()):
    entries, errors = index_folders(folders, cache, exclude=exclude)
    records = {}
    for row in sources:
        if row.get("source_type") not in KINDS:
            continue
        fields = parse_citation(row.get("canonical_citation", ""))
        chosen, candidates = match(fields, entries)
        chosen = extract_chosen(chosen, cache)
        result = {"matched": bool(chosen), "canonical_citation": row.get("canonical_citation", ""),
                  "source_type": row["source_type"], "candidates": [public_candidate(c) for c in candidates]}
        if chosen:
            version = version_evidence(fields, chosen)
            result.update(source_path=chosen["textPath"], source_sha256=chosen["textSha256"],
                          local_copy={"path": chosen["filePath"], "sha256": chosen["fileSha256"],
                                      "filename": chosen["fileName"], "text_pages": chosen["textPages"],
                                      "identity": chosen["identity"]["evidence"], "version": version})
        else:
            result["reason"] = "ambiguous candidates" if len(candidates) > 1 else "no strong title/byline match"
        records[row["source_id"]] = result
    count = sum(r["matched"] for r in records.values())
    return {"schema_version": 1, "folders": list(map(str, folders)), "folder_errors": errors,
            "files": entries, "sources": records,
            "stats": {"files_indexed": len(entries), "matched": count, "unmatched": len(records) - count,
                      "cache_reused": sum(e["cacheReused"] for e in entries),
                      "unreadable": sorted(set([e["fileName"] for e in entries if not e["readable"]] +
                          [c["fileName"] for rec in records.values() for c in rec["candidates"] if c.get("reason")]))}}


def disclosure_lines(lookup):
    stats = lookup["stats"]
    lines = [f"Local copies: {stats['matched']} sources matched; {stats['unmatched']} unmatched; {stats['files_indexed']} files indexed."]
    for filename in stats["unreadable"]:
        lines.append(f"Unreadable local copy: {filename}.")
    for error in lookup["folder_errors"]:
        lines.append(f"Source folder: {error['folder']}; {error['reason']}.")
    for sid, rec in lookup["sources"].items():
        if rec["matched"]:
            copy = rec["local_copy"]
            lines.append(f"Local proposal {sid}: {copy['filename']}; {copy['version']['note']}")
            if not copy["version"]["pinciteEligible"]:
                lines.append(f"Local copy {sid}: {copy['version']['pinciteReason']}")
        if rec["candidates"] and (not rec["matched"] or len(rec["candidates"]) > 1):
            lines.append(f"Local candidates {sid}: " + "; ".join(c.get("relativePath", c["fileName"]) + (": " + c["reason"] if c.get("reason") else "") for c in rec["candidates"]) +
                         ("; unique published proposal selected." if rec["matched"] else "; no match selected."))
    return lines


def apply_lookup(run, manifest, sources, lookup):
    updated = [dict(source) for source in sources]
    for source in updated:
        result = lookup["sources"].get(source["source_id"], {})
        if not result.get("matched"):
            if source.get("source_origin") == "local_folder":
                raise ValueError("a prior local match is now missing/ambiguous; reconcile it before applying a new lookup")
            continue
        if source.get("source_path") and source.get("source_origin") != "local_folder":
            raise ValueError("run the folder pass before other retrieval; refusing to replace existing source evidence")
        source.update({key: result[key] for key in ("source_path", "source_sha256", "local_copy")})
        source.update(source_origin="local_folder", status="retrieved", verification_basis="local_library_full_text",
                      local_identity_review={"status": "pending"}, pagination_convention="unknown", retrieval_notes=result["local_copy"]["version"]["note"])
    target = run / "source-ledger.jsonl"
    if target.is_symlink():
        raise ValueError("refusing symlink source ledger")
    for path in (run / "run-manifest.json", run / "local-lookup.json"):
        if path.is_symlink():
            raise ValueError("refusing symlink run output")
    # Validate every replacement before changing the active report or ledger.
    write_json(run / "local-lookup.json", lookup)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in updated), encoding="utf-8")
    sources[:] = updated
    manifest["local_source_version"] = 1
    manifest["local_lookup_sha256"] = digest(run / "local-lookup.json")
    write_json(run / "run-manifest.json", manifest)


def quote_without_pin(verdict, source):
    pin = verdict.get("pincite_verification") or {}
    return (source.get("source_origin") == "local_folder" and
            (source.get("local_copy") or {}).get("version", {}).get("pinciteEligible") is False and
            verdict.get("category") == "verified_quote" and pin.get("status") == "not_judged" and
            pin.get("confirmed") is False and isinstance(pin.get("reason"), str) and bool(pin["reason"].strip()))


def validate_local_sources(run, manifest, sources, units, verdicts, report):
    """Require copy provenance, intact text, version limits, and report disclosure."""
    errors = []
    local = [s for s in sources if s.get("source_origin") == "local_folder"]
    if manifest.get("local_source_version") != 1 and not local:
        return errors
    try:
        path = run / "local-lookup.json"
        if digest(path) != manifest.get("local_lookup_sha256"):
            errors.append("local lookup hash differs from the applied report")
        lookup = json.loads(path.read_text(encoding="utf-8"))
        for line in disclosure_lines(lookup):
            if line not in report:
                errors.append("report.md omits local-copy disclosure: " + line)
        by_id = {s["source_id"]: s for s in local}
        for sid, rec in lookup["sources"].items():
            if rec["matched"] and sid not in by_id and not any(s.get("source_id") == sid and (s.get("local_identity_review") or {}).get("status") == "rejected" and (s.get("local_identity_review") or {}).get("reason") for s in sources):
                errors.append(f"{sid}: matched local copy missing from source ledger")
        for source in local:
            sid = source["source_id"]
            rec = lookup["sources"].get(sid, {})
            if not rec.get("matched") or any(source.get(k) != rec.get(k) for k in (
                    "canonical_citation", "source_type", "source_path", "source_sha256", "local_copy")):
                errors.append(f"{sid}: local source does not match lookup provenance")
                continue
            text_path = (run / source["source_path"]).resolve()
            if run.resolve() not in text_path.parents or digest(text_path) != source["source_sha256"]:
                errors.append(f"{sid}: local text cache missing, outside run, or changed")
            review = source.get("local_identity_review") or {}
            ids = {u["unit_id"] for u in units if u.get("source_id") == sid}
            if any(v.get("unit_id") in ids for v in verdicts) and not (
                    review.get("status") == "confirmed" and review.get("locator") and review.get("reason")):
                errors.append(f"{sid}: local identity must be confirmed from the first content page before reliance")
            copy = source["local_copy"]
            if digest(copy["path"]) != copy["sha256"]:
                errors.append(f"{sid}: original local copy changed")
            if not copy["version"]["pinciteEligible"]:
                ids = {u["unit_id"] for u in units if u.get("source_id") == sid and u.get("pincite")}
                for v in verdicts:
                    if v.get("unit_id") not in ids:
                        continue
                    pin = v.get("pincite_verification") or {}
                    if (v.get("category") in {"verified_pincite", "pincite_error"} or pin.get("confirmed") or
                            pin.get("corrected_page") or v.get("corrected_pincite") or
                            (v.get("status") == "verified" and not quote_without_pin(v, source))):
                        errors.append(f"{sid}: local copy cannot establish cited-version printed pincites; keep pin not judged")

    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"local-copy validation: {exc}")
    return errors


def record_identity_review(run, source_id, status, locator, reason):
    """Persist the agent's inspected outcome without altering the proposal cache."""
    if status not in {"confirmed", "rejected"} or not locator or not reason:
        raise ValueError("identity review needs status, inspected page locator and reason")
    lookup = json.loads((run / "local-lookup.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "run-manifest.json").read_text(encoding="utf-8"))
    if digest(run / "local-lookup.json") != manifest.get("local_lookup_sha256"):
        raise ValueError("local proposal changed before identity review")
    rec = lookup["sources"].get(source_id, {})
    if not rec.get("matched"):
        raise ValueError("identity review requires a proposed local copy")
    rows = read_rows(run / "source-ledger.jsonl")
    source = next((s for s in rows if s["source_id"] == source_id), None)
    if source is None or source.get("source_origin") != "local_folder":
        raise ValueError("review requires the active proposed local copy")
    if digest(rec["local_copy"]["path"]) != rec["local_copy"]["sha256"]:
        raise ValueError("local copy changed before identity review")
    source["local_identity_review"] = dict(status=status, locator=locator, reason=reason,
                                          sha256=rec["local_copy"]["sha256"])
    if status == "rejected":
        for key in ("source_path", "source_sha256"):
            source.pop(key, None)
        source.update(source_origin="local_folder_rejected", status="unavailable", verification_basis="unavailable",
                      retrieval_notes="Local proposal rejected; try the selected Zotero library, then the web.")
    target = run / "source-ledger.jsonl"
    protect_output(target, [])
    target.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--folder", action="append", default=[])
    parser.add_argument("--project", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--review-source")
    parser.add_argument("--identity-status", choices=["confirmed", "rejected"])
    parser.add_argument("--identity-locator")
    parser.add_argument("--identity-reason")
    args = parser.parse_args()
    try:
        run = args.run_dir.expanduser().resolve()
        if args.review_source:
            if args.apply or args.folder or args.project:
                raise ValueError("identity review is separate from indexing")
            record_identity_review(run, args.review_source, args.identity_status, args.identity_locator, args.identity_reason)
            print("Local identity outcome recorded; rejected proposals fall through to selected Zotero then web.")
            return 0
        if any((args.identity_status, args.identity_locator, args.identity_reason)):
            raise ValueError("identity outcome fields need --review-source")
        manifest = json.loads((run / "run-manifest.json").read_text(encoding="utf-8"))
        draft = manifest.get("original_draft_path") or manifest["draft_path"]
        if "source_access" in manifest:
            choice = manifest["source_access"]
            validate_plan(choice)
            if args.folder or args.project:
                raise ValueError("folder choices are frozen in run options; regenerate options/run to change them")
            folders, origin = [Path(p) for p in choice["folder_paths"]], choice["folder_origin"]
        else:
            folders, origin = discover_folders(draft, args.project, args.folder)
        protect_output(run, folders)
        for target in (run / "local-lookup.json", run / "run-manifest.json", run / "source-ledger.jsonl"):
            protect_output(target, folders)
        sources = read_rows(run / "source-ledger.jsonl")
        lookup = build_lookup(sources, folders, run / "cached-sources" / "local", exclude=[run, Path(draft).expanduser()])
        lookup["folder_origin"] = origin
        if args.apply:
            apply_lookup(run, manifest, sources, lookup)
        elif manifest.get("local_source_version"):
            raise ValueError("this run has an applied lookup; use --apply to refresh it without invalidating provenance")
        else:
            write_json(run / "local-lookup.json", lookup)
        print(json.dumps(lookup["stats"], ensure_ascii=False))
        print("\n".join(disclosure_lines(lookup)))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
