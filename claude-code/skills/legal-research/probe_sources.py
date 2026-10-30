#!/usr/bin/env python3
"""Probe candidate URLs for a source BEFORE an agent spends a fetch (and its reasoning) on them.

Why this exists (2026-10-27): the first live cite-check run with the support pass spent about
58,000 subagent tokens per agent, six times the budget ladder's estimate, and the report's own
"couldn't check" section showed where it went: agents guessing repository URLs one at a time,
reasoning between each 403 and 404, on sources that ended unverifiable anyway. Testing every
candidate in one deterministic call costs no model tokens, and a host that is known never to
serve a scripted fetch is marked without a network call.

Usage:
    python3 probe_sources.py <url> [<url> ...]        # JSON report to stdout
    python3 probe_sources.py --urls-file FILE         # one URL per line
    options: --no-wayback   skip the Wayback Machine lookup for unreachable URLs
             --timeout N    seconds per request (default 15)
             --text         one line per URL instead of JSON

Per URL the report gives:
    fetchable     true only for a 2xx response that is not a sign-in page on a host that is
                  not subscription-only; fetch these (with fetch_page.py) and nothing else
    status        ok | blocked | not-found | login-wall | subscription | rate-limited |
                  server-error | unreachable | invalid | http-<code>
    http_status   the response code, when there was one
    final_url     after redirects
    content_type  from the response header, or application/pdf when the body starts %PDF-
    host_rule     the known behaviour of this host, when one applies (see HOST_RULES)
    wayback       {"url", "timestamp"} for the closest Wayback Machine snapshot of a URL that
                  was not fetchable, when one exists; fetch the snapshot instead
    unlock        what would make the source readable when nothing here is

Rules the agents follow with it: every URL marked not fetchable counts as one attempt without a
fetch; a URL marked blocked, not-found or subscription is never fetched or retried with a
variant; no candidate fetchable and no snapshot means the source is unverifiable, reported with
`unlock`. Stdlib only. Part of the legal-research skill's shared toolbox.

Exit codes: 0 = probe ran (read the per-URL results); 2 = usage error.
"""
from __future__ import annotations

import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 15
MAX_URLS = 20
SNIFF_BYTES = 4096
USER_AGENT = "Mozilla/5.0 (Macintosh) legal-research-skill/1.0"
WAYBACK_API = "https://archive.org/wayback/available?url="

# Hosts with a known, stable behaviour toward scripted fetches.
#   subscription: paywalled regardless of client; marked without a network call, no Wayback.
#   bot-block:    serves 403 (or a challenge page) to scripts; probed once, never with variants.
#   login:        the "page" is a sign-in form; probed once, never with variants.
# Each entry: (host regex, kind, label, unlock path)
_ZOTERO = "attach the PDF to the source's Zotero item and re-run"
HOST_RULES = [
    (r"(^|\.)heinonline\.org$", "subscription", "HeinOnline",
     "open the article on HeinOnline through your library and " + _ZOTERO),
    (r"(^|\.)jstor\.org$", "subscription", "JSTOR",
     "open the article on JSTOR through your library and " + _ZOTERO),
    (r"(^|\.)westlaw\.com$", "subscription", "Westlaw", "pull the document on Westlaw"),
    (r"(^|\.)lexis(nexis)?\.com$|(^|\.)lexis\.com$|(^|\.)advance\.lexis\.com$", "subscription",
     "Lexis", "pull the document on Lexis"),
    (r"(^|\.)ssrn\.com$", "bot-block", "SSRN",
     "download the PDF from SSRN in a browser and " + _ZOTERO + "; or use the journal's own site"),
    (r"(^|\.)bepress\.com$", "bot-block", "bepress Digital Commons",
     "download the PDF in a browser and " + _ZOTERO),
    (r"^digitalcommons\.", "bot-block", "bepress Digital Commons",
     "download the PDF in a browser and " + _ZOTERO),
    (r"^scholarship\.law\.", "bot-block", "bepress Digital Commons (law school repository)",
     "download the PDF in a browser and " + _ZOTERO),
    (r"^scholarlycommons\.law\.", "bot-block", "bepress Digital Commons (law school repository)",
     "download the PDF in a browser and " + _ZOTERO),
    (r"^ir\.lawnet\.fordham\.edu$", "bot-block", "bepress Digital Commons (Fordham)",
     "download the PDF in a browser and " + _ZOTERO),
    (r"^repository\.law\.umich\.edu$", "bot-block", "bepress Digital Commons (Michigan)",
     "download the PDF in a browser and " + _ZOTERO),
    (r"^openyls\.law\.yale\.edu$", "login", "openYLS (Yale sign-in)",
     "use yalelawjournal.org's own PDF, or sign in and " + _ZOTERO),
    (r"(^|\.)justia\.com$", "bot-block", "Justia",
     "read the same opinion on CourtListener or in the Caselaw Access Project"),
]
_LOGIN_URL = re.compile(r"(login|log-in|signin|sign-in|shibboleth|/sso\b|/auth\b|/idp/|openathens|ezproxy)", re.I)
_LOGIN_TITLE = re.compile(r"<title[^>]*>([^<]*)</title>", re.I | re.S)
_LOGIN_WORDS = re.compile(r"\b(log ?in|sign ?in|authenticate|access denied|just a moment|attention required)\b", re.I)


def host_rule(url: str):
    """The HOST_RULES entry for this URL's host, or None."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    for pattern, kind, label, unlock in HOST_RULES:
        if re.search(pattern, host):
            return {"kind": kind, "label": label, "unlock": unlock}
    return None


def _request(url: str, timeout: float, urlopen):
    """GET the first few KB (a Range request; servers that ignore it are read only to SNIFF_BYTES)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
        "Range": "bytes=0-%d" % (SNIFF_BYTES - 1),
    })
    with urlopen(req, timeout=timeout) as resp:
        code = getattr(resp, "status", None) or resp.getcode()
        head = resp.read(SNIFF_BYTES)
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        length = resp.headers.get("Content-Length") or resp.headers.get("Content-Range") or ""
        return code, resp.geturl(), ctype, length, head


def classify_code(code: int) -> str:
    if 200 <= code < 300:
        return "ok"
    if code in (401, 403):
        return "blocked"
    if code in (404, 410):
        return "not-found"
    if code == 429:
        return "rate-limited"
    if code >= 500:
        return "server-error"
    return "http-%d" % code


def looks_like_login(final_url: str, ctype: str, head: bytes) -> bool:
    if _LOGIN_URL.search(final_url or ""):
        return True
    if "html" not in ctype and head[:5] != b"<!DOC" and head[:5].lower() != b"<html":
        return False
    text = head.decode("utf-8", "replace")
    m = _LOGIN_TITLE.search(text)
    return bool(m and _LOGIN_WORDS.search(m.group(1)))


def wayback_lookup(url: str, timeout: float, urlopen):
    """Closest Wayback Machine snapshot, as {"url","timestamp"}, or None."""
    req = urllib.request.Request(WAYBACK_API + urllib.parse.quote(url, safe=""),
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read(65536).decode("utf-8", "replace"))
    except Exception as e:  # network, JSON, timeout: a missing snapshot, not an error worth a retry
        return None, "wayback lookup failed: %s" % (str(e)[:120] or type(e).__name__)
    closest = ((data or {}).get("archived_snapshots") or {}).get("closest") or {}
    if closest.get("available") and closest.get("url"):
        return {"url": closest["url"], "timestamp": closest.get("timestamp", "")}, None
    return None, None


def probe_one(url: str, timeout: float = TIMEOUT, wayback: bool = True, urlopen=urllib.request.urlopen) -> dict:
    out = {"url": url, "fetchable": False, "status": None, "http_status": None, "final_url": None,
           "content_type": None, "host_rule": None, "wayback": None, "unlock": None}
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        out["status"] = "invalid"
        out["unlock"] = "not a web address"
        return out
    rule = host_rule(url)
    if rule:
        out["host_rule"] = "%s (%s)" % (rule["label"], rule["kind"])
        out["unlock"] = rule["unlock"]
        if rule["kind"] == "subscription":
            out["status"] = "subscription"
            return out  # paywalled for every client: no request, no snapshot worth looking for
    try:
        code, final_url, ctype, length, head = _request(url, timeout, urlopen)
        out["http_status"] = code
        out["final_url"] = final_url
        if head[:5] == b"%PDF-":
            ctype = "application/pdf"
        out["content_type"] = ctype or None
        if length:
            out["content_length"] = length
        status = classify_code(code)
        if status == "ok" and (looks_like_login(final_url, ctype, head) or (rule and rule["kind"] == "login")):
            status = "login-wall"
        out["status"] = status
        out["fetchable"] = status == "ok"
    except urllib.error.HTTPError as e:
        out["http_status"] = e.code
        out["final_url"] = url
        out["status"] = classify_code(e.code)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as e:
        out["status"] = "unreachable"
        out["error"] = (str(getattr(e, "reason", e)) or type(e).__name__)[:160]
    if not out["fetchable"] and wayback:
        snap, err = wayback_lookup(url, timeout, urlopen)
        out["wayback"] = snap
        if err:
            out["wayback_error"] = err
    if not out["fetchable"] and not out["unlock"]:
        out["unlock"] = ("fetch the Wayback snapshot above" if out["wayback"] else
                         "find another copy (the journal's own site, the author's page) or " + _ZOTERO)
    return out


def probe(urls, timeout: float = TIMEOUT, wayback: bool = True, urlopen=urllib.request.urlopen) -> dict:
    results = [probe_one(u, timeout=timeout, wayback=wayback, urlopen=urlopen) for u in urls]
    return {
        "probed": len(results),
        "fetchable": [r["url"] for r in results if r["fetchable"]],
        "snapshots": [r["wayback"]["url"] for r in results if r.get("wayback")],
        "results": results,
    }


def text_lines(report: dict):
    for r in report["results"]:
        bits = [("FETCH " if r["fetchable"] else "skip  ") + r["status"]]
        if r.get("http_status"):
            bits.append(str(r["http_status"]))
        if r.get("host_rule"):
            bits.append(r["host_rule"])
        if r.get("wayback"):
            bits.append("wayback: " + r["wayback"]["url"])
        yield "%s  %s" % ("  ".join(bits), r["url"])


def main(argv) -> int:
    args = list(argv)
    wayback = True
    timeout = TIMEOUT
    as_text = False
    urls = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-wayback":
            wayback = False
        elif a == "--text":
            as_text = True
        elif a == "--timeout":
            if i + 1 >= len(args):
                print("usage: --timeout N", file=sys.stderr)
                return 2
            try:
                timeout = float(args[i + 1])
            except ValueError:
                print("usage: --timeout N (seconds)", file=sys.stderr)
                return 2
            i += 1
        elif a == "--urls-file":
            if i + 1 >= len(args):
                print("usage: --urls-file FILE", file=sys.stderr)
                return 2
            try:
                with open(args[i + 1], encoding="utf-8") as f:
                    urls.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
            except OSError as e:
                print("cannot read %s: %s" % (args[i + 1], e), file=sys.stderr)
                return 2
            i += 1
        elif a.startswith("--"):
            print("unknown option %s" % a, file=sys.stderr)
            return 2
        else:
            urls.append(a)
        i += 1
    seen = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]
    if not urls:
        print("usage: probe_sources.py <url> [<url> ...] | --urls-file FILE  [--no-wayback] [--timeout N] [--text]",
              file=sys.stderr)
        return 2
    if len(urls) > MAX_URLS:
        print("at most %d URLs per call (got %d): if a source really has that many candidates, "
              "the search is the problem" % (MAX_URLS, len(urls)), file=sys.stderr)
        return 2
    report = probe(urls, timeout=timeout, wayback=wayback)
    if as_text:
        print("\n".join(text_lines(report)))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
