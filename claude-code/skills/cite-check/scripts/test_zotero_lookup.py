#!/usr/bin/env python3
"""Offline tests for zotero_lookup.py (no network: a fake urlopen serves a two-item library).

The matching cases are real ones from the first run on a 1,453-item library (2026-10-27):
a record whose subtitle the draft omits, a same-author article with two shared title words
that must NOT match, an article cite that must not take a same-title book, a volume + first
page match that carries a cite the ledger had split mid-title, and an edition-year difference
reported as a confirm note.
"""
import io
import json
import os
import sys
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zotero_lookup as zl  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


def item(key, itype, title, creators, year="", volume="", pages="", publication=""):
    return {"key": key, "data": {"key": key, "itemType": itype, "title": title,
                                 "creators": [{"creatorType": "author", "firstName": f, "lastName": l} for f, l in creators],
                                 "date": year, "volume": volume, "pages": pages, "publicationTitle": publication}}


LIB = [
    item("A1", "journalArticle", "Administering Crime", [("Rachel E.", "Barkow")], "2005", "52", "715-814", "UCLA Law Review"),
    item("B1", "book", "Justice Abandoned: How the Supreme Court Ignored the Constitution and Enabled Mass Incarceration", [("Rachel Elise", "Barkow")], "2025"),
    item("S1", "journalArticle", "The Fourth Amendment and Common Law", [("David A.", "Sklansky")], "2000", "100", "1739-1814"),
    item("F1", "book", "Plea Bargaining's Triumph: A History of Plea Bargaining in America", [("George", "Fisher")], "2004"),
    item("D1", "journalArticle", "Criminal Procedure, Footnote Four, and the Theory of Public Choice; or, Why Don't Legislatures Give a Damn About the Rights of the Accused?", [("Donald A.", "Dripps")], "1993", "44", "1079-1094"),
    item("G1", "book", "Caught: The Prison State and the Lockdown of American Politics", [("Marie", "Gottschalk")], "2014"),
    item("K1", "journalArticle", "Beyond <i>Carolene Products</i>", [("Bruce A.", "Ackerman")], "1985", "98", "713-746"),
    item("C1", "book", "Criminal Procedure", [("Wayne R.", "LaFave"), ("Jerold H.", "Israel"), ("Nancy J.", "King"), ("Orin S.", "Kerr")], "2016"),
]

print("cite parsing")
f = zl.parse_cite("See generally William J. Stuntz, The Pathological Politics of Criminal Law, 100 Mich. L. Rev. 505, 510 (2001) [hereinafter Stuntz, Pathological Politics]", "article")
check(f["pattern"] == "article" and f["volume"] == "100" and f["first"] == "505" and f["year"] == "2001", "article fields: vol/first/year (%s)" % {k: f[k] for k in ("volume", "first", "year")})
check(f["lastNames"] == ["stuntz"] and f["title"] == "The Pathological Politics of Criminal Law", "signal and [hereinafter] stripped; author/title split (%s / %s)" % (f["lastNames"], f["title"]))
f = zl.parse_cite("see also, e.g., Rachel Elise Barkow, Prisoners of Politics: Breaking the Cycle of Mass Incarceration 5 (2019) (arguing X)", "book")
check(f["pattern"] == "book" and f["lastNames"] == ["barkow"] and f["year"] == "2019" and f["first"] == "5", "book with 'see also, e.g.' and a proposition parenthetical (%s)" % {k: f[k] for k in ("pattern", "lastNames", "year", "first")})
f = zl.parse_cite("Danielle D’Onfro & Daniel Epps, The Fourth Amendment and General Law, 132 Yale L.J. 910, 915 (2023)", "article")
check(f["lastNames"] == ["onfro", "epps"] and f["volume"] == "132", "two authors joined by & (%s)" % f["lastNames"])
f = zl.parse_cite("See Wayne R. LaFave, Substantive Criminal Law, chs. 2 & 3 (3d ed. 2025).", "book")
check(f["year"] == "2025", "edition parenthetical still yields the year")

print("matching")


def best(cite, kind):
    it, sc, _ = zl.match_source(cite, kind, LIB)
    return (it["key"] if it else None), sc


k, sc = best("See Rachel E. Barkow, Administering Crime, 52 UCLA L. Rev. 715, 728 (2005)", "article")
check(k == "A1" and sc["cite"], "volume + first page + author settle an article")
k, sc = best("See generally Rachel Elise Barkow, Justice Abandoned 1 (2025) (“America has less than 5 percent …”)", "book")
check(k == "B1", "short title in the draft matches a record with a long subtitle (reverse %s)" % sc.get("reverse"))
k, sc = best("David A. Sklansky, Traffic Stops, Minority Motorists, and the Future of the Fourth Amendment, 1997 Sup. Ct. Rev. 271, 280 (1997)", "article")
check(k is None, "same author, two shared title words, no year: NOT a match (best %s)" % (sc.get("best") or {}).get("score"))
k, sc = best("George Fisher, Plea Bargaining’s Triumph, 109 Yale L.J. 857, 1066 (2000)", "article")
check(k is None, "an article cite does not take the same-title book from another year")
k, sc = best("or, Why Don’t Legislatures Give a Damn about the Rights of the Accused?, 44 Syracuse L. Rev. 1079, 1089 (1993)", "other")
check(k == "D1", "a cite the ledger split mid-title still matches on volume + first page")
k, sc = best("Marie Gottschalk, Caught: The Prison State and the Lockdown of American Politics 10 (2016)", "book")
check(k == "G1", "edition year differs: still the same book")
k, sc = best("See generally Bruce A. Ackerman, Beyond Carolene Products, 98 Harv. L. Rev. 713, 715 (1985)", "article")
check(k == "K1", "HTML italics in the record title are ignored")
k, sc = best("Daniel Epps, Criminal Procedure in Winter, 51 Loy. L.A. L. Rev. 379 (2018)", "article")
check(k is None, "a two-word treatise title inside a longer article title does not match without its authors")
k, sc = best("See generally Wayne R. LaFave, Jerold H. Israel, Nancy J. King, Orin S. Kerr, Criminal Procedure § 1.5 (4th ed. 2025)", "book")
check(k == "C1", "treatise with four authors matches across editions")

print("metadata confirm notes")
f = zl.parse_cite("Marie Gottschalk, Caught: The Prison State and the Lockdown of American Politics 10 (2016)", "book")
notes = zl.metadata_confirms(f, LIB[5]["data"])
check(len(notes) == 1 and notes[0].startswith("confirm: draft year 2016 vs Zotero record 2014"), "year difference is a confirm note, never a fix (%s)" % notes)
f = zl.parse_cite("See Rachel E. Barkow, Administering Crime, 53 UCLA L. Rev. 715 (2005)", "article")
notes = zl.metadata_confirms(f, LIB[0]["data"])
check(any("volume 53 vs Zotero record 52" in n for n in notes), "volume difference noted (%s)" % notes)

print("credentials")
cfg = {"mcpServers": {"zotero-group": {"env": {"ZOTERO_API_KEY": "k1", "ZOTERO_LIBRARY_ID": "77", "ZOTERO_LIBRARY_TYPE": "group"}}}}
s = zl.resolve_server("zotero-group", config=cfg)
check(s["type"] == "group" and s["id"] == "77" and zl.base_url(s) == "https://api.zotero.org/groups/77", "server entry from ~/.claude.json mcpServers")
try:
    zl.resolve_server("nope", config=cfg)
    check(False, "unknown server raises")
except zl.ConfigError as e:
    check("nope" in str(e), "unknown server raises ConfigError naming it")
import tempfile
with tempfile.TemporaryDirectory() as proj:
    json.dump({"mcpServers": {"zotero-proj": {"env": {"ZOTERO_API_KEY": "k2", "ZOTERO_LIBRARY_ID": "99", "ZOTERO_LIBRARY_TYPE": "group"}}}},
              open(os.path.join(proj, ".mcp.json"), "w"))
    s = zl.resolve_server("zotero-proj", config=cfg, project=proj)
    check(s["id"] == "99" and s["type"] == "group", "a server in the project's .mcp.json resolves (the dialog lists it)")
    local = dict(cfg, projects={os.path.abspath(proj): {"mcpServers": {"zotero-group": {"env": {"ZOTERO_API_KEY": "k3", "ZOTERO_LIBRARY_ID": "55", "ZOTERO_LIBRARY_TYPE": "group"}}}}})
    s = zl.resolve_server("zotero-group", config=local, project=proj)
    check(s["id"] == "55", "local scope wins over user scope on a name clash")
s = zl.resolve_server("env", environ={"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "5"})
check(s["type"] == "user" and zl.base_url(s) == "https://api.zotero.org/users/5", "--server env")

print("end to end with a fake API")
calls = []


class FakeResp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(req, timeout=0):
    url = req.full_url
    calls.append(url)
    if "/items/top" in url:
        start = int(url.split("start=")[1].split("&")[0])
        return FakeResp(json.dumps(LIB if start == 0 else []).encode())
    if "itemType=attachment" in url:
        start = int(url.split("start=")[1].split("&")[0])
        atts = [{"key": "ATT1", "data": {"key": "ATT1", "parentItem": "A1", "contentType": "application/pdf", "linkMode": "imported_file", "filename": "barkow.pdf"}},
                {"key": "ATT2", "data": {"key": "ATT2", "parentItem": "B1", "contentType": "text/html", "linkMode": "imported_url", "filename": "page.html"}}]
        return FakeResp(json.dumps(atts if start == 0 else []).encode())
    if url.endswith("/items/ATT1/file"):
        return FakeResp(b"%PDF-1.4 fake")
    if url.endswith("/items/ATT2/fulltext"):
        return FakeResp(json.dumps({"content": "Justice Abandoned full text from the index", "indexedPages": 3}).encode())
    raise urllib.error.HTTPError(url, 404, "nf", {}, None)


zl.pdftotext_file = lambda pdf, txt: (open(txt, "w").write("page one\fpage two\f"), 2)[1]
sources = [
    {"key": "52 ucla l rev 715", "kind": "article", "cite": "See Rachel E. Barkow, Administering Crime, 52 UCLA L. Rev. 715, 728 (2005)"},
    {"key": "justice abandoned", "kind": "book", "cite": "Rachel Elise Barkow, Justice Abandoned 1 (2025)"},
    {"key": "nowhere", "kind": "article", "cite": "Jane Doe, A Paper Nobody Filed, 1 J. Nothing 1 (1999)"},
    {"key": "42 usc 1983", "kind": "statute", "cite": "42 U.S.C. § 1983"},
]
with tempfile.TemporaryDirectory() as td:
    server = {"name": "zotero", "key": "k", "id": "1", "type": "user"}
    rep = zl.run([s for s in sources if s["kind"] != "statute"], [server], td, opener=fake_opener, log=lambda m: None)
    st = rep["stats"]
    check(st["sources"] == 3 and st["matched"] == 2 and st["unmatched"] == 1, "stats: 2 of 3 matched (%s)" % st)
    a = rep["sources"]["52 ucla l rev 715"]
    check(a["matched"] and a["textSource"] == "pdf" and a["textPages"] == 2 and a["textPath"].endswith("zotero-A1.txt") and a["hasPdf"], "PDF attachment downloaded and extracted (%s)" % {k: a.get(k) for k in ("textSource", "textPages", "hasPdf")})
    check(a["citedFirstPage"] == "715" and a["zoteroUrl"].endswith("/users/1/items/A1"), "cited first page and item URL recorded")
    b = rep["sources"]["justice abandoned"]
    check(b["matched"] and b["textSource"] == "fulltext-index" and open(b["textPath"]).read().startswith("Justice Abandoned"), "no PDF: the full-text index is used")
    n = rep["sources"]["nowhere"]
    check(not n["matched"] and "nowhere" in rep["unmatched"] and isinstance(n.get("candidates"), list), "unmatched source listed with candidates")
    c = zl.compact(rep)
    check(set(c) == {"52 ucla l rev 715", "justice abandoned"} and c["52 ucla l rev 715"]["text"] == a["textPath"] and c["52 ucla l rev 715"]["first"] == "715", "compact map carries only matches, with text path and first page")
    before = len(calls)
    rep2 = zl.run([s for s in sources if s["kind"] != "statute"], [server], td, opener=fake_opener, log=lambda m: None)
    check(len(calls) == before, "second run in the same cache dir makes no network call (library dump and texts cached)")
    check(rep2["sources"]["52 ucla l rev 715"]["textPath"] == a["textPath"], "cached text path reused")
    # load_sources reads the two workflow-arg files and dedupes by key
    la = os.path.join(td, "ledger_args.json")
    sa = os.path.join(td, "support_args.json")
    json.dump({"instances": [], "secondary": sources}, open(la, "w"))
    json.dump({"units": [{"key": "52 ucla l rev 715", "k": "article", "src": "dup"}, {"key": "x", "k": "book", "src": "B, T 3 (2001)"}, {"key": "372 u s 335", "k": "case", "src": "Gideon"}]}, open(sa, "w"))
    ls = zl.load_sources({"secondary": [la], "support": [sa]})
    check([s["key"] for s in ls] == ["52 ucla l rev 715", "justice abandoned", "nowhere", "x"], "load_sources: article/book/other only, deduped across files (%s)" % [s["key"] for s in ls])

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
