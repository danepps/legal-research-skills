#!/usr/bin/env python3
"""Pre-report Zotero sweep for the cite-check workflow (added 2026-11-12).

Why: on the 2026-11-12 run, 65 quotations ended "unverifiable" or "not checked" although, for
most of them, the Zotero pre-lookup had already put the source's full text on disk. The quote had
been resolved to an unresolved short form or a bare "Id.", so the agent was told the source was not
in Zotero and went to a paywalled web copy instead. This sweep closes that gap with no model
judgment: for each quote unit it walks the unit's footnote in the citation ledger (every full cite
in the note, and the full cite every Id./supra/short form there resolves to, including a stale
supra matched by author name), takes every source the pre-lookup holds text for, and runs
verify_quotes.py against those files.

Usage:
    python3 zotero_sweep.py EXTRACT.json ZOTERO_LOOKUP.json --ids 12 15 197 [...]

Prints one JSON object: {"results": [{id, footnote, found, status, file, key, item, title,
page_in_file, matched, tried}]}. `found` is true when verify_quotes matched the quote (verbatim,
normalized, or altered with marked alterations) in one of the files; `status` is its tier.
`page_in_file` counts PDF pages from 1, so a cover page shifts it from the printed page: the sweep
never judges a pincite. Exit 0 always (2 on usage errors).
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import citation_ledger as cl  # noqa: E402
import prepare_units as pu  # noqa: E402

XREF = ("id", "supra", "case-short")
FOUND = ("verbatim", "normalized", "altered")


def chain_keys(instances, note):
    """Ledger keys of every source the footnote cites or cross-refers to, in note order."""
    keys = []
    for x in instances:
        if x["note"] != note or x["kind"] in ("text", "internal"):
            continue
        if x["kind"] in XREF:
            f = x.get("xref_final")
            if f is None:
                f = x.get("xref_name_final")
            if f is None:
                continue
            x = instances[f]
        if x["kind"] in ("case", "statute") or x["kind"] in XREF:
            continue
        if x["key"] not in keys:
            keys.append(x["key"])
    return keys


def run_verify(text_path, items):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(items, f)
        qpath = f.name
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, "verify_quotes.py"), text_path, "--json", qpath],
                             capture_output=True, text=True)
        if out.returncode not in (0, 1):
            return {}
        return {r.get("id"): r for r in json.loads(out.stdout).get("results", [])}
    except (ValueError, OSError):
        return {}
    finally:
        os.unlink(qpath)


def sweep(extract, lookup, ids):
    ledger = cl.build_ledger(extract)
    inst = ledger["instances"]
    units = {u["id"]: u for u in pu.build_units(extract)}
    sources = lookup.get("sources", {})
    # file -> (record, [unit ids]) so each text file is read once
    plan, tried = {}, {}
    for uid in ids:
        u = units.get(uid)
        if not u or u.get("footnote") is None:
            tried[uid] = []
            continue
        tried[uid] = []
        for k in chain_keys(inst, u["footnote"]):
            e = sources.get(k) or {}
            path = e.get("textPath")
            if not (e.get("matched") and path and os.path.exists(path)):
                continue
            plan.setdefault(path, (k, e, []))[2].append(uid)
            tried[uid].append(path)
    hits = {}
    for path, (k, e, uids) in plan.items():
        res = run_verify(path, [{"id": i, "quote": units[i]["quote"]} for i in uids])
        for i in uids:
            r = res.get(i) or {}
            if r.get("status") in FOUND and i not in hits:
                hits[i] = {"status": r["status"], "file": path, "key": k, "item": e.get("itemKey", ""),
                           "library": e.get("library", ""), "title": e.get("title", ""),
                           "page_in_file": r.get("page"), "matched": (r.get("match_excerpt") or "")[:300]}
    out = []
    for uid in ids:
        u = units.get(uid) or {}
        h = hits.get(uid)
        row = {"id": uid, "footnote": u.get("footnote"), "found": bool(h), "tried": tried.get(uid, [])}
        if h:
            row.update(h)
        out.append(row)
    return {"results": out}


def main(argv):
    if len(argv) < 4 or "--ids" not in argv:
        print(__doc__, file=sys.stderr)
        return 2
    i = argv.index("--ids")
    try:
        ids = [int(a) for a in argv[i + 1:]]
        extract = json.load(open(argv[0], encoding="utf-8"))
        lookup = json.load(open(argv[1], encoding="utf-8"))
    except (ValueError, OSError) as e:
        print("zotero_sweep: %s" % e, file=sys.stderr)
        return 2
    json.dump(sweep(extract, lookup, ids), sys.stdout, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
