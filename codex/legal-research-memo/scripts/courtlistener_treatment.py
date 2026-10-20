#!/usr/bin/env python3
"""Produce a CourtListener citing-opinion treatment triage packet.

This is a discovery aid, not a citator. A signal hit must be opened and read
to determine which authority it concerns and what treatment it reflects. No
hits do not establish that a case remains good law, and citation recency does
not establish doctrinal force or dormancy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE = "https://www.courtlistener.com"
TOKEN_FILE = Path("~/.config/courtlistener/token").expanduser()
USER_AGENT = "codex-legal-research-memo/1.0"
HTML_TAG = re.compile(r"<[^>]+>")
SIGNALS = [
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in [
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
PROBE = (
    '(overruled OR abrogated OR "no longer good law" OR "superseded by statute" '
    'OR "declined to follow" OR "limited to its facts" OR "called into doubt" '
    'OR disapproved OR "receded from")'
)


# The identity helper is bundled in this skill as well as cite-check so manual
# installations remain self-contained.
from check_cite import (request_json, party_tokens, phrase, search, fetch_pages,
                        opinion_row, decision_key, dedupe_decisions)


def signal_names(text: str) -> list[str]:
    return [name for name, expression in SIGNALS if expression.search(text or "")]


def target_party_tokens(case_name):
    return party_tokens(case_name)


def mentions_target(snippet, case_name):
    return any(len(word) > 2 and re.search(rf"\b{re.escape(word)}\b", snippet, re.I)
               for word in party_tokens(case_name))


def name_phrases(name):
    full = re.sub(r"\s+", " ", name or "").strip()
    if not full:
        return []
    variants = [full, full.replace(" & ", " and ") if " & " in full else full.replace(" and ", " & ")]
    sides = party_tokens(full)
    if len(sides) == 2:
        variants.append(f"{sides[0]} v. {sides[1]}")
    return list(dict.fromkeys(variants))


def resolve_cluster(target):
    if target.casefold().startswith("cluster:"):
        cluster_id = int(target.split(":", 1)[1])
    else:
        data = request_json(f"{BASE}/api/rest/v4/citation-lookup/",
                            urllib.parse.urlencode({"text": target}).encode())
        candidates = {int(c["id"]) for row in data or [] for c in row.get("clusters") or []}
        if len(candidates) != 1:
            raise ValueError("citation unresolved or ambiguous; run check_cite.py --name, inspect candidates, then supply cluster:ID")
        cluster_id = candidates.pop()
    return request_json(f"{BASE}/api/rest/v4/clusters/{cluster_id}/")


def opinion_ids(cluster_id):
    url = f"{BASE}/api/rest/v4/opinions/?" + urllib.parse.urlencode({"cluster": cluster_id, "fields": "id,cluster"})
    page = fetch_pages(url, limit=100)
    if page["truncated"]:
        raise ValueError("opinion-ID listing truncated; graph coverage cannot be established")
    return [int(row["id"]) for row in page["results"]]


def route_packet(query, limit, *, date=None, probe=False):
    if not query:
        return {"status": "skipped", "reason": "Missing caption/date or opinion IDs", "results": [], "count": None}
    filters = {"filed_after": date} if date else {}
    if not probe:
        filters["order_by"] = "dateFiled desc"
    packet = search(query + (f" AND {PROBE}" if probe else ""), limit=limit, **filters)
    packet["results"] = [opinion_row(row) for row in packet["results"]]
    for row in packet["results"]:
        row["signals"] = signal_names(row["snippet"])
    packet["retrieved_rows"] = len(packet["results"])
    packet["distinct_decisions_retrieved"] = sum(decision_key(r) is not None for r in dedupe_decisions(packet["results"]))
    return packet


def combine_routes(routes, target_id):
    rows = []
    for route, packet in routes.items():
        for row in packet["results"]:
            if str(row.get("cluster_id")) != str(target_id):
                rows.append(dict(row, routes=[route]))
    return dedupe_decisions(rows)


def build_report(target: str, limit: int) -> dict[str, Any]:
    cluster = resolve_cluster(target)
    cluster_id, name, date = cluster["id"], cluster.get("case_name"), cluster.get("date_filed")
    graph_error = None
    try:
        ids = opinion_ids(cluster_id)
    except (OSError, ValueError) as exc:
        ids, graph_error = [], str(exc)
    graph_q = "cites:(" + " OR ".join(map(str, ids)) + ")" if ids else None
    name_q = "(" + " OR ".join(map(phrase, name_phrases(name))) + ")" if name and date else None
    recent, probes = {}, {}
    for route, query in (("graph", graph_q), ("name", name_q)):
        recent[route] = route_packet(query, limit, date=date if route == "name" else None)
        probes[route] = route_packet(query, limit, date=date if route == "name" else None, probe=True)
    if graph_error:
        for group in (recent, probes):
            group["graph"].update(status="unavailable", reason=graph_error)
    for packet in probes.values():
        for row in packet["results"]:
            row["mentions_target"] = mentions_target(row["snippet"], name)
        packet["results"].sort(key=lambda row: not row["mentions_target"])
    combined = combine_routes(recent, cluster_id)
    probe_rows = combine_routes(probes, cluster_id)
    for row in probe_rows:
        row["mentions_target"] = mentions_target(" ".join([row["snippet"], *row.get("additional_snippets", [])]), name)
    probe_rows.sort(key=lambda row: not row["mentions_target"])
    missing_graph = [row for row in combined if row.get("routes") == ["name"]]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(), "service": "CourtListener REST API v4",
        "target": {"input": target, "cluster_id": cluster_id, "case_name": name, "date_filed": date, "opinion_ids": ids},
        # Preserve the existing graph-only fields; combined results have explicit names.
        "recent_citing_query": graph_q, "total_citing_results": recent["graph"]["count"],
        "recent_citing_opinions": recent["graph"]["results"],
        "treatment_probe_query": probes["graph"].get("query"), "total_probe_results": probes["graph"]["count"],
        "treatment_probe": probes["graph"]["results"], "routes": recent, "probe_routes": probes,
        "combined_treatment_decisions": probe_rows,
        "combined_citing_decisions": combined,
        "distinct_case_count": sum(decision_key(row) is not None for row in combined),
        "unkeyed_rows": sum(decision_key(row) is None for row in combined),
        "name_rows_absent_from_retrieved_graph": missing_graph,
        "coverage": "bounded retrieval; distinct cases means decisions grouped by cluster or shared reporter citation + court + date, not whole litigations",
        "limitations": [
            "This is treatment triage, not Shepard's or KeyCite. No hits do not establish good law.",
            "Read each material hit: a phrase match or treatment signal can concern a different case.",
            "Per-route count is the API total; distinct_case_count counts only retrieved, identified decisions after cluster/URL and shared citation + court + date deduplication.",
            "Name-only rows are absent from the retrieved graph sample, not proof that the complete graph lacks an edge.",
            "Search can group multiple opinions in a cluster. Do not count majority and dissent as distinct cases.",
            "The newest citing date does not establish doctrinal force or dormancy.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", help='reporter citation or inspected "cluster:ID"')
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    try:
        report = build_report(args.case, args.limit)
    except (OSError, ValueError, KeyError) as exc:
        print(f"courtlistener_treatment: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(str(args.output))
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
