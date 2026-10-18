#!/usr/bin/env python3
"""Deterministic case-citation lookup via CourtListener's free citation-lookup API.

Usage:
    python3 check_cite.py "347 U.S. 483" "Brown v. Board of Education, 347 U.S. 483 (1954)" ...

Prints a JSON array, one entry per citation the API recognized in the input:
    citation, found (bool), case_name, date_filed, url, ambiguous_matches, error

Exit codes: 0 = lookup ran (check per-citation "found"); 1 = API/network failure
(caller should fall back to web verification); 2 = usage error.

AUTH (the API requires it as of mid-2026): token resolved in order from
COURTLISTENER_API_TOKEN, COURTLISTENER_TOKEN, then the per-machine file
~/.config/courtlistener/token. Same account as scotus-syncer; token page:
https://www.courtlistener.com/profile/api-token/
To install:  mkdir -p ~/.config/courtlistener && echo "<token>" > ~/.config/courtlistener/token

Stdlib only. Part of the legal-research skill.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
TOKEN_FILE = os.path.expanduser("~/.config/courtlistener/token")


def get_token():
    for var in ("COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def main(argv):
    cites = [a.strip() for a in argv if a.strip()]
    if not cites:
        print('usage: check_cite.py "347 U.S. 483" ["<cite 2>" ...]', file=sys.stderr)
        return 2

    data = urllib.parse.urlencode({"text": " ;\n".join(cites)}).encode()
    req = urllib.request.Request(
        API, data=data, headers={"User-Agent": "legal-research-skill/1.0"}
    )
    token = get_token()
    if not token:
        print(
            "no CourtListener API token found (checked COURTLISTENER_API_TOKEN, "
            f"COURTLISTENER_TOKEN, {TOKEN_FILE}) — fall back to web verification. "
            "Get one at https://www.courtlistener.com/profile/api-token/",
            file=sys.stderr,
        )
        return 1
    req.add_header("Authorization", f"Token {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            results = json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read()[:300]
        print(
            f"API error HTTP {e.code}: {body!r} — fall back to web verification",
            file=sys.stderr,
        )
        return 1
    except Exception as e:  # network, timeout, bad JSON
        print(f"lookup failed ({e}) — fall back to web verification", file=sys.stderr)
        return 1

    out = []
    for r in results if isinstance(results, list) else []:
        row = {
            "citation": r.get("citation"),
            "found": r.get("status") == 200,
        }
        clusters = r.get("clusters") or []
        if clusters:
            c0 = clusters[0]
            row["case_name"] = c0.get("case_name")
            row["date_filed"] = c0.get("date_filed")
            if c0.get("absolute_url"):
                row["url"] = "https://www.courtlistener.com" + c0["absolute_url"]
            if len(clusters) > 1:
                row["ambiguous_matches"] = len(clusters)
        if r.get("error_message"):
            row["error"] = r["error_message"]
        out.append(row)

    print(json.dumps(out, indent=2))
    if not out:
        print(
            "note: API recognized no citations in the input — check the cite format "
            "or fall back to web verification",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
