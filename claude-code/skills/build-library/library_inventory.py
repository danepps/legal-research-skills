#!/usr/bin/env python3
"""Dump a compact inventory of a Zotero library — run this BEFORE proposing candidates.

Why this exists: on 2026-08-01 a run added three duplicates because the dedup step was delegated to a subagent, which reported the group library
held "only 13 items plus a handful of unrelated works." It held 105. Per-candidate
searching is fragile and easy to skip; a whole-library dump is cheap and unskippable.
102 items render in well under 3k tokens, so there is no reason not to read all of it.

Usage:
  python3 library_inventory.py --group <ID>
  python3 library_inventory.py --user            # personal library
  python3 library_inventory.py --group <ID> --json      # machine-readable
  python3 library_inventory.py --group <ID> --grep kahan lenity

Output is one line per top-level item:
  YEAR | PDF | AuthorLastNames | Title | Publication | ITEMKEY
"PDF" means the item has a child attachment whose contentType is application/pdf
(checked by listing the library's attachments, one extra paginated request, not
one per item); blank means no PDF attached. A child note or a non-PDF attachment
does not count. The JSON output carries both `child_count` (Zotero's numChildren,
notes included) and `has_pdf` (true only after that attachment check).
"""
import argparse, json, os, re, sys, urllib.request

USER_ID = os.environ.get("ZOTERO_USER_ID") or os.environ.get("ZOTERO_LIBRARY_ID", "")


def api_key():
    if os.environ.get("ZOTERO_API_KEY"):
        return os.environ["ZOTERO_API_KEY"]
    cfg = json.load(open(os.path.expanduser("~/.claude.json")))

    def find(o):
        if isinstance(o, dict):
            if "ZOTERO_API_KEY" in o:
                return o["ZOTERO_API_KEY"]
            for v in o.values():
                r = find(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
    k = find(cfg)
    if not k:
        sys.exit("no ZOTERO_API_KEY found (env or ~/.claude.json)")
    return k


def fetch_all(base, key, path="items/top", query=""):
    items, start = [], 0
    while True:
        url = f"{base}/{path}?limit=100&start={start}&format=json{query}"
        req = urllib.request.Request(url, headers={"Zotero-API-Key": key})
        with urllib.request.urlopen(req, timeout=120) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        items += batch
        start += 100
        if len(batch) < 100:
            break
    return items


def pdf_parents(base, key):
    """Keys of top-level items that have a child attachment with contentType
    application/pdf. One paginated listing of the library's attachments."""
    parents = set()
    for it in fetch_all(base, key, "items", "&itemType=attachment"):
        d = it.get("data", {})
        if (d.get("contentType") or "").lower() == "application/pdf" and d.get("parentItem"):
            parents.add(d["parentItem"])
    return parents


def year(d):
    m = re.search(r"(1[0-9]{3}|20[0-9]{2})", d.get("date", "") or "")
    return m.group(0) if m else "????"


def authors(d):
    names = [c.get("lastName") or c.get("name", "")
             for c in d.get("creators", [])
             if c.get("creatorType") in ("author", "editor")]
    return "; ".join(n for n in names if n) or "—"


def clean(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    return (t.replace("&quot;", '"').replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">").strip())


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--group", help="group library id")
    g.add_argument("--user", action="store_true", help="personal library (needs env ZOTERO_USER_ID)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--grep", nargs="+", metavar="TERM",
                    help="only show rows matching any term (case-insensitive)")
    a = ap.parse_args()

    key = api_key()
    if a.user and not USER_ID:
        sys.exit("set ZOTERO_USER_ID (your Zotero user library id) to use --user")
    base = (f"https://api.zotero.org/users/{USER_ID}" if a.user
            else f"https://api.zotero.org/groups/{a.group}")
    items = fetch_all(base, key)
    with_pdf = pdf_parents(base, key)

    rows = []
    for it in items:
        d = it["data"]
        rows.append({
            "key": d["key"],
            "year": year(d),
            "authors": authors(d),
            "title": clean(d.get("title", "")),
            "publication": clean(d.get("publicationTitle") or d.get("publisher") or ""),
            "itemType": d.get("itemType", ""),
            "child_count": int(it.get("meta", {}).get("numChildren", 0) or 0),
            "has_pdf": d["key"] in with_pdf,
            "DOI": d.get("DOI", ""),
            "ISBN": d.get("ISBN", ""),
        })
    rows.sort(key=lambda r: (r["year"], r["authors"]))

    if a.grep:
        terms = [t.lower() for t in a.grep]
        rows = [r for r in rows
                if any(t in (r["title"] + " " + r["authors"] + " " + r["publication"]).lower()
                       for t in terms)]

    if a.json:
        print(json.dumps(rows, indent=1))
        return

    for r in rows:
        pdf = "PDF" if r["has_pdf"] else "   "
        print(f"{r['year']} | {pdf} | {r['authors'][:40]:<40} | "
              f"{r['title'][:70]:<70} | {r['publication'][:26]:<26} | {r['key']}")
    missing = sum(1 for r in rows if not r["has_pdf"])
    print(f"\nTOTAL {len(rows)} top-level items ({missing} without a PDF attachment)")


if __name__ == "__main__":
    main()
