#!/usr/bin/env python3
"""Screen citation identity; unresolved lookups get caption and citation-text leads.

Search hits are candidates, never automatic identity or substantive verification.
--name applies to a single citation; batch misses still get citation-text searches.
Stdlib only. Authentication: environment, then ~/.config/courtlistener/token.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.courtlistener.com"
API = BASE + "/api/rest/v4/citation-lookup/"
TOKEN_FILE = Path("~/.config/courtlistener/token").expanduser()
PARTY_NOISE = set("the of a an et al inc llc corp co ltd city county state united states america president fellows board trustees secretary commissioner department in re ex rel for and on by at to".split())


def token() -> str | None:
    for name in ("COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def request_json(url, data=None, timeout=30):
    # Pagination URLs are server-controlled. Never forward the token off-origin.
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme, parsed.netloc) != ("https", "www.courtlistener.com"):
        raise ValueError("refusing non-CourtListener API URL")
    headers = {"User-Agent": "codex-legal-research/1.4"}
    credential = token()
    if credential:
        headers["Authorization"] = f"Token {credential}"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as response:
        return json.load(response)


def phrase(text):
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"') + '"'


def party_tokens(name):
    sides = re.split(r"\s+(?:v\.?|vs\.?|versus)\s+", name or "", maxsplit=1, flags=re.I)
    out = []
    for side in sides:
        words = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", side, re.UNICODE)
        significant = [w for w in words if w.casefold() not in PARTY_NOISE and len(w) > 1]
        if significant:
            out.append(significant[0])
        elif words:  # Preserve e.g. United States rather than silently dropping a side.
            out.append(" ".join(words))
    return out


def name_query(name):
    return " AND ".join("caseName:" + phrase(word) for word in party_tokens(name))


def fetch_pages(url, limit=20, max_pages=10):
    rows, seen = [], set()
    total = None
    while url and len(rows) < limit and len(seen) < max_pages:
        if url in seen:
            break
        seen.add(url)
        data = request_json(url)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("unexpected paginated response shape")
        if total is None:
            total = data.get("count")
        remaining = limit - len(rows)
        page = data["results"]
        rows.extend(page[:remaining])
        url = data.get("next")
        if len(page) > remaining:
            url = url or "unread rows in final page"
            break
    return {"count": total, "results": rows, "pages_read": len(seen),
            "truncated": bool(url) or (isinstance(total, int) and total > len(rows))}


def search(query, *, limit=20, **filters):
    params = {"type": "o", "q": query, "highlight": "on", **filters}
    url = BASE + "/api/rest/v4/search/?" + urllib.parse.urlencode(params)
    packet = {"query": query, "url": url, "filters": filters}
    try:
        packet.update(fetch_pages(url, limit))
        packet["status"] = "checked"
    except (OSError, ValueError) as exc:
        packet.update(status="unavailable", error=str(exc), results=[], count=None, truncated=True)
    return packet


def opinion_row(result):
    text = " ".join(str(o.get("snippet") or "") for o in result.get("opinions") or [])
    snippet = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()
    return {"cluster_id": result.get("cluster_id"), "case_name": html.unescape(re.sub(r"<[^>]+>", "", result.get("caseName") or "")),
            "date_filed": result.get("dateFiled"), "court": result.get("court_citation_string") or result.get("court"),
            "court_id": result.get("court_id"), "citations": result.get("citation") or [],
            "absolute_url": result.get("absolute_url"), "opinion_ids": [o["id"] for o in result.get("opinions") or [] if o.get("id")],
            "snippet": snippet[:1000]}


def decision_keys(row):
    keys = []
    if row.get("cluster_id") is not None:
        keys.append("cluster:" + str(row["cluster_id"]))
    # Slip/bound versions can be separate clusters. Shared reporter identity,
    # exact date and exact court are stronger than caption similarity.
    if row.get("court_id") and row.get("date_filed"):
        for cite in row.get("citations") or []:
            normalized = re.sub(r"[^a-z0-9]", "", str(cite).casefold())
            if normalized:
                keys.append(f"cite:{row['court_id']}:{row['date_filed']}:{normalized}")
    if row.get("absolute_url"):
        keys.append("url:" + row["absolute_url"])
    return keys


def decision_key(row):
    return next(iter(decision_keys(row)), None)


def dedupe_decisions(rows):
    # Union overlapping IDs/citations, including a later row bridging two groups.
    parents = list(range(len(rows)))
    aliases = {}
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, row in enumerate(rows):
        for key in decision_keys(row):
            if key in aliases:
                parents[root(i)] = root(aliases[key])
            aliases[key] = i
    groups = {}
    for i, row in enumerate(rows):
        group = root(i)
        if group not in groups:
            groups[group] = dict(row)
            groups[group]["cluster_ids"] = [row["cluster_id"]] if row.get("cluster_id") is not None else []
        else:
            old = groups[group]
            for field in ("routes", "signals", "opinion_ids", "citations"):
                if field in row or field in old:
                    old[field] = list(dict.fromkeys([*old.get(field, []), *row.get(field, [])]))
            if row.get("cluster_id") is not None and row["cluster_id"] not in old["cluster_ids"]:
                old["cluster_ids"].append(row["cluster_id"])
            if row.get("snippet") and row["snippet"] != old.get("snippet"):
                old["additional_snippets"] = list(dict.fromkeys([*old.get("additional_snippets", []), row["snippet"]]))
    return list(groups.values())


def fallback_searches(citation, name=None, limit=10):
    caption = search(name_query(name), limit=limit) if name_query(name) else {
        "status": "skipped", "reason": "No caption supplied; obtain it from draft context or a primary record.", "results": []}
    cited = search(phrase(citation), limit=limit) if citation else {
        "status": "skipped", "reason": "No citation string supplied.", "results": []}
    for route in (caption, cited):
        route["results"] = [opinion_row(r) for r in route["results"]]
    return {"caption": caption, "citation_text": cited,
            "interpretation": "Candidate matches and citing passages corroborate identity only after inspection; repeated citations can repeat errors. Unconfirmed is never fabricated."}


def lookup_state(result):
    status = result.get("status")
    if len(result.get("clusters") or []) > 1 or status == 300:
        return "ambiguous"
    if status == 200 and result.get("clusters"):
        return "matched"
    if status == 404:
        return "not_found_in_index"
    if status == 429:
        return "rate_limited"
    return "unresolved"


def screen(text, name=None, limit=10):
    error = None
    try:
        results = request_json(API, urllib.parse.urlencode({"text": text}).encode())
        if not isinstance(results, list) or any(not isinstance(r, dict) for r in results):
            raise ValueError("unexpected citation-lookup response shape")
    except (OSError, ValueError) as exc:
        results, error = [], str(exc)
    if name and len(results) > 1:
        raise ValueError("--name requires a single recognized citation, not a batch")
    if not results:
        results = [{"citation": text, "error_message": error or "No citations recognized"}]
    output = []
    for result in results:
        state = lookup_state(result)
        row = {"citation": result.get("citation") or text,
               "found": True if state == "matched" else False if state == "not_found_in_index" else None,
               "lookup_state": state, "lookup_status": result.get("status"),
               "verification_scope": "identity_only", "routes_tried": ["citation_lookup"]}
        clusters = result.get("clusters") or []
        if clusters:
            first = clusters[0]
            row.update(case_name=first.get("case_name"), date_filed=first.get("date_filed"),
                       url=urllib.parse.urljoin(BASE, first.get("absolute_url") or ""))
            if len(clusters) > 1:
                row["ambiguous_matches"] = len(clusters)
        if result.get("error_message"):
            row["error"] = result["error_message"]
        if state != "matched":
            row["fallbacks"] = fallback_searches(row["citation"], name, limit)
            row["routes_tried"] += [k for k in ("caption", "citation_text") if row["fallbacks"][k]["status"] != "skipped"]
            row["identity_confirmation"] = "unconfirmed_pending_source_inspection"
        output.append(row)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="*")
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--name", help="Caption for a single citation; never inferred from the first batch match")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    chunks = [text.strip() for text in args.text if text.strip()]
    if args.input_file:
        chunks.append(args.input_file.read_text(encoding="utf-8"))
    if not chunks or not 1 <= args.limit <= 100:
        parser.error("provide citation text and a --limit between 1 and 100")
    if not token():
        print("No CourtListener token; verify directly and disclose unavailable API routes.", file=sys.stderr)
        return 1
    try:
        output = screen(" ;\n".join(chunks), args.name, args.limit)
    except (OSError, ValueError) as exc:
        print(f"check_cite: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
