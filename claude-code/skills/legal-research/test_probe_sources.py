#!/usr/bin/env python3
"""Offline checks for probe_sources.py — run: python3 test_probe_sources.py

No network: urlopen is replaced by a fake that answers from a table keyed by URL. Checks the
host rules (a subscription host is marked without any request; a bot-block host is probed once
and gets a Wayback lookup), the status mapping (2xx ok, 403 blocked, 404 not-found, 429, 5xx,
timeouts), PDF sniffing, sign-in page detection by URL and by title, the Wayback snapshot
parsing, the per-call URL cap, and the JSON shape agents rely on. Plain asserts, no pytest.
"""
import contextlib
import importlib.util
import io
import json
import os
import socket
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("probe_sources", os.path.join(HERE, "probe_sources.py"))
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


class FakeResp:
    def __init__(self, code, body=b"", ctype="text/html", url=None, length=None):
        self.status = code
        self._body = body
        self._url = url
        self.headers = {"Content-Type": ctype}
        if length:
            self.headers["Content-Length"] = length

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


WAYBACK_HIT = json.dumps({"archived_snapshots": {"closest": {
    "available": True, "url": "http://web.archive.org/web/20240101000000/https://x", "timestamp": "20240101000000", "status": "200"}}}).encode()
WAYBACK_MISS = json.dumps({"archived_snapshots": {}}).encode()

calls = []


def fake_urlopen(req, timeout=None):
    url = req.full_url
    calls.append(url)
    if url.startswith(ps.WAYBACK_API):
        target = url[len(ps.WAYBACK_API):]
        return FakeResp(200, WAYBACK_HIT if "ssrn" in target or "gone" in target else WAYBACK_MISS, "application/json", url)
    table = {
        "https://journal.example.edu/article.pdf": FakeResp(200, b"%PDF-1.4 ...", "application/octet-stream", "https://journal.example.edu/article.pdf", "123456"),
        "https://ok.example.org/page": FakeResp(200, b"<html><head><title>An Article</title></head><body>text</body></html>", "text/html", "https://ok.example.org/page"),
        "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1": urllib.error.HTTPError(url, 403, "Forbidden", {}, None),
        "https://repo.example.edu/gone.pdf": urllib.error.HTTPError(url, 404, "Not Found", {}, None),
        "https://busy.example.edu/x": urllib.error.HTTPError(url, 429, "Too Many", {}, None),
        "https://down.example.edu/x": urllib.error.HTTPError(url, 503, "Unavailable", {}, None),
        "https://slow.example.edu/x": socket.timeout("timed out"),
        "https://nodns.example.invalid/x": urllib.error.URLError("Name or service not known"),
        "https://proxy.example.edu/doc": FakeResp(200, b"<html>", "text/html", "https://login.example.edu/idp/profile?target=doc"),
        "https://wall.example.edu/doc": FakeResp(200, b"<html><head><title>Please log in - Library</title></head>", "text/html", "https://wall.example.edu/doc"),
        "https://digitalcommons.law.example.edu/cgi/viewcontent.cgi?article=1": urllib.error.HTTPError(url, 403, "Forbidden", {}, None),
        "https://openyls.law.yale.edu/handle/1": FakeResp(200, b"<html><head><title>Item</title></head>", "text/html", "https://openyls.law.yale.edu/handle/1"),
    }
    r = table.get(url)
    if r is None:
        raise AssertionError("unexpected URL %s" % url)
    if isinstance(r, Exception):
        raise r
    return r


def one(url, wayback=True):
    return ps.probe_one(url, timeout=1, wayback=wayback, urlopen=fake_urlopen)


print("host rules")
calls.clear()
r = one("https://heinonline.org/HOL/Page?handle=hein.journals/x")
check(r["status"] == "subscription" and r["fetchable"] is False and not calls, "HeinOnline: subscription, no request made")
check("HeinOnline" in r["host_rule"] and "Zotero" in r["unlock"], "HeinOnline: host rule and unlock path given")
r = one("https://www.jstor.org/stable/1")
check(r["status"] == "subscription" and not calls, "JSTOR: subscription without a request")
calls.clear()
r = one("https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1")
check(r["status"] == "blocked" and r["http_status"] == 403 and r["fetchable"] is False, "SSRN 403: blocked")
check(r["host_rule"].startswith("SSRN (bot-block)"), "SSRN: bot-block host rule attached (%s)" % r["host_rule"])
check(r["wayback"] and r["wayback"]["url"].startswith("http://web.archive.org/"), "SSRN: Wayback snapshot returned")
check(sum(1 for c in calls if not c.startswith(ps.WAYBACK_API)) == 1, "SSRN: probed exactly once")
r = one("https://digitalcommons.law.example.edu/cgi/viewcontent.cgi?article=1")
check(r["status"] == "blocked" and "Digital Commons" in r["host_rule"], "digitalcommons.* 403: blocked with the bepress rule")
r = one("https://openyls.law.yale.edu/handle/1")
check(r["status"] == "login-wall" and r["fetchable"] is False, "openYLS 200 is still a login wall by host rule")
check(ps.host_rule("https://www.example.edu/x") is None, "an unknown host has no rule")
check(ps.host_rule("https://notssrn.com/x") is None, "ssrn.com rule does not match notssrn.com")

print("status mapping")
r = one("https://journal.example.edu/article.pdf")
check(r["fetchable"] is True and r["status"] == "ok" and r["content_type"] == "application/pdf", "200 with %%PDF- body: fetchable, sniffed as PDF (%s)" % r["content_type"])
check(r.get("content_length") == "123456" and r["wayback"] is None, "ok result carries the length and skips Wayback")
r = one("https://ok.example.org/page")
check(r["fetchable"] is True and r["status"] == "ok", "200 HTML page: fetchable")
r = one("https://repo.example.edu/gone.pdf")
check(r["status"] == "not-found" and r["http_status"] == 404 and r["wayback"], "404: not-found, Wayback snapshot found")
check(r["unlock"] == "fetch the Wayback snapshot above", "404 with a snapshot: unlock points at the snapshot")
r = one("https://busy.example.edu/x")
check(r["status"] == "rate-limited", "429: rate-limited")
r = one("https://down.example.edu/x")
check(r["status"] == "server-error" and r["wayback"] is None and "Zotero" in r["unlock"], "503: server-error; no snapshot; generic unlock")
r = one("https://slow.example.edu/x")
check(r["status"] == "unreachable" and "timed out" in r.get("error", ""), "timeout: unreachable with the reason")
r = one("https://nodns.example.invalid/x")
check(r["status"] == "unreachable", "DNS failure: unreachable")
r = one("not a url")
check(r["status"] == "invalid" and r["fetchable"] is False, "garbage: invalid")
r = one("ftp://files.example.edu/x")
check(r["status"] == "invalid", "ftp: invalid (http/https only)")

print("sign-in detection")
r = one("https://proxy.example.edu/doc")
check(r["status"] == "login-wall" and r["final_url"].startswith("https://login."), "redirect to an IdP login URL: login-wall")
r = one("https://wall.example.edu/doc")
check(r["status"] == "login-wall", "200 page titled 'Please log in': login-wall")
check(ps.looks_like_login("https://x/doc", "application/pdf", b"%PDF-1.4 log in") is False, "a PDF body is never a login page")

print("--no-wayback")
calls.clear()
r = one("https://repo.example.edu/gone.pdf", wayback=False)
check(r["wayback"] is None and not any(c.startswith(ps.WAYBACK_API) for c in calls), "no Wayback request when disabled")

print("report shape")
rep = ps.probe(["https://ok.example.org/page", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1", "https://heinonline.org/x"],
               timeout=1, wayback=True, urlopen=fake_urlopen)
check(rep["probed"] == 3 and rep["fetchable"] == ["https://ok.example.org/page"], "fetchable list holds only the ok URL")
check(rep["snapshots"] == ["http://web.archive.org/web/20240101000000/https://x"], "snapshots list holds the Wayback URL")
check([r["status"] for r in rep["results"]] == ["ok", "blocked", "subscription"], "results keep input order")
check(all(set(("url", "fetchable", "status", "host_rule", "wayback", "unlock")) <= set(r) for r in rep["results"]), "every result carries the documented keys")
lines = list(ps.text_lines(rep))
check(lines[0].startswith("FETCH ok") and lines[1].startswith("skip  blocked  403") and "wayback:" in lines[1], "--text lines: %s" % lines[:2])

print("command line")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    rc = ps.main([])
check(rc == 2 and "usage" in err.getvalue(), "no URLs: usage error, exit 2")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    rc = ps.main(["https://a.example/%d" % i for i in range(ps.MAX_URLS + 1)])
check(rc == 2 and "at most" in err.getvalue(), "more than %d URLs: refused, exit 2" % ps.MAX_URLS)
err = io.StringIO()
with contextlib.redirect_stderr(err):
    rc = ps.main(["--timeout"])
check(rc == 2, "--timeout without a value: usage error")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    rc = ps.main(["--bogus", "https://a.example/"])
check(rc == 2 and "unknown option" in err.getvalue(), "unknown option: usage error")
# duplicates collapse before the cap is applied
out = io.StringIO()
real = ps.probe
ps.probe = lambda urls, **kw: {"probed": len(urls), "fetchable": [], "snapshots": [], "results": []}
with contextlib.redirect_stdout(out):
    rc = ps.main(["https://a.example/1", "https://a.example/1", "--no-wayback"])
ps.probe = real
check(rc == 0 and json.loads(out.getvalue())["probed"] == 1, "duplicate URLs are probed once")

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
