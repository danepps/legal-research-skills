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


def token() -> str | None:
    for name in ("COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value.strip()
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def request_json(url: str, data: bytes | None = None, timeout: int = 45) -> Any:
    headers = {"User-Agent": USER_AGENT}
    credential = token()
    if credential:
        headers["Authorization"] = f"Token {credential}"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def signal_names(text: str) -> list[str]:
    return [name for name, expression in SIGNALS if expression.search(text or "")]


def target_party_tokens(case_name: str | None) -> list[str]:
    if not case_name:
        return []
    normalized = re.sub(r"\s+", " ", case_name)
    pieces = re.split(r"\s+v\.?\s+", normalized, maxsplit=1, flags=re.IGNORECASE)
    return [
        re.sub(r"[^A-Za-z0-9'-]", "", piece.split()[0])
        for piece in pieces
        if piece.strip() and piece.split()
    ]


def mentions_target(snippet: str, case_name: str | None) -> bool:
    return any(
        len(token_value) > 2
        and re.search(rf"\b{re.escape(token_value)}\b", snippet, re.IGNORECASE)
        for token_value in target_party_tokens(case_name)
    )


def resolve_cluster(target: str) -> tuple[int, str | None] | None:
    if target.casefold().startswith("cluster:"):
        return int(target.split(":", 1)[1]), None
    payload = urllib.parse.urlencode({"text": target}).encode()
    rows = request_json(f"{BASE}/api/rest/v4/citation-lookup/", data=payload)
    for row in rows or []:
        for cluster in row.get("clusters") or []:
            return int(cluster["id"]), cluster.get("case_name")
    return None


def opinion_ids(cluster_id: int) -> list[int]:
    parameters = urllib.parse.urlencode(
        {"cluster": cluster_id, "fields": "id,cluster"}
    )
    data = request_json(f"{BASE}/api/rest/v4/opinions/?{parameters}")
    return [int(row["id"]) for row in data.get("results") or [] if row.get("id")]


def citing_search(
    ids: list[int],
    *,
    limit: int,
    treatment_probe: bool,
) -> tuple[str, int | None, list[dict[str, Any]]]:
    id_query = " OR ".join(str(identifier) for identifier in ids)
    query = f"cites:({id_query})"
    if treatment_probe:
        query += f" AND {PROBE}"
    parameters: dict[str, str] = {
        "type": "o",
        "q": query,
        "highlight": "on",
    }
    if not treatment_probe:
        parameters["order_by"] = "dateFiled desc"
    url = f"{BASE}/api/rest/v4/search/?{urllib.parse.urlencode(parameters)}"
    data = request_json(url)
    rows: list[dict[str, Any]] = []
    for result in (data.get("results") or [])[:limit]:
        snippet = HTML_TAG.sub(
            "",
            " ".join(
                str(opinion.get("snippet") or "")
                for opinion in result.get("opinions") or []
            ),
        )
        snippet = re.sub(r"\s+", " ", snippet).strip()
        rows.append(
            {
                "case_name": result.get("caseName"),
                "date_filed": result.get("dateFiled"),
                "court": result.get("court_citation_string") or result.get("court"),
                "citations": result.get("citation") or [],
                "absolute_url": result.get("absolute_url"),
                "signals": signal_names(snippet),
                "snippet": snippet[:500],
            }
        )
    return query, data.get("count"), rows


def build_report(target: str, limit: int) -> dict[str, Any]:
    resolved = resolve_cluster(target)
    if resolved is None:
        raise ValueError(f"could not resolve {target!r} to a CourtListener cluster")
    cluster_id, case_name = resolved
    ids = opinion_ids(cluster_id)
    if not ids:
        raise ValueError(f"cluster {cluster_id} has no indexed opinions")
    recent_query, total, recent = citing_search(ids, limit=limit, treatment_probe=False)
    probe_query, probe_total, probe_rows = citing_search(
        ids, limit=limit, treatment_probe=True
    )
    for row in probe_rows:
        row["mentions_target"] = mentions_target(str(row.get("snippet", "")), case_name)
    probe_rows.sort(key=lambda row: not row["mentions_target"])
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "service": "CourtListener REST API v4",
        "target": {
            "input": target,
            "cluster_id": cluster_id,
            "case_name": case_name,
            "opinion_ids": ids,
        },
        "recent_citing_query": recent_query,
        "total_citing_results": total,
        "recent_citing_opinions": recent,
        "treatment_probe_query": probe_query,
        "total_probe_results": probe_total,
        "treatment_probe": probe_rows,
        "limitations": [
            "This is citing-opinion and treatment-language triage, not Shepard's, KeyCite, or another citator.",
            "A signal may concern a different authority discussed in the same opinion; open and read every material hit.",
            "No signal hit does not establish the absence of negative treatment.",
            "The newest indexed citing date is coverage metadata only; it does not establish doctrinal force or dormancy.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", help='reporter citation or "cluster:ID"')
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")
    try:
        report = build_report(args.case, args.limit)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ) as exc:
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
