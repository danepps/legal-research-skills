#!/usr/bin/env python3
"""CourtListener case tools for the legal-research skill.

Two deterministic helpers that upgrade case verification and retrieval:

  citing — recent citing opinions for a case, newest first, with a
           treatment-signal triage scan. Turns the "quick search for
           'overruled'" glance into a systematic check: the N most recent
           citing cases are listed with any treatment language flagged
           ("overruled", "abrogated", "no longer good law", ...), plus the
           most recent citing date (a liveness signal — a doctrine nobody
           has cited in a decade is dormant).
  pdf   —  resolve a case to its PDF: CourtListener's stored copy
           (storage.courtlistener.com) when present, else the court's own
           download URL. Optionally downloads it (verifying %PDF magic).

Usage:
    python3 cl_case_tools.py citing "410 U.S. 113" [--limit 20]
    python3 cl_case_tools.py citing cluster:108713 [--limit 20]
    python3 cl_case_tools.py pdf "536 U.S. 181" [--out FILE]

Output: one JSON object on stdout. IMPORTANT caveats baked into the output:
signal hits are TRIAGE flags — the flagged language may concern a different
case discussed in the same passage, so a hit means "open this citing case
and determine the scope," never "treatment confirmed." This is not
Shepard's/KeyCite and does not prove the absence of negative treatment.

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
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.courtlistener.com"
TOKEN_FILE = os.path.expanduser("~/.config/courtlistener/token")
UA = "legal-research-skill/1.0 (cl_case_tools)"

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

TAG_RE = re.compile(r"<[^>]+>")


def get_token():
    for var in ("COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def request(url, data=None, timeout=45):
    headers = {"User-Agent": UA}
    token = get_token()
    if token:
        headers["Authorization"] = f"Token {token}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def resolve_cluster(target):
    """'cluster:123' or a reporter cite -> (cluster_id, case_name) or None."""
    if target.lower().startswith("cluster:"):
        return int(target.split(":", 1)[1]), None
    data = urllib.parse.urlencode({"text": target}).encode()
    try:
        rows = request(f"{BASE}/api/rest/v4/citation-lookup/", data=data)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"citation lookup failed: {e}", file=sys.stderr)
        return None
    for row in rows or []:
        for cl in row.get("clusters") or []:
            return cl["id"], cl.get("case_name")
    return None


def opinions_for_cluster(cluster_id):
    got = request(f"{BASE}/api/rest/v4/opinions/?cluster={cluster_id}&fields=id,local_path,download_url,type")
    return got.get("results") or []


def scan_signals(text):
    return [name for name, rx in SIGNAL_RES if rx.search(text or "")]


# Query terms for the treatment probe — citing cases whose TEXT contains
# treatment language, so the highlighted snippets show it in context.
PROBE_TERMS = ('(overruled OR abrogated OR "no longer good law" OR "superseded by statute" '
               'OR "declined to follow" OR "limited to its facts" OR "called into doubt" '
               'OR disapproved OR "receded from")')


def search_citing(ids, extra_q, limit, by_date=True):
    # The recent listing orders by date (liveness); the treatment probe orders
    # by RELEVANCE — date-ordering it surfaces whatever treatment language was
    # filed last week (usually about other cases), while relevance surfaces
    # the citing cases most about the treatment terms (e.g. Dobbs-era cases
    # discussing Roe's overruling, not a Wisconsin estate case).
    params = {
        "type": "o",
        "q": f"cites:({ids})" + (f" AND {extra_q}" if extra_q else ""),
        "highlight": "on",
    }
    if by_date:
        params["order_by"] = "dateFiled desc"
    q = urllib.parse.urlencode(params)
    got = request(f"{BASE}/api/rest/v4/search/?{q}")
    rows = []
    for r in (got.get("results") or [])[:limit]:
        snippet = TAG_RE.sub("", " ".join(
            (op.get("snippet") or "") for op in (r.get("opinions") or [])
        )).strip()
        snippet = re.sub(r"\s+", " ", snippet)
        rows.append({
            "case": r.get("caseName"),
            "date": r.get("dateFiled"),
            "court": r.get("court_citation_string") or r.get("court"),
            "cites": r.get("citation") or [],
            "signals": scan_signals(snippet),
            "snippet": snippet[:400],
        })
    return got.get("count"), rows


def cmd_citing(args):
    resolved = resolve_cluster(args.case)
    if not resolved:
        print(f"could not resolve {args.case!r} to a CourtListener cluster", file=sys.stderr)
        return 1
    cluster_id, case_name = resolved
    try:
        ops = opinions_for_cluster(cluster_id)
        if not ops:
            print(f"cluster {cluster_id} has no opinions on CourtListener", file=sys.stderr)
            return 1
        ids = " OR ".join(str(o["id"]) for o in ops)
        # Two passes: recent citing cases (liveness + what's current), and the
        # treatment probe (citing cases whose text carries treatment language).
        total, recent = search_citing(ids, None, args.limit)
        probe_total, probe = search_citing(ids, PROBE_TERMS, args.limit, by_date=False)
        # Sharpen triage: does the snippet actually name the target case's
        # parties? A treatment snippet that never mentions the target is
        # usually about a different case cited in the same opinion.
        parties = [p.strip().split()[0] for p in (case_name or "").split(" v. ") if p.strip()]
        for row in probe:
            row["mentions_target"] = any(
                re.search(rf"\b{re.escape(p)}\b", row["snippet"]) for p in parties if len(p) > 2
            )
        probe.sort(key=lambda r: not r["mentions_target"])
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"citing search failed: {e}", file=sys.stderr)
        return 1

    report = {
        "case": {"cluster_id": cluster_id, "case_name": case_name, "queried": args.case},
        "total_citing": total,
        "most_recent_citing_date": recent[0]["date"] if recent else None,
        "recent_citing": recent,
        "treatment_probe": {
            "total_with_treatment_language": probe_total,
            "most_relevant": probe,
        },
        "caveats": (
            "The treatment probe finds citing cases whose text contains treatment language — the "
            "flagged language may concern a DIFFERENT case discussed in the same passage. A hit "
            "means: open that citing case and determine WHAT was overruled/limited and how far "
            "(full overruling / partial abrogation / narrowing / mere distinguishing). No hits "
            "does NOT prove good law (this is not Shepard's/KeyCite). most_recent_citing_date is "
            "a liveness signal: an old date means the doctrine may be dormant."
        ),
    }
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


def cmd_pdf(args):
    resolved = resolve_cluster(args.case)
    if not resolved:
        print(f"could not resolve {args.case!r} to a CourtListener cluster", file=sys.stderr)
        return 1
    cluster_id, case_name = resolved
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
    ap = argparse.ArgumentParser(description="CourtListener case tools (citing / pdf)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("citing", help="recent citing opinions + treatment-signal triage")
    p1.add_argument("case", help='reporter cite ("410 U.S. 113") or cluster:<id>')
    p1.add_argument("--limit", type=int, default=20)
    p1.set_defaults(fn=cmd_citing)
    p2 = sub.add_parser("pdf", help="resolve (and optionally download) the case PDF")
    p2.add_argument("case", help='reporter cite ("536 U.S. 181") or cluster:<id>')
    p2.add_argument("--out", help="download the PDF to this path")
    p2.set_defaults(fn=cmd_pdf)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
