#!/usr/bin/env python3
"""Bounded subsequent-history leads from RECAP entries and later caption matches.

Read the actual disposition and verify litigation identity and reviewing jurisdiction
before treating a lead as history. This helper makes no Bluebook or good-law verdict.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import urllib.parse

from check_cite import (BASE, API, request_json, fetch_pages, search, name_query,
                        phrase, opinion_row, dedupe_decisions)

HISTORY_PATTERNS = {
    "notice_of_appeal": r"\bnotice of (?:cross[- ]?)?appeal\b",
    "appellate_judgment_or_opinion": r"\b(?:USCA|court of appeals|circuit)\b.*\b(?:judgment|opinion|order)\b|\b(?:judgment|opinion|order)\s+of\s+(?:the\s+)?(?:USCA|court of appeals)\b",
    "mandate": r"\bmandate\b",
    "cert_granted": r"\bcert(?:\.|iorari)\s+(?:is\s+)?granted\b",
    "cert_denied": r"\bcert(?:\.|iorari)\s+(?:is\s+)?denied\b",
    "cert_petition": r"\bpetition\b.*\bcertiorari\b",
    "amended_or_substituted_opinion": r"\b(?:amended|substituted|corrected|superseding|revised)\s+(?:memorandum\s+)?(?:opinion|order|decision|judgment)\b|\berrat[au]m?\b",
    "reconsideration": r"\breconsider|\brehear|\ben banc\b|\brule\s+(?:59|60)\b|relief from (?:the )?judgment",
    "vacatur": r"\bvacat", "remand": r"\bremand", "reversal": r"\brevers", "affirmance": r"\baffirm",
    "withdrawn_opinion": r"\bwithdrawn\b.*\bopinion\b|\bopinion\b.*\bwithdrawn\b",
}
LIMITS = [
    "RECAP is crowd-sourced, incomplete and federal-only; appellate dockets are thin.",
    "Supreme Court dockets are not on PACER; verify certiorari history using lower-court entries, later opinions and the Supreme Court's own record.",
    "Docket text is the clerk's language, not a holding; motions and notices may request an outcome without establishing one.",
    "A notice of appeal is not an outcome. No hits is not proof of good law or absence of later proceedings.",
    "Caption matches are only same-litigation candidates; verify docket identity and actual reviewing jurisdiction, including state review routes.",
    "Entries use date_filed__gte (inclusive); inspect same-day entries for their sequence relative to the decision.",
]


def flags(text):
    return [label for label, pattern in HISTORY_PATTERNS.items() if re.search(pattern, text or "", re.I | re.S)]


def docket_core(text):
    match = re.search(r"(?<!\d)(\d{2})\s*-?\s*(cv|cr|mc|md|bk|ap)\s*-?\s*(\d+)\b", text or "", re.I)
    return "-".join(match.groups()).lower() if match else None


def object_id(value):
    return str(value).rstrip("/").split("/")[-1] if value is not None else None


def resolve(target):
    if target.lower().startswith("cluster:"):
        cid = int(target.split(":", 1)[1])
    else:
        rows = request_json(API, urllib.parse.urlencode({"text": target}).encode())
        candidates = {int(c["id"]) for r in rows or [] for c in r.get("clusters") or []}
        if len(candidates) != 1:
            raise ValueError("unresolved/ambiguous citation; use check_cite.py --name and inspect candidates before supplying cluster:ID")
        cid = candidates.pop()
    return request_json(f"{BASE}/api/rest/v4/clusters/{cid}/")


def entries(docket_id, date, limit):
    params = {"docket": docket_id, "date_filed__gte": date, "order_by": "date_filed"}
    url = BASE + "/api/rest/v4/docket-entries/?" + urllib.parse.urlencode(params)
    result = fetch_pages(url, limit)
    result["url"] = url
    result["read_both_ends"] = False
    count = result.get("count")
    if result.get("truncated") or (isinstance(count, int) and count > len(result["results"])):
        result["truncated"] = True
        newest_url = BASE + "/api/rest/v4/docket-entries/?" + urllib.parse.urlencode(
            dict(params, order_by="-date_filed"))
        try:
            newest = fetch_pages(newest_url, max(20, limit // 2))
        except (OSError, ValueError, KeyError) as exc:
            result["newest_entries"] = {"status": "unavailable", "url": newest_url, "reason": str(exc)}
        else:
            result["newest_entries"] = {
                "status": "checked", "url": newest_url, "count": newest.get("count"),
                "retrieved_count": len(newest["results"]), "pages_read": newest.get("pages_read", 0),
                "truncated": newest.get("truncated", False),
            }
            result["read_both_ends"] = True
            seen, merged = set(), []
            for row in result["results"] + newest["results"]:
                key = (("id", str(row["id"])) if row.get("id") is not None else
                       ("entry", str(row.get("entry_number")), row.get("date_filed"), row.get("description")))
                if key not in seen:
                    seen.add(key)
                    merged.append(row)
            result["results"] = sorted(merged, key=lambda row: (
                row.get("date_filed") or "", str(row.get("entry_number") or 0).zfill(20)))
            result["pages_read"] = result.get("pages_read", 0) + newest.get("pages_read", 0)
            # Only clear the gap when both reads agree on the total and their union covers it.
            result["truncated"] = not (isinstance(count, int) and newest.get("count") == count
                                       and len(merged) >= count)
    result["retrieved_count"] = len(result["results"])
    result["results"] = [dict(row, history_flags=flags(row.get("description"))) for row in result["results"]]
    return result


def build_history(target, limit=100):
    cluster = resolve(target)
    cid, date, name = cluster["id"], cluster.get("date_filed"), cluster.get("case_name")
    docket_id = object_id(cluster.get("docket_id") or cluster.get("docket"))
    docket = {"status": "unavailable", "reason": "Missing linked docket or decision date", "results": []}
    origin = {"cluster_id": cid, "case_name": name, "date_filed": date, "input": target}
    if docket_id and date:
        try:
            meta = request_json(f"{BASE}/api/rest/v4/dockets/{docket_id}/")
            court_id = object_id(meta.get("court_id") or meta.get("court"))
            court = request_json(f"{BASE}/api/rest/v4/courts/{court_id}/") if court_id else {}
            origin.update(court_id=court_id, jurisdiction=court.get("jurisdiction"), docket_number=meta.get("docket_number"))
            if not court_id or not court.get("jurisdiction"):
                docket.update(status="unavailable", reason="Court jurisdiction metadata unavailable; verify the court directly")
            elif court_id == "scotus" or court.get("jurisdiction") not in {"F", "FD", "FB", "FBP", "FS"}:
                docket.update(status="not_applicable", reason="No supported federal PACER docket; use the appropriate official court record")
            else:
                docket = dict(entries(docket_id, date, limit), status="checked", docket_id=docket_id, resolved_by="cluster_link")
                if not docket["results"]:
                    core = docket_core(meta.get("docket_number"))
                    if core:
                        candidates = search(f"docketNumber:{phrase(core)}", type="d", court=court_id, limit=5)
                        docket["recap_search"] = candidates
                        matching = [r for r in candidates["results"] if object_id(r.get("court_id")) == court_id
                                    and docket_core(r.get("docketNumber")) == core
                                    and object_id(r.get("docket_id")) != docket_id and r.get("docket_id")]
                        ids = {object_id(r["docket_id"]) for r in matching}
                        if len(ids) == 1 and not candidates.get("truncated"):
                            alternate = ids.pop()
                            replacement = entries(alternate, date, limit)
                            docket.update(replacement, docket_id=alternate, resolved_by="recap_search")
                        elif ids or candidates.get("truncated"):
                            docket.update(status="partial", reason="Ambiguous or truncated RECAP docket search; inspect candidates before choosing a twin")
                        elif candidates["status"] != "checked":
                            docket.update(status="partial", reason="RECAP twin search unavailable")
                    else:
                        docket.update(status="partial", reason="Empty linked docket and no supported docket-number core for twin search")
                if docket.get("truncated"):
                    reason = ("Entry cap reached; oldest and newest entries read, intervening post-decision entries remain unchecked"
                              if docket.get("read_both_ends") else
                              "Entry cap reached; newest-entry read unavailable, later post-decision entries remain unchecked")
                    docket.update(status="partial", reason=reason)
                docket["flagged_entries"] = [r for r in docket["results"] if r["history_flags"]]
        except (OSError, ValueError, KeyError) as exc:
            docket.update(status="unavailable", reason=str(exc))
    later = {"status": "skipped", "reason": "Missing caption or decision date", "results": []}
    if date and name_query(name):
        later = search(name_query(name), limit=min(limit, 100), filed_after=date, order_by="dateFiled asc")
        later["results"] = dedupe_decisions([opinion_row(r) for r in later["results"]
                                             if str(r.get("cluster_id")) != str(cid) and str(r.get("dateFiled") or "") > date])
        for row in later["results"]:
            row["relationship"] = "unconfirmed_same_litigation_candidate"
            row["reviewing_jurisdiction"] = "requires_manual_verification"
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "origin": origin,
            "docket": docket, "later_opinions": later, "limitations": LIMITS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", help='Reporter citation or inspected "cluster:ID"')
    parser.add_argument("--limit", type=int, default=100,
                        help="Oldest-entry cap (default: 100); capped dockets also read max(20, limit // 2) newest entries")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")
    try:
        data = build_history(args.case, args.limit)
    except (OSError, ValueError, KeyError) as exc:
        print(f"case_history: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(str(args.output))
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
