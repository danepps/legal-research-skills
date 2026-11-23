#!/usr/bin/env python3
"""Screen citation identity; unresolved lookups get caption and citation-text leads.

Search hits are candidates, never automatic identity or substantive verification.
--name/--year carry draft values for a single citation. --units-file takes JSONL
case units with unit_id, lookup_citation, draft_case_name and draft_year.
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
# Keep comparison normalization separate from fallback-search token selection.
# Agreement between distinctive words screens identity; it does not prove it.
CAPTION_ABBREVIATIONS = {
    "bd": "board", "educ": "education", "dept": "department",
    "assn": "association", "commn": "commission", "natl": "national",
    "intl": "international", "univ": "university", "co": "company",
    "corp": "corporation", "inc": "incorporated", "ltd": "limited",
}
CAPTION_NOISE = PARTY_NOISE | set(
    "v vs versus parte people commonwealth company corporation incorporated limited "
    "commission association national international university government petitioner "
    "petitioners respondent respondents appellant appellants appellee appellees".split())
SOVEREIGN_ABBREVIATIONS = {
    "alabama": "Ala.", "alaska": "Alaska", "arizona": "Ariz.", "arkansas": "Ark.",
    "california": "Cal.", "colorado": "Colo.", "connecticut": "Conn.", "delaware": "Del.",
    "florida": "Fla.", "georgia": "Ga.", "hawaii": "Haw.", "idaho": "Idaho",
    "illinois": "Ill.", "indiana": "Ind.", "iowa": "Iowa", "kansas": "Kan.",
    "kentucky": "Ky.", "louisiana": "La.", "maine": "Me.", "maryland": "Md.",
    "massachusetts": "Mass.", "michigan": "Mich.", "minnesota": "Minn.",
    "mississippi": "Miss.", "missouri": "Mo.", "montana": "Mont.", "nebraska": "Neb.",
    "nevada": "Nev.", "new hampshire": "N.H.", "new jersey": "N.J.",
    "new mexico": "N.M.", "new york": "N.Y.", "north carolina": "N.C.",
    "north dakota": "N.D.", "ohio": "Ohio", "oklahoma": "Okla.", "oregon": "Or.",
    "pennsylvania": "Pa.", "rhode island": "R.I.", "south carolina": "S.C.",
    "south dakota": "S.D.", "tennessee": "Tenn.", "texas": "Tex.", "utah": "Utah",
    "vermont": "Vt.", "virginia": "Va.", "washington": "Wash.",
    "west virginia": "W. Va.", "wisconsin": "Wis.", "wyoming": "Wyo.",
    "district of columbia": "D.C.", "puerto rico": "P.R.", "guam": "Guam",
}


def caption_tokens(name):
    text = re.sub(r"[.'’ʼ]", "", str(name).casefold())
    return re.findall(r"[^\W\d_]+", text, re.UNICODE)


SOVEREIGN_ALIASES = {
    tuple(caption_tokens(alias)): name
    for name, abbreviation in SOVEREIGN_ABBREVIATIONS.items()
    for alias in (name, abbreviation, abbreviation.replace(" ", ""), abbreviation.replace(".", " "))
}
MAX_SOVEREIGN_WORDS = max(map(len, SOVEREIGN_ALIASES))


def caption_words(name):
    words = caption_tokens(name)
    distinctive, sovereigns = set(), set()
    index = 0
    while index < len(words):
        # Consume the longest complete name first: West Virginia is not Virginia,
        # and New York must not leave a shared 'new' in a different caption.
        for width in range(min(MAX_SOVEREIGN_WORDS, len(words) - index), 0, -1):
            sovereign = SOVEREIGN_ALIASES.get(tuple(words[index:index + width]))
            if sovereign:
                sovereigns.add(sovereign)
                index += width
                break
        else:
            word = CAPTION_ABBREVIATIONS.get(words[index], words[index])
            if word not in CAPTION_NOISE and len(word) > 1:
                distinctive.add(word)
            index += 1
    # Sovereigns do not clear criminal-party mismatches. Preserve comparison of
    # captions consisting only of sovereigns, using canonical whole names.
    return distinctive or sovereigns


def word_agreement(left, right):
    """Explain agreement between normalized caption words, without spellchecking."""
    if left == right:
        return "exact"
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 4 and longer.startswith(shorter):
        return "prefix"
    if len(shorter) < 5 or len(longer) - len(shorter) > 1:
        return None
    if len(shorter) == len(longer):
        return "one_edit" if sum(a != b for a, b in zip(shorter, longer)) == 1 else None
    # Lengths differ by one. Skip the first differing letter in the longer word;
    # the remainder must agree exactly. A transposition does not qualify.
    for index, letter in enumerate(shorter):
        if letter != longer[index]:
            return "one_edit" if shorter[index:] == longer[index + 1:] else None
    return "one_edit"


def compare_identity(name, year, case_name, date_filed, *, matched=True):
    """Compare only supplied draft values with an unambiguous lookup result."""
    if name is not None and not isinstance(name, str):
        raise ValueError("draft_case_name must be a string or null")
    if year not in (None, "") and (isinstance(year, bool) or not re.fullmatch(r"[0-9]{4}", str(year))):
        raise ValueError("draft_year must be a four-digit year or null")
    caption = {"draft": name, "resolved": case_name}
    if not name or not name.strip():
        caption["result"] = "not_supplied"
    elif not matched or not case_name:
        caption["result"] = "resolved_unavailable"
    else:
        left, right = caption_words(name), caption_words(case_name)
        caption["shared_words"] = sorted(left & right)
        agreements = []
        for draft_word in sorted(left):
            for resolved_word in sorted(right):
                rule = word_agreement(draft_word, resolved_word)
                if rule in {"prefix", "one_edit"}:
                    agreements.append({"draft": draft_word, "resolved": resolved_word, "rule": rule})
        if agreements:
            caption["word_agreements"] = agreements
        caption["result"] = ("indeterminate" if not left or not right else
                             "match" if left & right or agreements else "mismatch")
    resolved_year = re.match(r"^([0-9]{4})(?:-|$)", str(date_filed or ""))
    resolved_year = resolved_year.group(1) if resolved_year else None
    years = {"draft": year, "resolved": resolved_year, "date_filed": date_filed}
    years["result"] = ("not_supplied" if year in (None, "") else
                       "resolved_unavailable" if not matched or not resolved_year else
                       "match" if str(year) == resolved_year else "mismatch")
    return {"caption": caption, "year": years}


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


def screen(text, name=None, limit=10, year=None):
    compare_identity(name, year, None, None)  # Reject malformed inputs before I/O.
    error = None
    try:
        results = request_json(API, urllib.parse.urlencode({"text": text}).encode())
        if not isinstance(results, list) or any(not isinstance(r, dict) for r in results):
            raise ValueError("unexpected citation-lookup response shape")
    except (OSError, ValueError) as exc:
        results, error = [], str(exc)
    if (name or year not in (None, "")) and len(results) > 1:
        raise ValueError("--name/--year require a single recognized citation, not a batch")
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
        row["identity_comparison"] = compare_identity(
            name, year, row.get("case_name"), row.get("date_filed"), matched=state == "matched")
        if state != "matched":
            row["fallbacks"] = fallback_searches(row["citation"], name, limit)
            row["routes_tried"] += [k for k in ("caption", "citation_text") if row["fallbacks"][k]["status"] != "skipped"]
            row["identity_confirmation"] = "unconfirmed_pending_source_inspection"
        output.append(row)
    return output


def screen_units(units, limit=10):
    """Bind each request to a unit explicitly; never depend on API offsets/order."""
    cases = [u for u in units if u.get("source_type") == "case" and u.get("unit_kind") != "internal_reference"]
    seen = set()
    for unit in cases:
        uid = unit.get("unit_id")
        if not isinstance(uid, str) or not uid.strip() or uid in seen:
            raise ValueError("case units require unique nonempty unit_id values")
        seen.add(uid)
        if not isinstance(unit.get("lookup_citation"), str) or not unit["lookup_citation"].strip():
            raise ValueError(f"{uid}: supply one lookup_citation")
        if "draft_case_name" not in unit or "draft_year" not in unit:
            raise ValueError(f"{uid}: supply draft_case_name and draft_year (null if absent)")
        compare_identity(unit["draft_case_name"], unit["draft_year"], None, None)
    output = []
    for unit in cases:
        rows = screen(unit["lookup_citation"], unit["draft_case_name"], limit, unit["draft_year"])
        if len(rows) != 1:
            raise ValueError(f"{unit['unit_id']}: lookup_citation must identify one citation")
        output.append(dict(rows[0], unit_id=unit["unit_id"], source_id=unit.get("source_id"),
                           lookup_citation=unit["lookup_citation"]))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="*")
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--units-file", type=Path, help="JSONL citation units with explicit draft metadata")
    parser.add_argument("--output", type=Path, help="Create a new JSONL screen ledger; refuses an existing file")
    parser.add_argument("--name", help="Caption printed in the draft for a single citation")
    parser.add_argument("--year", help="Decision year printed in the draft for a single citation")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    chunks = [text.strip() for text in args.text if text.strip()]
    if args.input_file:
        chunks.append(args.input_file.read_text(encoding="utf-8"))
    if args.units_file and (chunks or args.name is not None or args.year is not None):
        parser.error("--units-file cannot be combined with text, --input-file, --name or --year")
    if (not chunks and not args.units_file) or not 1 <= args.limit <= 100:
        parser.error("provide citation text and a --limit between 1 and 100")
    if args.output and args.output.exists():
        parser.error("--output already exists; preserve it and choose a new path")
    if not token():
        print("No CourtListener token; verify directly and disclose unavailable API routes.", file=sys.stderr)
        return 1
    try:
        if args.units_file:
            units = [json.loads(line) for line in args.units_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            if any(not isinstance(unit, dict) for unit in units):
                raise ValueError("--units-file rows must be objects")
            output = screen_units(units, args.limit)
        else:
            output = screen(" ;\n".join(chunks), args.name, args.limit, args.year)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                for row in output:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except (OSError, ValueError) as exc:
        print(f"check_cite: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
