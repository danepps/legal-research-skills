#!/usr/bin/env python3
"""Offline regression tests for the build-library helpers (Codex review of
2026-10-19, findings CLAUDE-08, -13, -14, -15, -16, -17). Every HTTP call is
mocked by replacing urllib.request.urlopen inside each module; no credentials,
no network. Standalone-assert style: prints [ok]/[FAIL] lines, exits 1 on any."""
import io
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResp:
    def __init__(self, body, status=200, headers=None):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status
        self.headers = headers or {}

    def read(self, n=-1):
        return self._body

    def getheader(self, k, default=None):
        return self.headers.get(k, default)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeHTTP:
    """urlopen stand-in: route(method, url, body) -> FakeResp | raises."""

    def __init__(self, route):
        self.route = route
        self.calls = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = req.get_method() if hasattr(req, "get_method") else "GET"
        body = req.data if hasattr(req, "data") else None
        self.calls.append((method, url))
        return self.route(method, url, body)


def http_error(url, code):
    return urllib.error.HTTPError(url, code, "err", {}, None)


# ======================================================== CLAUDE-08: attach_pdf
print("CLAUDE-08 attach_pdf.py: deferred config, group libraries, readback")
ap = load("attach_pdf")

env = {k: v for k, v in os.environ.items() if not k.startswith("ZOTERO_")}
with tempfile.TemporaryDirectory() as td:
    env["HOME"] = td  # no ~/.claude.json either
    p = subprocess.run([sys.executable, os.path.join(HERE, "attach_pdf.py"), "--help"],
                       env=env, capture_output=True, text=True)
check(p.returncode == 0 and "--library" in p.stdout,
      "--help works with no Zotero configuration at all (exit %d)" % p.returncode)

lib = ap.resolve_library(environ={"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "4242",
                                  "ZOTERO_LIBRARY_TYPE": "group"})
check(lib["type"] == "group" and lib["id"] == "4242" and lib["key"] == "k",
      "env group config resolves to group:4242")
check(ap.base_url(lib["type"], lib["id"]) == "https://api.zotero.org/groups/4242",
      "group library posts to /groups/<id>")
lib = ap.resolve_library(environ={"ZOTERO_API_KEY": "k", "ZOTERO_USER_ID": "7"})
check(lib["type"] == "user" and ap.base_url(lib["type"], lib["id"]).endswith("/users/7"),
      "ZOTERO_USER_ID still means the personal library")

with tempfile.TemporaryDirectory() as td:
    cj = os.path.join(td, "claude.json")
    with open(cj, "w") as f:  # the shape setup.py zotero writes
        json.dump({"mcpServers": {
            "zotero": {"command": "uvx", "args": ["zotero-mcp"],
                       "env": {"ZOTERO_API_KEY": "cfgkey", "ZOTERO_LIBRARY_ID": "12",
                               "ZOTERO_LIBRARY_TYPE": "user"}},
            "zotero-group": {"command": "uvx", "args": ["zotero-mcp"],
                             "env": {"ZOTERO_API_KEY": "cfgkey", "ZOTERO_LIBRARY_ID": "99",
                                     "ZOTERO_LIBRARY_TYPE": "group"}},
            "other": {"command": "npx", "args": ["x"]}}}, f)
    lib = ap.resolve_library(environ={}, claude_json=cj)
    check(lib == {"key": "cfgkey", "type": "user", "id": "12", "source": lib["source"]}
          and "mcpServers['zotero']" in lib["source"],
          "no env -> default MCP server entry 'zotero' from ~/.claude.json")
    lib = ap.resolve_library(server="zotero-group", environ={}, claude_json=cj)
    check(lib["type"] == "group" and lib["id"] == "99", "--server picks the named entry")
    lib = ap.resolve_library(environ={"ZOTERO_MCP_SERVER": "zotero-group"}, claude_json=cj)
    check(lib["type"] == "group" and lib["id"] == "99", "ZOTERO_MCP_SERVER picks the entry")
    lib = ap.resolve_library(library="group:55", environ={}, claude_json=cj)
    check(lib["type"] == "group" and lib["id"] == "55" and lib["key"] == "cfgkey",
          "--library group:<ID> overrides the destination, key still from config")
    try:
        ap.resolve_library(server="nope", environ={}, claude_json=cj)
        check(False, "unknown --server raises ConfigError")
    except ap.ConfigError as e:
        check("'nope'" in str(e) and "zotero-group" in str(e),
              "unknown --server raises ConfigError naming the available entries")
    try:
        ap.resolve_library(environ={}, claude_json=os.path.join(td, "missing.json"))
        check(False, "no config anywhere raises ConfigError")
    except ap.ConfigError as e:
        check("ZOTERO_API_KEY" in str(e), "no config anywhere raises ConfigError with guidance")
    try:
        ap.resolve_library(library="team:1", environ={}, claude_json=cj)
        check(False, "bad library type rejected")
    except ap.ConfigError:
        check(True, "bad library type rejected")

# full upload flow against a fake Zotero, group destination
PDF = b"%PDF-1.4 fake body"
import hashlib
MD5 = hashlib.md5(PDF).hexdigest()


def make_zotero(readback):
    def route(method, url, body):
        if url == "https://api.zotero.org/groups/77/items/PARENT01" and method == "GET":
            return FakeResp({"data": {"title": "A Title", "date": "2020",
                                      "creators": [{"lastName": "Doe"}]}})
        if url == "https://api.zotero.org/groups/77/items" and method == "POST":
            return FakeResp({"successful": {"0": {"key": "ATTACH01"}}, "failed": {}})
        if url == "https://api.zotero.org/groups/77/items/ATTACH01/file" and method == "POST":
            if b"upload=" in (body or b""):
                return FakeResp(b"", status=204)
            return FakeResp({"url": "https://storage.example/up", "contentType": "multipart/form-data",
                             "prefix": "--p\r\n", "suffix": "\r\n--p--", "uploadKey": "UK"})
        if url == "https://storage.example/up":
            return FakeResp(b"", status=201)
        if url == "https://api.zotero.org/groups/77/items/ATTACH01" and method == "GET":
            return FakeResp(readback)
        raise AssertionError(f"unexpected request {method} {url}")
    return route


def run_attach(readback, extra=()):
    fake = FakeHTTP(make_zotero(readback))
    ap.urllib.request.urlopen = fake
    out, err = io.StringIO(), io.StringIO()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(PDF)
        path = f.name
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                ap.main(["--item", "PARENT01", "--file", path, "--library", "group:77",
                         *extra])
                rc = 0
            except SystemExit as e:
                rc = 0 if e.code in (None, 0) else (1 if isinstance(e.code, str) else e.code)
                if isinstance(e.code, str):
                    out.write(e.code)
    finally:
        os.unlink(path)
    return rc, out.getvalue() + err.getvalue(), fake.calls


good = {"key": "ATTACH01", "library": {"type": "group", "id": 77},
        "data": {"key": "ATTACH01", "itemType": "attachment", "parentItem": "PARENT01",
                 "contentType": "application/pdf", "md5": MD5}}
os.environ["ZOTERO_API_KEY"] = "k"
rc, text, calls = run_attach(good)
check(rc == 0 and any(l.startswith("PASS PARENT01") for l in text.splitlines())
      and "readback: parent, library, application/pdf, md5 all verified" in text
      and "destination group:77" in text,
      "group upload with matching readback -> PASS (exit 0), destination announced")
check(all("/groups/77/" in u or u.startswith("https://storage") for _, u in calls),
      "every API request went to /groups/77/")
check(("GET", "https://api.zotero.org/groups/77/items/ATTACH01") in calls,
      "the attachment was read back after registering")

bad_parent = json.loads(json.dumps(good))
bad_parent["data"]["parentItem"] = "OTHER999"
rc, text, _ = run_attach(bad_parent)
check(rc != 0 and "FAIL" in text and "OTHER999" in text,
      "readback with a different parent -> FAIL, non-zero exit")

bad_lib = json.loads(json.dumps(good))
bad_lib["library"] = {"type": "user", "id": 77}
rc, text, _ = run_attach(bad_lib)
check(rc != 0 and "expected group:77" in text,
      "readback stored in a different library -> FAIL naming the expected destination")

bad_md5 = json.loads(json.dumps(good))
bad_md5["data"]["md5"] = "0" * 32
rc, text, _ = run_attach(bad_md5)
check(rc != 0 and "md5" in text, "readback md5 mismatch -> FAIL")
del os.environ["ZOTERO_API_KEY"]

# ======================================================= CLAUDE-15: author match
print("CLAUDE-15 check_source.py: author name boundaries + fields compared")
cs = load("check_source")
cs.SLEEP = 0
item = {"title": "A Book", "date": "2010",
        "creators": [{"creatorType": "author", "lastName": "Smith"}]}
ok, probs, compared = cs.compare(item, {"source": "x", "title": "A Book",
                                        "authors": ["Jane Smithson"], "year": 2010})
check(not ok and any("Smith" in p for p in probs), "claimed Smith vs retrieved Smithson -> mismatch")
ok, _, compared = cs.compare(item, {"source": "x", "title": "A Book",
                                    "authors": ["John Smith"], "year": 2010})
check(ok and compared == ["title", "year", "authors"], "claimed Smith vs John Smith -> match, all three fields compared")
ok, _, _ = cs.compare(item, {"source": "x", "title": "A Book", "authors": ["Smith, John"], "year": 2010})
check(ok, "inverted 'Smith, John' still matches")
vdb = {"title": "T", "date": "2010", "creators": [{"creatorType": "author", "lastName": "van der Berg"}]}
ok, _, _ = cs.compare(vdb, {"source": "x", "title": "T", "authors": ["Anna van der Berg"], "year": 2010})
check(ok, "multi-token surname matches when every token is present")
ok, _, _ = cs.compare(vdb, {"source": "x", "title": "T", "authors": ["Anna Berg"], "year": 2010})
check(not ok, "multi-token surname does not match on one token")
ok, _, compared = cs.compare(item, {"source": "x", "title": "A Book", "authors": [], "year": 2010})
check(ok and compared == ["title", "year"], "source without authors: match, but authors not in fields_compared")
ok, _, compared = cs.compare(item, {"source": "x", "title": "A Book", "authors": ["John Smith"], "year": None})
check(ok and compared == ["title", "authors"], "source without year: year not in fields_compared")

# ===================================================== CLAUDE-16: unavailable
print("CLAUDE-16 check_source.py: lookup unavailable vs searched/no match")


def route_fail(method, url, body):
    raise urllib.error.URLError("connection refused")


cs.urllib.request.urlopen = FakeHTTP(route_fail)
doi_item = {"title": "An Article", "date": "2020", "DOI": "10.1000/xyz", "creators": []}
r = cs.verify_item(doi_item)
check(r["verdict"] == "UNAVAILABLE", "crossref transport failure -> UNAVAILABLE, not UNRESOLVED (got %s)" % r["verdict"])
check(r["sources_unavailable"] == ["crossref_resolve"] and r["sources_searched"] == [],
      "sources attempted/unavailable recorded")
check(any("connection refused" in d for d in r["detail"]) and not any("not found" in d for d in r["detail"]),
      "detail carries the error and never says 'not found'")

cs.urllib.request.urlopen = FakeHTTP(lambda m, u, b: FakeResp(b"<html>oops", status=200))
r = cs.verify_item(doi_item)
check(r["verdict"] == "UNAVAILABLE" and any("JSON" in d for d in r["detail"]),
      "non-JSON body -> UNAVAILABLE with the JSON error")

cs.urllib.request.urlopen = FakeHTTP(lambda m, u, b: (_ for _ in ()).throw(http_error(u, 404)))
r = cs.verify_item(doi_item)
check(r["verdict"] == "UNRESOLVED" and r["sources_searched"] == ["crossref_resolve"],
      "crossref 404 -> UNRESOLVED (searched, no match)")

cs.urllib.request.urlopen = FakeHTTP(lambda m, u, b: (_ for _ in ()).throw(http_error(u, 503)))
r = cs.verify_item(doi_item)
check(r["verdict"] == "UNAVAILABLE" and any("HTTP 503" in d for d in r["detail"]),
      "crossref 503 -> UNAVAILABLE with the status")


def route_isbn_mixed(method, url, body):
    if "openlibrary.org/isbn/" in url:
        raise http_error(url, 404)          # searched, no match
    if "openlibrary.org/search" in url:
        return FakeResp({"docs": []})       # searched, no match
    raise urllib.error.URLError("down")     # googlebooks/harvard/loc unavailable


cs.urllib.request.urlopen = FakeHTTP(route_isbn_mixed)
r = cs.verify_item({"title": "Book", "date": "2000", "ISBN": "9780306406157", "creators": []})
check(r["verdict"] == "UNAVAILABLE" and len(r["sources_searched"]) == 2 and len(r["sources_unavailable"]) == 3,
      "ISBN: 2 searched + 3 unavailable -> UNAVAILABLE, both lists kept")


def route_isbn_none(method, url, body):
    if "openlibrary.org/isbn/" in url:
        raise http_error(url, 404)
    if "openlibrary.org/search" in url:
        return FakeResp({"docs": []})
    if "googleapis" in url:
        return FakeResp({"totalItems": 0})
    if "harvard" in url:
        return FakeResp({"items": {}})
    if "loc.gov" in url:
        return FakeResp({"results": []})
    raise AssertionError(url)


cs.urllib.request.urlopen = FakeHTTP(route_isbn_none)
r = cs.verify_item({"title": "Book", "date": "2000", "ISBN": "9780306406157", "creators": []})
check(r["verdict"] == "UNRESOLVED" and len(r["sources_searched"]) == 5,
      "ISBN: all five searched with no match -> UNRESOLVED")

cs.urllib.request.urlopen = FakeHTTP(lambda m, u, b: FakeResp(
    {"message": {"title": ["An Article"], "author": [], "issued": {"date-parts": [[2020]]}}}))
r = cs.verify_item(doi_item)
check(r["verdict"] == "PASS" and r["fields_compared"] == ["title", "year"]
      and "no authors" in r["detail"][-1],
      "PASS records fields_compared and says the source supplied no authors")

# ================================================ CLAUDE-13 / -17: Zotero fetch
print("CLAUDE-13/17 check_source.py: pagination and key reconciliation")
cs.verify_item = lambda it: {"key": it.get("key", ""), "title": it.get("title", ""), "identifier": "",
                             "verdict": "PASS", "matched_source": "", "detail": []}
cs.zotero_creds = lambda server=None, claude_json=None: ("k", "user", "1")


def rec(k, t="book"):
    return {"data": {"key": k, "itemType": t, "title": "T " + k}}


def run_main(argv):
    sys.argv = ["check_source.py"] + argv
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cs.main()
    return rc, out.getvalue(), err.getvalue()


def paged(records, total_header=True, link=False, lie_total=None):
    def route(method, url, body):
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        start, limit = int(q.get("start", 0)), int(q.get("limit", 100))
        page = records[start:start + limit]
        h = {}
        if total_header:
            h["Total-Results"] = str(lie_total if lie_total is not None else len(records))
        if link and start + limit < len(records):
            base = url.split("?", 1)[0]
            h["Link"] = f'<{base}?start={start + limit}&limit={limit}>; rel="next", <{base}?start=0>; rel="first"'
        return FakeResp(page, headers=h)
    return route


coll = [rec(f"K{i:04d}") for i in range(250)]
fake = FakeHTTP(paged(coll))
cs.urllib.request.urlopen = fake
rc, out, err = run_main(["--collection", "COLL1", "--json"])
check(rc == 0 and len(json.loads(out)) == 250 and len(fake.calls) == 3,
      "250-item collection: 3 requests via start/limit + Total-Results, all 250 verified (got %d calls)" % len(fake.calls))
check("fetched 250" in err, "stderr reports the fetched count")

fake = FakeHTTP(paged(coll, total_header=False, link=True))
cs.urllib.request.urlopen = fake
rc, out, err = run_main(["--collection", "COLL1", "--json"])
check(rc == 0 and len(json.loads(out)) == 250 and len(fake.calls) == 3,
      "250-item collection: Link rel=next followed without Total-Results")

fake = FakeHTTP(paged(coll, total_header=False, link=False))
cs.urllib.request.urlopen = fake
rc, out, err = run_main(["--collection", "COLL1", "--json"])
check(rc == 0 and len(json.loads(out)) == 250 and len(fake.calls) == 3,
      "250-item collection: no headers at all -> loop until a short page")

fake = FakeHTTP(paged(coll[:100], lie_total=250))
cs.urllib.request.urlopen = fake
rc, out, err = run_main(["--collection", "COLL1", "--json"])
check(rc == 2 and "incomplete" in err and "250" in err and "100" in err,
      "server declares 250 but returns 100 -> exit 2, incomplete, nothing verified")

fake = FakeHTTP(paged([rec(f"K{i:04d}") for i in range(100)]))
cs.urllib.request.urlopen = fake
rc, out, err = run_main(["--collection", "COLL1", "--json"])
check(rc == 0 and len(json.loads(out)) == 100 and len(fake.calls) == 1,
      "exactly 100 items with Total-Results=100 -> one request, all verified")


def keyed(records, extra=None):
    def route(method, url, body):
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        want = q["itemKey"].split(",")
        page = [r for r in records if r["data"]["key"] in want] + (extra or [])
        return FakeResp(page, headers={"Total-Results": str(len(page))})
    return route


cs.urllib.request.urlopen = FakeHTTP(keyed([]))
rc, out, err = run_main(["--keys", "ITEM1234"])
check(rc == 2 and "ITEM1234" in err and "not returned" in err,
      "requested ITEM1234, empty response -> exit 2 naming the missing key")

cs.urllib.request.urlopen = FakeHTTP(keyed([rec("AAAA0001"), rec("BBBB0002")]))
rc, out, err = run_main(["--keys", "AAAA0001,BBBB0002", "--json"])
check(rc == 0 and [r["key"] for r in json.loads(out)] == ["AAAA0001", "BBBB0002"],
      "two requested keys, both returned -> verified in request order")

rc, out, err = run_main(["--keys", "AAAA0001,CCCC0003", "--json"])
check(rc == 2 and "CCCC0003" in err and "AAAA0001" not in err.split("not returned")[1].split(";")[0].replace("CCCC0003", ""),
      "one of two keys missing -> exit 2 naming only the missing one")

cs.urllib.request.urlopen = FakeHTTP(keyed([rec("AAAA0001"), rec("AAAA0001")]))
rc, out, err = run_main(["--keys", "AAAA0001", "--json"])
check(rc == 2 and "more than once" in err, "a key returned twice -> exit 2")

cs.urllib.request.urlopen = FakeHTTP(keyed([rec("AAAA0001")], extra=[rec("ZZZZ9999")]))
rc, out, err = run_main(["--keys", "AAAA0001", "--json"])
check(rc == 2 and "unrequested" in err, "an unrequested record in the response -> exit 2")

cs.urllib.request.urlopen = FakeHTTP(lambda m, u, b: FakeResp({"error": "nope"}))
rc, out, err = run_main(["--keys", "AAAA0001", "--json"])
check(rc == 2 and "array" in err, "a JSON object instead of an array -> exit 2")

cs.urllib.request.urlopen = FakeHTTP(lambda m, u, b: FakeResp([{"data": {"itemType": "book"}}]))
rc, out, err = run_main(["--keys", "AAAA0001", "--json"])
check(rc == 2 and "malformed" in err, "a record without a key -> exit 2")

cs.urllib.request.urlopen = FakeHTTP(lambda m, u, b: (_ for _ in ()).throw(http_error(u, 403)))
rc, out, err = run_main(["--keys", "AAAA0001", "--json"])
check(rc == 2 and "HTTP 403" in err, "HTTP error from Zotero -> exit 2 with the status")

cs.urllib.request.urlopen = FakeHTTP(keyed([rec("AAAA0001"), rec("NOTE0001", "note")]))
rc, out, err = run_main(["--keys", "AAAA0001,NOTE0001", "--json"])
check(rc == 0 and [r["key"] for r in json.loads(out)] == ["AAAA0001"] and "skipping" in err,
      "a requested note is accounted for, then skipped with a notice")

# ================================================== CLAUDE-14: inventory has_pdf
print("CLAUDE-14 library_inventory.py: has_pdf only from a real PDF attachment")
li = load("library_inventory")
li.api_key = lambda: "k"
TOP = [
    {"data": {"key": "NOTEONLY", "title": "Has only a note", "creators": [], "date": "2001"},
     "meta": {"numChildren": 1}},
    {"data": {"key": "WITHPDF1", "title": "Has a pdf", "creators": [], "date": "2002"},
     "meta": {"numChildren": 1}},
    {"data": {"key": "NOTEPDF1", "title": "Has a note and a pdf", "creators": [], "date": "2003"},
     "meta": {"numChildren": 2}},
    {"data": {"key": "HTMLONLY", "title": "Has a snapshot only", "creators": [], "date": "2004"},
     "meta": {"numChildren": 1}},
    {"data": {"key": "NOCHILD1", "title": "Nothing", "creators": [], "date": "2005"},
     "meta": {"numChildren": 0}},
]
ATT = [
    {"data": {"key": "A1", "itemType": "attachment", "parentItem": "WITHPDF1", "contentType": "application/pdf"}},
    {"data": {"key": "A2", "itemType": "attachment", "parentItem": "NOTEPDF1", "contentType": "application/pdf"}},
    {"data": {"key": "A3", "itemType": "attachment", "parentItem": "HTMLONLY", "contentType": "text/html"}},
]


def route_lib(method, url, body):
    if "/items/top?" in url:
        return FakeResp(TOP)
    if "/items?" in url and "itemType=attachment" in url:
        return FakeResp(ATT)
    raise AssertionError(url)


fake = FakeHTTP(route_lib)
li.urllib.request.urlopen = fake
sys.argv = ["library_inventory.py", "--group", "1", "--json"]
out = io.StringIO()
with redirect_stdout(out):
    li.main()
rows = {r["key"]: r for r in json.loads(out.getvalue())}
check(rows["NOTEONLY"]["has_pdf"] is False and rows["NOTEONLY"]["child_count"] == 1,
      "note-only child: has_pdf False, child_count 1")
check(rows["WITHPDF1"]["has_pdf"] is True, "pdf child: has_pdf True")
check(rows["NOTEPDF1"]["has_pdf"] is True and rows["NOTEPDF1"]["child_count"] == 2,
      "note + pdf: has_pdf True, child_count 2")
check(rows["HTMLONLY"]["has_pdf"] is False, "html snapshot only: has_pdf False")
check(rows["NOCHILD1"]["has_pdf"] is False and rows["NOCHILD1"]["child_count"] == 0, "no children: both false/0")
check(any("itemType=attachment" in u for _, u in fake.calls) and len(fake.calls) == 2,
      "attachments fetched with one extra listing, not one request per item")
check(all("/groups/1/" in u for _, u in fake.calls), "group library addressed as /groups/1")

sys.argv = ["library_inventory.py", "--group", "1"]
out = io.StringIO()
with redirect_stdout(out):
    li.main()
check("(3 without a PDF attachment)" in out.getvalue(), "text summary counts items without a PDF")

print()
if fails:
    print(f"FAILED: {fails} check(s)")
    sys.exit(1)
print("all checks passed")
