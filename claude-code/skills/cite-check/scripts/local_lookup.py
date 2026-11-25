#!/usr/bin/env python3
"""Index local secondary sources before Zotero. No network or model calls.

local_lookup.py REPORT --secondary LEDGER [--support SUPPORT] [--cites CITES]
    [--folder DIR ...] [--draft DRAFT --project PROJECT] --cache-dir DIR
local_lookup.py REPORT --merge-zotero ZOTERO_REPORT
local_lookup.py REPORT --compact | --get KEY

The report becomes the single lookup for both origins after --merge-zotero.
"""
import argparse
import json
from pathlib import Path

import zotero_lookup as zotero
from local_sources import discover_folders, index_folders, match, protect_output, version_evidence, write_json, editions, extract_chosen, public_candidate
from source_options import validate_plan


def run(sources, folders, cache, *, exclude=()):
    files, errors = index_folders(folders, cache, exclude=exclude)
    report = {"origin": "local", "folders": list(map(str, folders)), "folderErrors": errors,
              "files": files, "sources": {}, "unmatched": [], "zoteroSearched": False}
    for source in sources:
        fields = zotero.parse_cite(source["cite"], source["kind"])
        fields["edition"] = next(iter(editions(source["cite"])), "")
        chosen, candidates = match(fields, files)
        chosen = extract_chosen(chosen, cache)
        row = dict(source, matched=False, origin="local", candidates=[public_candidate(e) for e in candidates])
        if chosen:
            proof = chosen["identity"]["evidence"][0]
            # Reuse Zotero's scoring on *text-derived* fields, never PDF metadata.
            data = {"title": proof["title"], "creators": [{"name": proof["byline"]}]}
            score = zotero.score_item(fields, zotero.content_words(fields["text"]), set(zotero.tokens(fields["text"])), data)
            version = version_evidence(fields, chosen)
            confirms = []
            for field, observed in (("year", version["observedYears"]), ("volume", version["observedVolumes"])):
                if fields.get(field) and observed and fields[field] not in observed:
                    confirms.append(f"confirm: draft {field} {fields[field]} vs local copy first-page labels {', '.join(observed)}; this may be a different version")
            row.update({k: v for k, v in chosen.items() if k not in {"firstPages", "readable", "cacheReused"}})
            row.update(matched=True, title=proof["title"], creators=[proof["byline"]], score=score,
                       citedFirstPage=fields["first"] if fields["pattern"] == "article" else "",
                       version=version, versionNote=version["note"], confirm=confirms, identityReview={"status": "pending"},
                       publication="; ".join(j["text"] for j in version["journalHeadings"]),
                       volume=", ".join(version["observedVolumes"]), pages=", ".join(str(p["printed_page"]) for p in version["printedPages"]), year=", ".join(version["observedYears"]))
        else:
            row["reason"] = "ambiguous candidates" if len(candidates) > 1 else "no strong title/byline match"
            report["unmatched"].append(source["key"])
        report["sources"][source["key"]] = row
    count = sum(row["matched"] for row in report["sources"].values())
    report["stats"] = {"filesIndexed": len(files), "matched": count, "unmatched": len(sources) - count,
                       "cacheReused": sum(f["cacheReused"] for f in files),
                       "unreadable": sorted(set([f["fileName"] for f in files if not f["readable"]] +
                           [c["fileName"] for row in report["sources"].values() for c in row["candidates"] if c.get("reason")]))}
    return report


def merge(local, remote):
    for key, entry in remote.get("sources", {}).items():
        previous = local["sources"].get(key, {})
        if not previous.get("matched"):
            local["sources"][key] = dict(entry, origin="zotero", localCandidates=previous.get("candidates", []))
    local["zoteroSearched"] = True
    local["libraries"] = remote.get("libraries", [])
    local["unmatched"] = [key for key, e in local["sources"].items() if not e.get("matched")]
    return local


def compact(report):
    remote = {k: e for k, e in report["sources"].items() if e.get("origin") != "local"}
    result = zotero.compact({"sources": remote})
    for key, e in report["sources"].items():
        if not e.get("matched") or e.get("origin") != "local":
            continue
        result[key] = {"origin": "local", "title": e["title"], "au": e["creators"], "cite": e["cite"],
                       "text": e["textPath"], "pages": e["textPages"], "src": e["textSource"],
                       "file": e["fileName"], "path": e["filePath"], "sha256": e["fileSha256"],
                       "version": e["version"], "versionNote": e["versionNote"], "confirm": e["confirm"], "identityReview": e.get("identityReview", {"status": "pending"})}
    return result


def summary(report):
    return {"stats": report["stats"], "folderErrors": report.get("folderErrors", []),
            "candidates": {key: e.get("localCandidates", e.get("candidates", []))
                           for key, e in report["sources"].items()
                           if e.get("localCandidates") or len(e.get("candidates", [])) > 1 or e.get("candidates") and not e.get("matched")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--folder", action="append", default=[])
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--source-options", type=Path, help="resolved source_options.py plan for this run")
    parser.add_argument("--cache-dir", type=Path)
    for name in ("secondary", "support", "cites"):
        parser.add_argument("--" + name, action="append", default=[])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--compact", action="store_true")
    action.add_argument("--summary", action="store_true")
    action.add_argument("--get")
    action.add_argument("--merge-zotero", type=Path)
    args = parser.parse_args()
    try:
        if args.compact or args.summary or args.get is not None or args.merge_zotero:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            if args.compact:
                print(json.dumps(compact(report), ensure_ascii=False))
            elif args.summary:
                print(json.dumps(summary(report), ensure_ascii=False))
            elif args.get is not None:
                print(json.dumps(report["sources"].get(args.get, {"error": "no such key"}), ensure_ascii=False))
            else:
                protect_output(args.report, [Path(p) for p in report["folders"]])
                write_json(args.report, merge(report, json.loads(args.merge_zotero.read_text(encoding="utf-8"))))
                print("Merged local and Zotero records; local matches retained.")
            return 0
        if not args.cache_dir:
            parser.error("--cache-dir is required for indexing")
        if args.source_options:
            choice = json.loads(args.source_options.read_text(encoding="utf-8"))
            validate_plan(choice)
            if args.folder:
                raise ValueError("use the resolved source-options folders, not another --folder override")
            folders, origin = [Path(p) for p in choice["folder_paths"]], choice["folder_origin"]
        else:
            folders, origin = discover_folders(args.draft, args.project, args.folder)
        protect_output(args.report, folders)
        inputs = [Path(p).resolve() for kind in ("secondary", "support", "cites") for p in getattr(args, kind)]
        if args.draft:
            inputs.append(args.draft.expanduser().resolve())
        if args.source_options:
            inputs.append(args.source_options.resolve())
        if args.report.resolve() in inputs:
            raise ValueError("report must not overwrite an input")
        run_exclusions = [args.report.parent] if any(f in args.report.parent.resolve().parents for f in folders) else []
        report = run(zotero.load_sources(vars(args)), folders, args.cache_dir, exclude=[*run_exclusions, args.cache_dir, args.report, *inputs])
        report["folderOrigin"] = origin
        write_json(args.report, report)
        print(json.dumps(report["stats"], ensure_ascii=False))
        for error in report["folderErrors"]:
            print(json.dumps(error, ensure_ascii=False))
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
