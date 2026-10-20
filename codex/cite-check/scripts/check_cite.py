#!/usr/bin/env python3
"""Screen case-citation identity through CourtListener's citation-lookup API.

This does not verify quotations, holdings, proposition support, pinpoints, or
negative treatment. Treat every result as identity-only until the source text
is retrieved. Treat misses as unresolved and verify them directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
TOKEN_FILE = Path("~/.config/courtlistener/token").expanduser()


def lookup_state(result: dict) -> str:
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


def token() -> str | None:
    for name in ("COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="*", help="Citation strings or raw footnote text")
    parser.add_argument("--input-file", type=Path, help="UTF-8 citation or footnote text")
    args = parser.parse_args()
    chunks = [item.strip() for item in args.text if item.strip()]
    if args.input_file:
        try:
            chunks.append(args.input_file.read_text(encoding="utf-8"))
        except OSError as exc:
            parser.error(f"cannot read --input-file: {exc}")
    if not chunks:
        parser.error("provide citation text or --input-file")
    api_token = token()
    if not api_token:
        print(
            "No CourtListener token found; set COURTLISTENER_API_TOKEN or store it at "
            f"{TOKEN_FILE}. Verify directly instead.",
            file=sys.stderr,
        )
        return 1
    request = urllib.request.Request(
        API,
        data=urllib.parse.urlencode({"text": " ;\n".join(chunks)}).encode(),
        headers={
            "Authorization": f"Token {api_token}",
            "User-Agent": "codex-cite-check/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            results = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"CourtListener HTTP {exc.code}; verify directly.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"CourtListener lookup failed: {exc}; verify directly.", file=sys.stderr)
        return 1
    if not isinstance(results, list) or any(not isinstance(row, dict) for row in results):
        print("CourtListener returned an unexpected response shape; verify directly.", file=sys.stderr)
        return 1
    output = []
    for result in results:
        clusters = result.get("clusters") or []
        state = lookup_state(result)
        row = {
            "citation": result.get("citation"),
            "found": True if state == "matched" else False if state == "not_found_in_index" else None,
            "lookup_state": state,
            "lookup_status": result.get("status"),
            "verification_scope": "identity_only",
        }
        if clusters:
            first = clusters[0]
            row.update(
                {
                    "case_name": first.get("case_name"),
                    "date_filed": first.get("date_filed"),
                    "url": (
                        "https://www.courtlistener.com" + first["absolute_url"]
                        if first.get("absolute_url")
                        else None
                    ),
                }
            )
            if len(clusters) > 1:
                row["ambiguous_matches"] = len(clusters)
        if result.get("error_message"):
            row["error"] = result["error_message"]
        output.append(row)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
