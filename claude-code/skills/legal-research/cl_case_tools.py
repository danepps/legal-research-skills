#!/usr/bin/env python3
"""CourtListener case tools for the legal-research and cite-check skills.

Deterministic helpers that upgrade case verification and retrieval:

  citing  — citing opinions for a case by TWO routes, deduplicated, with a
            treatment-signal triage scan. Route 1 is the citation graph
            (CourtListener's `cites:` filter); route 2 is a full-text search
            for the case name as a phrase, filed after the case, which reaches
            courts that cite by short form, docket number or Westlaw number
            and so have no graph edge. The two routes miss different cases;
            the output says what each produced and how many DISTINCT cases
            the combined set holds (the index is one row per opinion, so a
            decision with a dissent is two rows). Plus the most recent citing
            date (a liveness signal within the index — nothing more).
  history — subsequent history of a decision: everything filed on its own
            docket after the decision date (RECAP; federal only), with the
            dispositive entries flagged (notice of appeal, USCA judgment or
            opinion, mandate, cert. granted or denied, amended or substituted
            opinion, reconsideration, vacatur, remand, Rule 59/60 relief), and
            later opinions in the same litigation from the opinion index
            (appellate decisions, cert dispositions) found by party names.
            This is what a graph lookup cannot see: a judgment vacated on
            reconsideration or reversed by a mandate often leaves no published
            opinion for a citation search to find.
  find    — resolve a case when the reporter citation will not: CourtListener's
            citation metadata is uneven, so a case can be present and
            full-text searchable with no reporter citation attached. Searches
            the case name as a phrase (caseName field), and, given the
            citation string, searches the full text for opinions CITING that
            string — their text confirms the case is real and names its
            parties and court. An unresolved citation is a search problem,
            never evidence of fabrication.
  pdf     — resolve a case to its PDF: CourtListener's stored copy
            (storage.courtlistener.com) when present, else the court's own
            download URL. Optionally downloads it (verifying %PDF magic).

Usage:
    python3 cl_case_tools.py citing "410 U.S. 113" [--limit 20] [--name "Roe v. Wade"]
    python3 cl_case_tools.py citing cluster:108713 [--limit 20]
    python3 cl_case_tools.py history "397 F. Supp. 3d 126" [--name "<case name>"] [--max-entries 100]
    python3 cl_case_tools.py find "Students for Fair Admissions v. Harvard" [--cite "397 F. Supp. 3d 126"] [--year 2019]
    python3 cl_case_tools.py pdf "536 U.S. 181" [--out FILE]

Output: one JSON object on stdout. IMPORTANT caveats baked into the output:
signal hits are TRIAGE flags — the flagged language may concern a different
case discussed in the same passage, so a hit means "open this citing case
and determine the scope," never "treatment confirmed." Docket coverage is
the RECAP archive (crowd-sourced, incomplete, federal only; appellate dockets
are thin), so a missing entry is not evidence that nothing happened, and a
docket entry is the clerk's language, not a holding. This is not
Shepard's/KeyCite and does not prove the absence of negative treatment.
Opinions in the index that postdate the model's training data are real.

AUTH: same token resolution as check_cite.py (COURTLISTENER_API_TOKEN,
COURTLISTENER_TOKEN, then ~/.config/courtlistener/token). The citation
lookup requires it; search usually works without but is rate-limited harder.

Exit codes: 0 = ran (read the JSON); 1 = API/network failure or case not
found (fall back to web checking); 2 = usage error. Stdlib only.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.courtlistener.com"
TOKEN_FILE = os.path.expanduser("~/.config/courtlistener/token")
UA = "legal-research-skill/1.1 (cl_case_tools)"

# Treatment language worth flagging in a citing opinion. Triage only — the
# language may be about a different case in the same passage.
SIGNAL_RES = [
    (name, re.compile(pat, re.IGNORECASE))
    for name, pat in [
        ("overruled", r"\boverrul"),
        ("abrogated", r"\babrogat"),
        ("no_longer_good_law", r"no longer good law"),
        ("superseded_by_statute", r"supersed\w* by statute"),
        ("declined_to_follow", r"declin\w+ to follow"),
        ("limited", r"\blimited to its facts|\bnarrow\w+ (?:by|in)\b"),
        ("called_into_doubt", r"called into (?:doubt|question)|cast doubt"),
        ("disapproved", r"\bdisapprov"),
        ("receded_from", r"\breced\w+ from"),
    ]
]

# Query terms for the treatment probe — citing cases whose TEXT contains
# treatment language, so the highlighted snippets show it in context.
PROBE_TERMS = ('(overruled OR abrogated OR "no longer good law" OR "superseded by statute" '
               'OR "declined to follow" OR "limited to its facts" OR "called into doubt" '
               'OR disapproved OR "receded from")')

# Docket-entry language that decides subsequent history. Each label names what
# the entry is evidence OF; the agent still reads the entry (and, where
# available, the document) before characterizing the disposition.
HISTORY_RES = [
    (label, re.compile(pat, re.IGNORECASE))
    for label, pat in [
        ("mandate", r"\bmandate\b"),
        ("notice_of_appeal", r"notice of (?:cross[- ])?appeal"),
        ("usca_judgment_or_opinion", r"\b(?:usca|court of appeals|circuit)\b.*\b(?:judgment|opinion|order)\b|\b(?:judgment|opinion) of (?:the )?usca"),
        ("appealed_to_supreme_court", r"appealed to (?:the )?supreme court|petition for (?:a )?writ of certiorari|\bcertiorari\b"),
        ("cert_granted", r"certiorari (?:is )?granted|\bcert(?:\.|iorari)? granted"),
        ("cert_denied", r"certiorari (?:is )?denied|\bcert(?:\.|iorari)? denied"),
        ("amended_judgment", r"amended (?:final )?judgment|alter(?:ed)? or amend"),
        ("amended_or_substituted_opinion", r"(?:amended|substituted|corrected|superseding|revised) (?:memorandum )?(?:opinion|order|decision)|\berrata\b|\berratum\b"),
        ("withdrawn", r"\bwithdraw(?:n|al|s)?\b.*\b(?:opinion|order|decision)\b|\b(?:opinion|order|decision)\b.*\bwithdrawn\b"),
        ("reconsideration", r"\breconsider|\brehear|\ben banc\b|rule 59|rule 60|relief from (?:the )?judgment"),
        ("vacated", r"\bvacat"),
        ("remanded", r"\bremand"),
        ("reversed", r"\brevers"),
        ("affirmed", r"\baffirm"),
        ("stay", r"\bstay(?:ed)?\b"),
        ("dismissed", r"\bdismiss"),
    ]
]
# Routine entries that match a history term only by accident (a notice of
# appearance is not a notice of appeal; a "mandate" inside a motion caption is).
ROUTINE_RE = re.compile(r"notice of (?:withdrawal of )?appearance|change of address|pro hac vice|"
                        r"certificate of service|transcript order|notice of attorney", re.IGNORECASE)
ATTACH_RE = re.compile(r"\(Attachments?:\s*([^)]*)\)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SCOTUS_CITE_RE = re.compile(r"\b\d+\s+(?:U\.?\s?S\.?|S\.?\s?Ct\.?|L\.?\s?Ed\.?(?:\s?2d)?)\s+\d+", re.IGNORECASE)
PARTY_NOISE = {"inc", "inc.", "llc", "l.l.c.", "corp", "corp.", "co", "co.", "ltd", "ltd.",
               "the", "of", "a", "an", "et", "al", "al.", "city", "county", "state", "united",
               "states", "america", "president", "fellows", "board", "trustees", "secretary",
               "commissioner", "department", "in", "re", "ex", "rel", "rel.", "for", "and", "on",
               "by", "at", "to", "v", "v.", "vs", "vs.", "town", "village", "u.s.", "u.s.a."}
# Court ids that look like a federal district id but are state courts.
STATE_LOOKALIKES = {"ind"}


# ----------------------------------------------------------------- helpers
def get_token():
    for var in ("COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def request(url, data=None, timeout=45, retries=3):
    """GET/POST JSON. A 429 (rate limit) is retried with a backoff, since several agents share
    the same token during a cite-check run; anything else raises for the caller to report."""
    headers = {"User-Agent": UA}
    token = get_token()
    if token:
        headers["Authorization"] = f"Token {token}"
    delay = 2.0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = delay
                try:
                    wait = max(delay, float(e.headers.get("Retry-After") or 0))
                except ValueError:
                    pass
                print(f"CourtListener rate limit (429) — waiting {wait:.0f}s and retrying", file=sys.stderr)
                time.sleep(min(wait, 30))
                delay *= 2
                continue
            raise


def search(params):
    q = urllib.parse.urlencode(params)
    return request(f"{BASE}/api/rest/v4/search/?{q}")


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def scan_signals(text):
    return [name for name, rx in SIGNAL_RES if rx.search(text or "")]


def court_level(court_id):
    """scotus | circuit | district | bankruptcy | state | unknown, from a CourtListener court id."""
    c = (court_id or "").lower()
    if not c:
        return "unknown"
    if c == "scotus":
        return "scotus"
    if c.startswith("ca") and (c[2:].isdigit() or c in ("cadc", "cafc")):
        return "circuit"
    if c in STATE_LOOKALIKES:
        return "state"
    if re.fullmatch(r"[a-z]{2,3}[nsewmc]?b", c):
        return "bankruptcy"
    if re.fullmatch(r"[a-z]{2,3}[nsewmc]?d", c):
        return "district"
    return "state"


def above(origin_level, court_id):
    """Can a court at court_id review a decision at origin_level? Federal chain only."""
    lvl = court_level(court_id)
    if origin_level in ("district", "bankruptcy"):
        return lvl in ("circuit", "scotus") or (origin_level == "bankruptcy" and lvl == "district")
    if origin_level == "circuit":
        return lvl == "scotus"
    return False


def party_words(case_name, per_side=2):
    """Distinctive words of each side of 'A v. B', for a caseName word search:
    'Students for Fair Admissions, Inc. v. President and Fellows of Harvard College' ->
    [['Students', 'Fair'], ['Harvard', 'College']]."""
    sides = re.split(r"\s+v(?:s?\.|ersus)\s+", case_name or "", maxsplit=1, flags=re.IGNORECASE)
    out = []
    for side in sides:
        words = [w.strip(".,'") for w in re.findall(r"[A-Za-z][A-Za-z'.-]*", side)]
        words = [w for w in words if w and w.lower() not in PARTY_NOISE and len(w) > 1]
        if words:
            out.append(words[:per_side])
    return out


def party_keys(case_name):
    """One distinctive word per side: ['Students', 'Harvard']."""
    return [ws[0] for ws in party_words(case_name, per_side=1)]


def name_query(case_name):
    """caseName field query ANDing the distinctive words of both sides (words, not phrases, so
    noise words between them do not break the match)."""
    words = party_keys(case_name)
    return " AND ".join(f"caseName:{w}" for w in words) if words else f'caseName:"{case_name}"'


def name_phrases(case_name):
    """Phrases a court would use to cite the case in text: the full name (with an ampersand
    variant) and the 'A v. B' short form."""
    out = []
    full = re.sub(r"\s+", " ", (case_name or "")).strip()
    if full:
        out.append(full)
        alt = full.replace(" & ", " and ") if " & " in full else full.replace(" and ", " & ")
        if alt != full:
            out.append(alt)
    keys = party_keys(full)
    if len(keys) == 2:
        short = f"{keys[0]} v. {keys[1]}"
        if all(norm(short) != norm(p) for p in out):
            out.append(short)
    return out


def flag_entry(description):
    """History labels an entry's text is evidence of (empty for routine entries)."""
    text = description or ""
    if ROUTINE_RE.search(text):
        return []
    return [label for label, rx in HISTORY_RES if rx.search(text)]


def attachments_of(description):
    m = ATTACH_RE.search(description or "")
    return m.group(1).strip() if m else ""


def dedupe_rows(rows):
    """One row per decision: by cluster_id, else by normalized case name + date."""
    seen, out = set(), []
    for r in rows:
        key = r.get("cluster_id") or (norm(r.get("case")) + "|" + (r.get("date") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def is_scotus_cite(cite):
    return bool(SCOTUS_CITE_RE.search(cite or ""))


def row_of(r, route):
    snippet = TAG_RE.sub("", " ".join((op.get("snippet") or "") for op in (r.get("opinions") or []))).strip()
    snippet = re.sub(r"\s+", " ", snippet)
    return {
        "cluster_id": r.get("cluster_id"),
        "case": r.get("caseName"),
        "date": r.get("dateFiled"),
        "court": r.get("court_citation_string") or r.get("court"),
        "court_id": r.get("court_id"),
        "cites": r.get("citation") or [],
        "docket_number": r.get("docketNumber"),
        "route": route,
        "signals": scan_signals(snippet),
        "snippet": snippet[:400],
        "url": (BASE + r["absolute_url"]) if r.get("absolute_url") else None,
    }


def lookup_cite(cite):
    data = urllib.parse.urlencode({"text": cite}).encode()
    rows = request(f"{BASE}/api/rest/v4/citation-lookup/", data=data)
    for row in rows or []:
        for cl in row.get("clusters") or []:
            return {"cluster_id": cl["id"], "case_name": cl.get("case_name"),
                    "date_filed": cl.get("date_filed"), "status": row.get("status")}
    return {"cluster_id": None, "status": (rows or [{}])[0].get("status") if rows else None}


def search_by_name(name, year=None, limit=10):
    q = name_query(name)
    params = {"type": "o", "q": q, "order_by": "dateFiled asc"}
    if year:
        params["filed_after"] = f"{int(year) - 1}-01-01"
        params["filed_before"] = f"{int(year) + 1}-12-31"
    got = search(params)
    return q, got.get("count"), [row_of(r, "name-search") for r in (got.get("results") or [])[:limit]]


def resolve_cluster(target, name=None, year=None):
    """'cluster:123', a reporter cite, or (fallback) a case name -> dict with cluster_id, case_name, date_filed, how."""
    if target and target.lower().startswith("cluster:"):
        cid = int(target.split(":", 1)[1])
        try:
            c = request(f"{BASE}/api/rest/v4/clusters/{cid}/?fields=id,case_name,date_filed")
            return {"cluster_id": cid, "case_name": c.get("case_name"), "date_filed": c.get("date_filed"), "how": "cluster-id"}
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            print(f"cluster fetch failed: {e}", file=sys.stderr)
            return None
    if target:
        try:
            hit = lookup_cite(target)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            print(f"citation lookup failed: {e}", file=sys.stderr)
            hit = {"cluster_id": None}
        if hit.get("cluster_id"):
            hit["how"] = "citation-lookup"
            return hit
    if name:
        try:
            _, _, rows = search_by_name(name, year=year, limit=10)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            print(f"name search failed: {e}", file=sys.stderr)
            rows = []
        # prefer a row carrying the cite we were given, else the only/first row
        want = norm(target) if target else ""
        for r in rows:
            if want and any(norm(c) == want for c in r.get("cites") or []):
                return {"cluster_id": r["cluster_id"], "case_name": r["case"], "date_filed": r["date"], "how": "name-search (cite matched)"}
        if len(rows) == 1 or (rows and not want):
            r = rows[0]
            return {"cluster_id": r["cluster_id"], "case_name": r["case"], "date_filed": r["date"], "how": "name-search (single candidate)"}
        if rows:
            print(f"name search returned {len(rows)} candidates and none carries {target!r}; run `find` and pick one (cluster:<id>)", file=sys.stderr)
    return None


def opinions_for_cluster(cluster_id):
    got = request(f"{BASE}/api/rest/v4/opinions/?cluster={cluster_id}&fields=id,local_path,download_url,type")
    return got.get("results") or []


def search_citing(ids, extra_q, limit, by_date=True):
    # The recent listing orders by date (liveness); the treatment probe orders
    # by RELEVANCE — date-ordering it surfaces whatever treatment language was
    # filed last week (usually about other cases), while relevance surfaces
    # the citing cases most about the treatment terms (e.g. Dobbs-era cases
    # discussing Roe's overruling, not a Wisconsin estate case).
    params = {"type": "o", "q": f"cites:({ids})" + (f" AND {extra_q}" if extra_q else ""), "highlight": "on"}
    if by_date:
        params["order_by"] = "dateFiled desc"
    got = search(params)
    return got.get("count"), [row_of(r, "graph") for r in (got.get("results") or [])[:limit]]


def search_name_route(case_name, date_filed, extra_q, limit, by_date=True):
    phrases = name_phrases(case_name)
    if not phrases:
        return None, None, []
    q = "(" + " OR ".join(f'"{p}"' for p in phrases) + ")" + (f" AND {extra_q}" if extra_q else "")
    params = {"type": "o", "q": q, "highlight": "on"}
    if date_filed:
        params["filed_after"] = date_filed
    if by_date:
        params["order_by"] = "dateFiled desc"
    got = search(params)
    return q, got.get("count"), [row_of(r, "name-search") for r in (got.get("results") or [])[:limit]]


# ---------------------------------------------------------------- commands
def cmd_citing(args):
    resolved = resolve_cluster(args.case, name=args.name)
    if not resolved:
        print(f"could not resolve {args.case!r} to a CourtListener cluster (try `find` with the case name)", file=sys.stderr)
        return 1
    cluster_id, case_name, date_filed = resolved["cluster_id"], resolved.get("case_name"), resolved.get("date_filed")
    try:
        ops = opinions_for_cluster(cluster_id)
        if not ops:
            print(f"cluster {cluster_id} has no opinions on CourtListener", file=sys.stderr)
            return 1
        ids = " OR ".join(str(o["id"]) for o in ops)
        # Route 1, the graph: recent citing cases (liveness + what's current), and the
        # treatment probe (citing cases whose text carries treatment language).
        total, recent = search_citing(ids, None, args.limit)
        probe_total, probe = search_citing(ids, PROBE_TERMS, args.limit, by_date=False)
        # Route 2, the name as a phrase in later opinions: reaches citers the graph has
        # no edge for (short-form, docket-number and Westlaw citations). Same two passes.
        name_q, name_total, name_rows = search_name_route(case_name, date_filed, None, args.limit)
        _, name_probe_total, name_probe = search_name_route(case_name, date_filed, PROBE_TERMS, args.limit, by_date=False)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"citing search failed: {e}", file=sys.stderr)
        return 1
    # Sharpen triage: does the snippet actually name the target case's parties? A
    # treatment snippet that never mentions the target is usually about a different case.
    parties = [p.strip().split()[0] for p in (case_name or "").split(" v. ") if p.strip()]
    graph_ids = {r["cluster_id"] for r in recent + probe if r.get("cluster_id")} | {cluster_id}
    for row in probe + name_probe:
        row["mentions_target"] = any(re.search(rf"\b{re.escape(p)}\b", row["snippet"]) for p in parties if len(p) > 2)
    probe.sort(key=lambda r: not r["mentions_target"])
    name_only = [r for r in dedupe_rows(name_rows + name_probe) if r.get("cluster_id") not in graph_ids]
    combined = dedupe_rows(recent + probe + name_only)
    report = {
        "case": {"cluster_id": cluster_id, "case_name": case_name, "date_filed": date_filed,
                 "queried": args.case, "resolved_by": resolved.get("how")},
        "routes": {
            "graph": {"total_citing": total, "returned": len(recent), "with_treatment_language": probe_total},
            "name_search": {"query": name_q, "total": name_total, "returned": len(name_rows),
                            "with_treatment_language": name_probe_total,
                            "not_in_graph": len(name_only)},
        },
        "distinct_cases_returned": len(combined),
        "rows_returned": len(recent) + len(probe) + len(name_rows) + len(name_probe),
        "total_citing": total,
        "most_recent_citing_date": max([r["date"] for r in recent + name_rows if r.get("date")] or [None]),
        "recent_citing": recent,
        "treatment_probe": {"total_with_treatment_language": probe_total, "most_relevant": probe},
        "name_search_only": name_only,
        "name_search_treatment_probe": name_probe,
        "caveats": (
            "Two routes ran: the citation graph (`cites:`) and a full-text phrase search for the case "
            "name filed after the decision. They miss different cases; name_search_only lists what the "
            "graph lacked. Counts are per OPINION row before deduplication — distinct_cases_returned is "
            "the deduplicated figure; report that one. The treatment probes find citing cases whose text "
            "contains treatment language — the flagged language may concern a DIFFERENT case discussed "
            "in the same passage. A hit means: open that citing case and determine WHAT was "
            "overruled/limited and how far (full overruling / partial abrogation / narrowing / mere "
            "distinguishing). No hits does NOT prove good law (this is not Shepard's/KeyCite). "
            "most_recent_citing_date is recency within the retrieved index, nothing more. Opinions that "
            "postdate the model's training data are real."
        ),
    }
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


def merge_entries(head, tail):
    """Union of two entry lists (oldest-first head, newest-first tail) in date order, one copy per entry."""
    seen, out = set(), []
    for e in list(head) + list(reversed(tail)):
        key = (e.get("entry"), e.get("date"), (e.get("description") or "")[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    out.sort(key=lambda e: ((e.get("date") or ""), e.get("entry") or 0))
    return out


def fetch_entries(docket_id, after, max_entries, newest_first=False):
    out, url = [], (f"{BASE}/api/rest/v4/docket-entries/?" + urllib.parse.urlencode({
        "docket": docket_id, "date_filed__gte": after, "order_by": "-date_filed" if newest_first else "date_filed",
        "page_size": 100, "fields": "entry_number,date_filed,description,recap_documents"}))
    count = None
    while url and len(out) < max_entries:
        got = request(url)
        count = got.get("count", count)
        for e in got.get("results") or []:
            docs = e.get("recap_documents") or []
            out.append({
                "entry": e.get("entry_number"),
                "date": e.get("date_filed"),
                "description": re.sub(r"\s+", " ", (e.get("description") or ""))[:400],
                "flags": flag_entry(e.get("description")),
                "attachments": attachments_of(e.get("description")),
                "documents": [{"description": (d.get("description") or "")[:80], "available": bool(d.get("is_available")),
                               "url": (BASE + d["absolute_url"]) if d.get("absolute_url") else None} for d in docs[:3]],
            })
        url = got.get("next")
    return count, out[:max_entries]


DOCKET_CORE_RE = re.compile(r"(?:(\d{1,2}):)?(\d{2})-([a-z]{2,3})-(\d{3,6})", re.IGNORECASE)


def docket_core(docket_number):
    """'Civil Action No. 14-cv-14176-ADB' / '1:14-cv-14176' -> '14-cv-14176' (the part every record shares)."""
    m = DOCKET_CORE_RE.search(docket_number or "")
    if not m:
        return None
    _office, yy, kind, num = m.groups()
    return f"{yy}-{kind.lower()}-{num}"


def find_recap_docket(court_id, docket_number):
    """The RECAP docket record (the one that carries entries) for a court + docket number, or None.
    CourtListener often holds two records for one case — the scraper's (no entries) and RECAP's."""
    core = docket_core(docket_number)
    if not core or not court_id:
        return None
    got = search({"type": "d", "q": f'docketNumber:"{core}"', "court": court_id, "order_by": "dateFiled asc"})
    rows = got.get("results") or []
    rows.sort(key=lambda r: (r.get("dateTerminated") is None, r.get("dateFiled") or ""))
    return {"docket_id": rows[0].get("docket_id"), "docket_number": rows[0].get("docketNumber"),
            "date_terminated": rows[0].get("dateTerminated"), "candidates": len(rows)} if rows else None


def cmd_history(args):
    resolved = resolve_cluster(args.case, name=args.name, year=args.year)
    if not resolved:
        print(f"could not resolve {args.case!r} to a CourtListener cluster (try `find` with the case name)", file=sys.stderr)
        return 1
    cluster_id = resolved["cluster_id"]
    caveats = [
        "Docket coverage is the RECAP archive: crowd-sourced, incomplete, federal only, and appellate "
        "dockets are thin. A missing entry is NOT evidence that nothing happened.",
        "A docket entry is the clerk's language, not a holding: 'VACATED and REMANDED' gives the "
        "disposition, not its scope — retrieve the opinion before characterizing it. A notice of appeal "
        "says an appeal was filed, not how it came out; look for the mandate or the reviewing court's opinion.",
        "An '(Attachments: ...)' parenthetical naming an amended, substituted or corrected opinion is often "
        "the only evidence the published opinion changed; report it as a known, unretrieved amendment.",
        "The opinion index and the docket are separate sources; a later opinion in the same case may sit "
        "on the docket as a PDF while absent from the opinion index, and vice versa.",
        "Supreme Court dockets are not on PACER: a cert. grant or denial shows up, if at all, as an entry "
        "on the lower court's docket or as a later same-litigation opinion. Confirm cert. history on "
        "supremecourt.gov before stating it.",
        "Coordinate courts reaching the same litigation (after transfer, say) can disagree with the origin "
        "but cannot review it: report that as a conflict, not as direct history.",
        "Opinions that postdate the model's training data are real.",
    ]
    try:
        cl = request(f"{BASE}/api/rest/v4/clusters/{cluster_id}/?fields=id,case_name,date_filed,docket_id,citations,history,posture")
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"cluster fetch failed: {e}", file=sys.stderr)
        return 1
    case_name = cl.get("case_name") or resolved.get("case_name")
    date_filed = cl.get("date_filed") or resolved.get("date_filed")
    cites = [f"{c.get('volume')} {c.get('reporter')} {c.get('page')}" for c in cl.get("citations") or []]
    origin = {"cluster_id": cluster_id, "case_name": case_name, "date_filed": date_filed, "citations": cites,
              "queried": args.case, "resolved_by": resolved.get("how"),
              "cluster_history_field": (cl.get("history") or "")[:300]}
    docket = {"checked": False, "note": "", "entries_after_decision": None, "flagged_entries": [], "other_entries": []}
    level = "unknown"
    if cl.get("docket_id"):
        try:
            dk = request(f"{BASE}/api/rest/v4/dockets/{cl['docket_id']}/?fields=id,court_id,docket_number,date_filed,date_terminated,appeal_from_str")
            level = court_level(dk.get("court_id"))
            origin.update({"court_id": dk.get("court_id"), "level": level, "docket_number": dk.get("docket_number"),
                           "docket_date_terminated": dk.get("date_terminated"), "appeal_from": dk.get("appeal_from_str") or ""})
            if level in ("district", "circuit", "bankruptcy") and date_filed:
                docket_id, how = dk["id"], "cluster-link"
                count, entries = fetch_entries(docket_id, date_filed, args.max_entries)
                if count == 0:
                    # The cluster's docket record is often the scraper's empty twin of the RECAP
                    # docket; find the record that carries entries by court + docket number.
                    alt = find_recap_docket(dk.get("court_id"), dk.get("docket_number"))
                    if alt and alt["docket_id"] and alt["docket_id"] != dk["id"]:
                        c2, e2 = fetch_entries(alt["docket_id"], date_filed, args.max_entries)
                        if c2:
                            docket_id, how, count, entries = alt["docket_id"], "recap-search", c2, e2
                            origin["docket_date_terminated"] = origin.get("docket_date_terminated") or alt.get("date_terminated")
                if count and count > len(entries):
                    # A long post-decision docket (an interlocutory ruling in a case that ran on
                    # for years): the dispositive entries — mandate, cert. — sit at the END, so
                    # read the newest entries too rather than stopping at the cap.
                    _, tail = fetch_entries(docket_id, date_filed, max(20, args.max_entries // 2), newest_first=True)
                    entries = merge_entries(entries, tail)
                    docket["read_both_ends"] = True
                flagged = [e for e in entries if e["flags"]]
                docket.update({"checked": True, "docket_id": docket_id, "docket_resolved_by": how, "entries_after_decision": count,
                               "entries_read": len(entries), "flagged_entries": flagged,
                               "other_entries": [e for e in entries if not e["flags"]][: args.max_other],
                               "truncated": bool(count and count > len(entries))})
                if count == 0:
                    docket["note"] = ("no RECAP entries after the decision date: either nothing was filed, or the "
                                      "archive is thin for this docket — not evidence of no appeal")
            else:
                docket["note"] = f"docket pass skipped: court level '{level}' (PACER covers federal courts only)" if level == "state" else \
                    f"docket pass skipped: level '{level}' or no decision date"
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            docket["note"] = f"docket lookup failed: {e}"
    else:
        docket["note"] = "cluster has no linked docket on CourtListener"
    # Later opinions in the same litigation (appellate decisions, cert dispositions, remand decisions).
    same = {"query": None, "count": None, "opinions": [], "note": ""}
    try:
        if party_words(case_name):
            q = name_query(case_name)
            params = {"type": "o", "q": q, "order_by": "dateFiled asc"}
            if date_filed:
                params["filed_after"] = date_filed
            got = search(params)
            rows = [row_of(r, "same-litigation") for r in got.get("results") or []]
            rows = [r for r in dedupe_rows(rows) if r.get("cluster_id") != cluster_id]
            for r in rows:
                r["court_can_review_origin"] = above(level, r.get("court_id")) if level != "unknown" else None
                r.pop("signals", None)
            same.update({"query": q, "count": got.get("count"), "opinions": rows[: args.limit]})
        else:
            same["note"] = "could not derive party names for a same-litigation search"
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        same["note"] = f"same-litigation search failed: {e}"
    report = {"origin": origin, "docket": docket, "same_litigation_opinions": same,
              "what_this_settles": (
                  "Whether an appeal was taken (notice of appeal), whether and how it came out (USCA judgment, "
                  "opinion, mandate), whether the judgment was amended or vacated on reconsideration without a "
                  "citable opinion, whether cert. was sought. Combine the flagged docket entries with the "
                  "same-litigation opinions; a reviewing court's opinion is the thing to cite as history."),
              "caveats": caveats}
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


def cmd_find(args):
    out = {"name": args.name, "cite": args.cite, "candidates": [], "citers_of_cite": None, "lookup": None,
           "note": ("A citation that will not resolve is a search problem, not evidence that the case does not "
                    "exist: CourtListener's citation metadata is uneven, and a case can be present and full-text "
                    "searchable with no reporter citation attached. Opinions whose text cites the citation string "
                    "confirm it is real and name its parties and court. Opinions that postdate the model's "
                    "training data are real.")}
    errors = []
    if args.cite:
        try:
            out["lookup"] = lookup_cite(args.cite)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            errors.append(f"citation lookup failed: {e}")
    try:
        q, count, rows = search_by_name(args.name, year=args.year, limit=args.limit)
        out["name_query"] = q
        out["candidates_total"] = count
        out["candidates"] = rows
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        errors.append(f"name search failed: {e}")
    if args.cite:
        try:
            got = search({"type": "o", "q": f'"{args.cite}"', "order_by": "dateFiled asc", "highlight": "on"})
            rows = [row_of(r, "cites-the-string") for r in (got.get("results") or [])[: args.limit]]
            out["citers_of_cite"] = {"query": f'"{args.cite}"', "count": got.get("count"), "opinions": rows}
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            errors.append(f"citation-string search failed: {e}")
    if errors:
        out["errors"] = errors
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if (out["candidates"] or (out["citers_of_cite"] or {}).get("count")) else 1


def cmd_pdf(args):
    resolved = resolve_cluster(args.case, name=args.name)
    if not resolved:
        print(f"could not resolve {args.case!r} to a CourtListener cluster", file=sys.stderr)
        return 1
    cluster_id, case_name = resolved["cluster_id"], resolved.get("case_name")
    try:
        ops = opinions_for_cluster(cluster_id)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"opinions lookup failed: {e}", file=sys.stderr)
        return 1
    pdf_url, source = None, None
    for o in ops:
        if o.get("local_path"):
            pdf_url, source = f"https://storage.courtlistener.com/{o['local_path']}", "courtlistener-storage"
            break
    if not pdf_url:
        for o in ops:
            if o.get("download_url"):
                pdf_url, source = o["download_url"], "court-website"
                break
    out = {"case": {"cluster_id": cluster_id, "case_name": case_name, "queried": args.case},
           "pdf_url": pdf_url, "source": source}
    if not pdf_url:
        out["note"] = ("no PDF on CourtListener for this cluster (common for older, text-only "
                       "opinions) — the HTML/markdown text remains the record")
        json.dump(out, sys.stdout, indent=2)
        print()
        return 1
    if args.out:
        req = urllib.request.Request(pdf_url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read(100_000_000)
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"pdf download failed: {e}", file=sys.stderr)
            return 1
        if body[:5] != b"%PDF-":
            print("downloaded file is not a PDF (no %PDF magic) — not saved", file=sys.stderr)
            return 1
        with open(args.out, "wb") as f:
            f.write(body)
        out["saved"] = args.out
        out["bytes"] = len(body)
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="CourtListener case tools (citing / history / find / pdf)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("citing", help="citing opinions by two routes + treatment-signal triage")
    p1.add_argument("case", help='reporter cite ("410 U.S. 113") or cluster:<id>')
    p1.add_argument("--limit", type=int, default=20)
    p1.add_argument("--name", help="case name, used to resolve the case when the cite will not")
    p1.set_defaults(fn=cmd_citing)
    p2 = sub.add_parser("history", help="subsequent history: docket entries after the decision + later same-litigation opinions")
    p2.add_argument("case", help='reporter cite ("397 F. Supp. 3d 126") or cluster:<id>')
    p2.add_argument("--name", help="case name, used to resolve the case when the cite will not")
    p2.add_argument("--year", type=int, help="decision year, narrows the name fallback")
    p2.add_argument("--max-entries", type=int, default=150, help="docket entries to read after the decision")
    p2.add_argument("--max-other", type=int, default=12, help="unflagged entries to include as a sample")
    p2.add_argument("--limit", type=int, default=15, help="same-litigation opinions to list")
    p2.set_defaults(fn=cmd_history)
    p3 = sub.add_parser("find", help="resolve a case by name (and by who cites its citation string) when the cite will not resolve")
    p3.add_argument("name", help='case name, e.g. "Fought v. City of Wilkes-Barre"')
    p3.add_argument("--cite", help="the reporter citation as the draft gives it")
    p3.add_argument("--year", type=int, help="decision year (searches year-1..year+1)")
    p3.add_argument("--limit", type=int, default=10)
    p3.set_defaults(fn=cmd_find)
    p4 = sub.add_parser("pdf", help="resolve (and optionally download) the case PDF")
    p4.add_argument("case", help='reporter cite ("536 U.S. 181") or cluster:<id>')
    p4.add_argument("--out", help="download the PDF to this path")
    p4.add_argument("--name", help="case name, used to resolve the case when the cite will not")
    p4.set_defaults(fn=cmd_pdf)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
