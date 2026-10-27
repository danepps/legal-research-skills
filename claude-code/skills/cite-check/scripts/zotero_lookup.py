#!/usr/bin/env python3
"""Deterministic Zotero pre-lookup for the cite-check skill — run BEFORE the workflow launches.

Why this exists (2026-10-27): the agent transcripts of the first live support-pass run showed
where its cost went. Not output tokens (278k for 34 agents, in line with the budget gates) but
486 agent turns, each re-reading 50-60k of context: 22.4M cache-read tokens. The turn-heavy
agents were the ones doing Zotero work by hand — a secondary-existence batch made 12 Zotero
searches plus metadata calls (30+ turns), and every verify agent searched three libraries
before it fetched anything. All of that is deterministic. This script does it once, with no
model tokens: it dumps each configured library, matches every secondary source the draft cites
to a Zotero item, compares the bibliographic metadata, downloads the PDF attachment of every
match and extracts its text to a file the agents run `verify_quotes.py` against directly.
Agents are then told, per source, "in Zotero: text at <path>" or "not in Zotero: do not search
it", and never call a Zotero tool.

Usage:
    python3 zotero_lookup.py OUT.json --server zotero [--server zotero-group ...]
        [--secondary ledger_args.json] [--support support_args.json] [--cites list.json]
        [--cache-dir DIR] [--no-download] [--max-downloads N] [--timeout S]
    python3 zotero_lookup.py OUT.json --compact          # print the compact map for workflow args
    python3 zotero_lookup.py OUT.json --get KEY          # one source's full record (for agents)

Inputs: the `secondary` array of `citation_ledger.py --compact` ({key, kind, cite}), the `units`
array of `prepare_support_units.py --compact` ({key, k, src}), or a plain list of
{key, kind, cite}. Only article/book/other kinds are looked up (statutes and URLs have no Zotero
record worth matching). Keys are the ledger's source keys, so the workflow joins on them.

Per source the report gives:
    matched        true when one library item matched with enough confidence
    library        the MCP server name whose library held it; itemKey its Zotero key
    title, creators, publication, volume, pages, year, doi, url    the Zotero record
    score          the match score and the parts that carried it (title / author / year / cite)
    confirm        bibliographic differences between the draft's cite and the record, as
                   "confirm: ..." notes (never a fix — a Zotero record can be wrong too)
    hasPdf         a PDF attachment exists on the item
    textPath       extracted text of that attachment (pdftotext, form feeds between pages), or
                   of the Zotero full-text index when no PDF could be downloaded
    textPages      pages in the text file; textSource pdf | fulltext-index | none
    citedFirstPage the first page from the draft's cite (pass as --first-page when the PDF's
                   page 1 is the article's first page — the agent confirms)
    candidates     the next-best items when nothing matched well enough (for the agent's note)

Credentials: `--server NAME` reads the MCP server entry of that name in ~/.claude.json
(`mcpServers.NAME.env`: ZOTERO_API_KEY, ZOTERO_LIBRARY_ID, ZOTERO_LIBRARY_TYPE — the same entry
the Zotero MCP tools use, so nothing new to configure). `--server env` uses the environment.
Library dumps are cached in the cache dir for the run; a text file already present is reused,
so a re-run downloads nothing.

Stdlib only (pdftotext optional; without it the Zotero full-text index is used). Exit codes:
0 = ran; 2 = usage / credential error.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.zotero.org"
TIMEOUT = 60
MAX_DOWNLOADS = 200
MAX_PDF_BYTES = 60 * 1024 * 1024
PDF_MAX_PAGES = 400

STOP = set("""a an the of and or in on at to for by with from as is are was were be been this that
these those its it their his her into over under about between among toward against after before
during without within upon vs v et al law review rev journal j""".split())

SIGNAL_RE = re.compile(
    r"^(?:(?:see|cf\.|but|compare|with|accord|contra|also|generally|e\.g\.|sources cited in|citing)[,.;\s]+)+",
    re.I)
TAG_RE = re.compile(r"<[^>]+>")
HEREINAFTER_RE = re.compile(r"\s*\[hereinafter[^\]]*\]", re.I)
PAREN_RE = re.compile(r"\s*\((?![^)]*\b(?:1[6-9]|20)\d{2}\))[^()]*\)")  # parentheticals without a year
YEAR_RE = re.compile(r"\b((?:1[6-9]|20)\d{2})\b")
ARTICLE_RE = re.compile(
    r"^(?P<authors>.+?),\s+(?P<title>.+?),\s+(?P<vol>\d+)\s+(?P<journal>[A-Z][A-Za-z.&'’\-\s]+?)\s+"
    r"(?P<first>\d+)(?:,\s*(?P<pin>[\d,\s–\-]+?))?\s*\((?P<year>(?:1[6-9]|20)\d{2})\)")
BOOK_RE = re.compile(
    r"^(?P<authors>.+?),\s+(?P<title>.+?)(?:\s+(?P<page>\d+(?:[–\-]\d+)?))?\s*\((?P<edparen>[^)]*?)\b(?P<year>(?:1[6-9]|20)\d{2})\)")


# ---- cite parsing -----------------------------------------------------------------------
def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", fold(s)) if t]


def content_words(s: str) -> set[str]:
    return {t for t in tokens(s) if len(t) >= 3 and t not in STOP and not t.isdigit()}


def clean_cite(cite: str) -> str:
    s = (cite or "").strip()
    s = HEREINAFTER_RE.sub("", s)
    s = SIGNAL_RE.sub("", s).strip()
    # drop proposition parentheticals (keep the year parenthetical)
    prev = None
    while prev != s:
        prev = s
        s = PAREN_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".;,")
    return s


def last_names(authors: str) -> list[str]:
    out = []
    for a in re.split(r"\s*(?:&|\band\b|,)\s*", authors or ""):
        a = re.sub(r"\b(?:jr|sr|ii|iii|iv|ed|eds|trans)\.?$", "", a.strip(), flags=re.I).strip()
        if not a:
            continue
        parts = tokens(a)
        if parts:
            out.append(parts[-1])
    return out


def parse_cite(cite: str, kind: str = "") -> dict:
    """Best-effort fields from a footnote cite. Never raises; missing fields are ''."""
    s = clean_cite(cite)
    years = YEAR_RE.findall(s)
    f = {"text": s, "authors": "", "title": "", "volume": "", "first": "", "journal": "",
         "year": years[-1] if years else "", "lastNames": [], "pattern": ""}
    m = ARTICLE_RE.match(s)
    if m and kind in ("article", "other", ""):
        f.update(authors=m.group("authors"), title=m.group("title"), volume=m.group("vol"),
                 journal=m.group("journal").strip(), first=m.group("first"), year=m.group("year"),
                 pattern="article")
    else:
        m = BOOK_RE.match(s)
        if m:
            f.update(authors=m.group("authors"), title=m.group("title"), year=m.group("year"),
                     first=m.group("page") or "", pattern="book")
    if f["authors"] and len(tokens(f["authors"])) > 12:
        # the first comma was inside the title; treat everything as title text
        f["title"] = f["authors"] + ", " + f["title"]
        f["authors"] = ""
    f["lastNames"] = last_names(f["authors"])
    return f


# ---- matching ---------------------------------------------------------------------------
def item_year(d: dict) -> str:
    m = YEAR_RE.search(d.get("date") or "")
    return m.group(1) if m else ""


def item_creators(d: dict) -> list[str]:
    names = []
    for c in d.get("creators") or []:
        if c.get("lastName"):
            names.append(c["lastName"])
        elif c.get("name"):
            names.append(c["name"].split()[-1] if c["name"].split() else c["name"])
    return names


def first_page(pages: str) -> str:
    m = re.match(r"\s*([A-Za-z]?\d+)", pages or "")
    return m.group(1) if m else ""


def score_item(fields: dict, cite_words: set[str], cite_tokens: set[str], d: dict) -> dict:
    """Score one library item against a parsed cite.

    title    share of the ITEM title's content words present anywhere in the cite
    reverse  share of the cite's PARSED title words present in the item title (0 when no
             title was parsed) — catches a record whose subtitle the draft omits
    author   share of the item's creators whose last name appears in the cite
    year     the cite's year equals the record's; cite  volume + first page both equal
    typeOk   false when an article cite meets a book record
    """
    item_title = TAG_RE.sub("", d.get("title") or "")
    title_words = content_words(item_title)
    title = (sum(1 for w in title_words if w in cite_words) / len(title_words)) if title_words else 0.0
    cite_title_words = content_words(fields.get("title") or "")
    reverse = (sum(1 for w in cite_title_words if w in title_words) / len(cite_title_words)) if cite_title_words else 0.0
    creators = [fold(n) for n in item_creators(d)]
    creator_tokens = {tokens(n)[-1] for n in creators if tokens(n)}
    author = (sum(1 for n in creator_tokens if n in cite_tokens) / len(creator_tokens)) if creator_tokens else 0.0
    year = bool(fields["year"]) and item_year(d) == fields["year"]
    cite_match = bool(fields["volume"]) and (d.get("volume") or "").strip() == fields["volume"] \
        and bool(fields["first"]) and first_page(d.get("pages") or "") == fields["first"]
    type_ok = not (fields["pattern"] == "article" and (d.get("itemType") or "") == "book")
    score = 0.45 * title + 0.15 * reverse + 0.25 * author + (0.1 if year else 0.0) + (0.25 if cite_match else 0.0)
    return {"score": round(score, 3), "title": round(title, 2), "reverse": round(reverse, 2), "author": round(author, 2),
            "year": year, "cite": cite_match, "typeOk": type_ok, "titleWords": len(title_words)}


def accept(sc: dict) -> bool:
    """Match rules, each learned from a real cite (test_zotero_lookup.py keeps the cases):
    volume + first page settle an article; the whole item title in the cite plus the author
    settles a book or article (edition years differ); the whole cited title in a longer record
    title plus the author plus the year catches an omitted subtitle; a title match alone needs the
    year. A partial title overlap with the right author is NOT enough (a same-author article with
    two shared title words matched a different one), and an article cite never takes a book record
    without the year."""
    if sc["cite"] and (sc["author"] >= 0.5 or sc["title"] >= 0.5 or sc["reverse"] >= 0.5):
        return True
    if not sc["typeOk"] and not sc["year"]:
        return False
    if sc["titleWords"] >= 2 and sc["title"] >= 0.85 and sc["author"] >= 0.5:
        return True
    if sc["reverse"] >= 0.9 and sc["author"] >= 0.5 and (sc["year"] or sc["title"] >= 0.5):
        return True
    if sc["titleWords"] >= 3 and sc["title"] >= 0.85 and sc["year"]:
        return True
    if sc["titleWords"] >= 2 and sc["title"] >= 0.6 and sc["author"] >= 0.5 and sc["year"] and sc["reverse"] >= 0.6:
        return True
    return False


def match_source(cite: str, kind: str, items: list[dict]) -> tuple[dict | None, dict | None, list]:
    """Best item for a cite: (item, score, runners-up). `items` are Zotero item dicts (with data)."""
    fields = parse_cite(cite, kind)
    cite_words = content_words(fields["text"])
    cite_tokens = set(tokens(fields["text"]))
    scored = []
    for it in items:
        d = it.get("data") or {}
        if d.get("itemType") in ("attachment", "note", "annotation"):
            continue
        sc = score_item(fields, cite_words, cite_tokens, d)
        if sc["score"] > 0.2:
            scored.append((sc, it))
    scored.sort(key=lambda x: -x[0]["score"])
    if scored and accept(scored[0][0]):
        best_sc, best = scored[0]
        return best, dict(best_sc, fields=fields), [i for _, i in scored[1:3]]
    return None, {"fields": fields, "best": scored[0][0] if scored else None}, [i for _, i in scored[:3]]


def metadata_confirms(fields: dict, d: dict) -> list[str]:
    """Differences between the draft's cite and the Zotero record, as confirm notes."""
    out = []
    y = item_year(d)
    if fields["year"] and y and y != fields["year"]:
        out.append(f"confirm: draft year {fields['year']} vs Zotero record {y}")
    if fields["pattern"] == "article":
        v = (d.get("volume") or "").strip()
        if fields["volume"] and v and v != fields["volume"]:
            out.append(f"confirm: draft volume {fields['volume']} vs Zotero record {v}")
        p = first_page(d.get("pages") or "")
        if fields["first"] and p and p != fields["first"]:
            out.append(f"confirm: draft first page {fields['first']} vs Zotero record {d.get('pages')}")
    names = [fold(n) for n in item_creators(d)]
    cite_last = [fold(n) for n in fields["lastNames"]]
    if cite_last and names:
        missing = [n for n in cite_last if not any(n == tokens(m)[-1] for m in names if tokens(m))]
        if missing and len(missing) == len(cite_last):
            out.append(f"confirm: draft author(s) {', '.join(fields['lastNames'])} vs Zotero record {', '.join(item_creators(d))}")
        elif len(names) != len(cite_last) and fields["pattern"] == "article":
            out.append(f"confirm: draft lists {len(cite_last)} author(s), Zotero record {len(names)} ({', '.join(item_creators(d))})")
    return out


# ---- Zotero API -------------------------------------------------------------------------
class ConfigError(Exception):
    pass


def resolve_server(name: str, config: dict | None = None, environ: dict | None = None) -> dict:
    environ = os.environ if environ is None else environ
    if name == "env":
        key, lib = environ.get("ZOTERO_API_KEY"), environ.get("ZOTERO_LIBRARY_ID") or environ.get("ZOTERO_USER_ID")
        typ = environ.get("ZOTERO_LIBRARY_TYPE", "user")
        if not key or not lib:
            raise ConfigError("--server env needs ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in the environment")
        return {"name": "env", "key": key, "id": str(lib), "type": typ}
    if config is None:
        try:
            config = json.load(open(os.path.expanduser("~/.claude.json")))
        except (OSError, ValueError) as e:
            raise ConfigError(f"cannot read ~/.claude.json: {e}")
    entry = ((config.get("mcpServers") or {}).get(name)) or {}
    env = entry.get("env") or {}
    key, lib = env.get("ZOTERO_API_KEY"), env.get("ZOTERO_LIBRARY_ID") or env.get("ZOTERO_USER_ID")
    if not key or not lib:
        raise ConfigError(f'no Zotero MCP server "{name}" with ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in ~/.claude.json '
                          "(register it with /legal-research:setup, or pass --server env)")
    return {"name": name, "key": key, "id": str(lib), "type": env.get("ZOTERO_LIBRARY_TYPE", "user")}


def base_url(server: dict) -> str:
    return f"{API}/{'groups' if server['type'] == 'group' else 'users'}/{server['id']}"


def api_get(url: str, key: str, timeout: int = TIMEOUT, raw: bool = False, opener=None):
    """GET with the API key; honours Backoff / Retry-After once. Returns parsed JSON or bytes."""
    opener = opener or urllib.request.urlopen
    for attempt in (1, 2):
        req = urllib.request.Request(url, headers={"Zotero-API-Key": key, "Zotero-API-Version": "3",
                                                   "User-Agent": "legal-research-skill/1.0"})
        try:
            with opener(req, timeout=timeout) as resp:
                body = resp.read()
                backoff = resp.headers.get("Backoff")
                if backoff and backoff.isdigit():
                    time.sleep(min(int(backoff), 30))
                return body if raw else json.loads(body or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                wait = e.headers.get("Retry-After", "5")
                time.sleep(min(int(wait) if wait.isdigit() else 5, 60))
                continue
            raise


def fetch_all(base: str, key: str, path: str, query: str = "", opener=None) -> list[dict]:
    items, start = [], 0
    while True:
        url = f"{base}/{path}?limit=100&start={start}&format=json{query}"
        batch = api_get(url, key, opener=opener)
        if not batch:
            break
        items += batch
        start += 100
        if len(batch) < 100:
            break
    return items


def dump_library(server: dict, cache_dir: str, opener=None, log=print) -> dict:
    """Top-level items and attachments of one library, cached as JSON in cache_dir."""
    path = os.path.join(cache_dir, f"zotero-library-{server['name']}.json")
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except ValueError:
            pass
    base = base_url(server)
    log(f"zotero_lookup: dumping library {server['name']} ({server['type']} {server['id']}) …")
    items = fetch_all(base, server["key"], "items/top", opener=opener)
    atts = fetch_all(base, server["key"], "items", "&itemType=attachment", opener=opener)
    by_parent: dict[str, list] = {}
    for a in atts:
        d = a.get("data") or {}
        if d.get("parentItem"):
            by_parent.setdefault(d["parentItem"], []).append(
                {"key": d.get("key"), "contentType": d.get("contentType") or "", "linkMode": d.get("linkMode") or "",
                 "filename": d.get("filename") or "", "title": d.get("title") or ""})
    out = {"server": server["name"], "type": server["type"], "id": server["id"], "items": items, "attachments": by_parent}
    with open(path, "w") as f:
        json.dump(out, f)
    log(f"zotero_lookup: {server['name']}: {len(items)} items, {len(atts)} attachments")
    return out


def pdf_attachment(lib: dict, item_key: str) -> dict | None:
    for a in lib["attachments"].get(item_key, []):
        if a["contentType"].lower() == "application/pdf" and a["linkMode"] in ("imported_file", "imported_url", ""):
            return a
    return None


def any_attachment(lib: dict, item_key: str) -> dict | None:
    atts = lib["attachments"].get(item_key, [])
    return atts[0] if atts else None


def pdftotext_file(pdf_path: str, txt_path: str) -> int:
    """Extract text with pdftotext (form feeds between pages). Returns pages extracted, 0 on failure."""
    if not shutil.which("pdftotext"):
        return 0
    try:
        proc = subprocess.run(["pdftotext", "-l", str(PDF_MAX_PAGES), pdf_path, txt_path],
                              capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if proc.returncode != 0 or not os.path.exists(txt_path):
        return 0
    text = open(txt_path, encoding="utf-8", errors="replace").read()
    text = text.rstrip("\f\n\r\t ")
    return text.count("\f") + 1 if text.strip() else 0


def get_text(server: dict, lib: dict, item_key: str, cache_dir: str, allow_download: bool, opener=None, log=print) -> dict:
    """Text for one matched item: cached file, else PDF download + pdftotext, else full-text index."""
    txt = os.path.join(cache_dir, f"{server['name']}-{item_key}.txt")
    meta = os.path.join(cache_dir, f"{server['name']}-{item_key}.meta.json")
    if os.path.exists(txt) and os.path.exists(meta):
        try:
            m = json.load(open(meta))
            m["textPath"] = txt
            return m
        except ValueError:
            pass
    res = {"textPath": "", "textPages": 0, "textSource": "none", "hasPdf": False, "attachmentKey": ""}
    pdf = pdf_attachment(lib, item_key)
    res["hasPdf"] = bool(pdf)
    base = base_url(server)
    if pdf and allow_download:
        res["attachmentKey"] = pdf["key"]
        pdf_path = os.path.join(cache_dir, f"{server['name']}-{item_key}.pdf")
        try:
            if not os.path.exists(pdf_path):
                body = api_get(f"{base}/items/{pdf['key']}/file", server["key"], raw=True, opener=opener)
                if body and body[:5] == b"%PDF-" and len(body) <= MAX_PDF_BYTES:
                    with open(pdf_path, "wb") as f:
                        f.write(body)
                else:
                    log(f"zotero_lookup: {item_key}: attachment {pdf['key']} is not a PDF or too large; skipped")
            if os.path.exists(pdf_path):
                pages = pdftotext_file(pdf_path, txt)
                if pages:
                    res.update(textPath=txt, textPages=pages, textSource="pdf")
        except (urllib.error.URLError, OSError) as e:
            log(f"zotero_lookup: {item_key}: PDF download failed ({e}); trying the full-text index")
    if not res["textPath"]:
        att = pdf or any_attachment(lib, item_key)
        if att:
            try:
                ft = api_get(f"{base}/items/{att['key']}/fulltext", server["key"], opener=opener)
            except urllib.error.HTTPError:
                ft = None
            except urllib.error.URLError:
                ft = None
            content = (ft or {}).get("content") if isinstance(ft, dict) else None
            if content and content.strip():
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(content)
                res.update(textPath=txt, textPages=int((ft or {}).get("indexedPages") or 0), textSource="fulltext-index",
                           attachmentKey=att["key"])
    with open(meta, "w") as f:
        json.dump({k: v for k, v in res.items() if k != "textPath"}, f)
    return res


# ---- driver -----------------------------------------------------------------------------
def load_sources(args: dict) -> list[dict]:
    seen, out = set(), []

    def add(key, kind, cite):
        if not key or key in seen or kind not in ("article", "book", "other"):
            return
        seen.add(key)
        out.append({"key": key, "kind": kind, "cite": cite})

    for p in args.get("secondary") or []:
        data = json.load(open(p))
        for s in data.get("secondary", data) if isinstance(data, dict) else data:
            add(s.get("key"), s.get("kind"), s.get("cite"))
    for p in args.get("support") or []:
        data = json.load(open(p))
        for u in data.get("units", data) if isinstance(data, dict) else data:
            add(u.get("key"), u.get("k") or u.get("kind"), u.get("src") or u.get("source"))
    for p in args.get("cites") or []:
        for s in json.load(open(p)):
            add(s.get("key"), s.get("kind"), s.get("cite"))
    return out


def record_for(it: dict, lib: dict, server: dict) -> dict:
    d = it.get("data") or {}
    return {"library": server["name"], "itemKey": d.get("key") or it.get("key"), "itemType": d.get("itemType"),
            "title": TAG_RE.sub("", d.get("title") or ""), "creators": item_creators(d), "publication": d.get("publicationTitle") or d.get("publisher") or "",
            "volume": d.get("volume") or "", "pages": d.get("pages") or "", "year": item_year(d),
            "doi": d.get("DOI") or "", "url": d.get("url") or "",
            "zoteroUrl": f"https://www.zotero.org/{'groups' if server['type'] == 'group' else 'users'}/{server['id']}/items/{d.get('key')}"}


def run(sources: list[dict], servers: list[dict], cache_dir: str, allow_download: bool = True,
        max_downloads: int = MAX_DOWNLOADS, opener=None, log=print) -> dict:
    os.makedirs(cache_dir, exist_ok=True)
    libs = [(s, dump_library(s, cache_dir, opener=opener, log=log)) for s in servers]
    report = {"libraries": [{"server": s["name"], "items": len(l["items"])} for s, l in libs], "sources": {}, "unmatched": []}
    downloads = 0
    for src in sources:
        best = None
        best_unmatched = None
        for s, l in libs:
            it, sc, runners = match_source(src["cite"], src["kind"], l["items"])
            if it:
                best = (s, l, it, sc)
                break
            if best_unmatched is None and runners:
                best_unmatched = (sc, runners, s, l)
        entry = {"key": src["key"], "kind": src["kind"], "cite": src["cite"], "matched": False}
        if best:
            s, l, it, sc = best
            entry.update(matched=True, score={k: v for k, v in sc.items() if k != "fields"}, **record_for(it, l, s))
            entry["confirm"] = metadata_confirms(sc["fields"], it.get("data") or {})
            entry["citedFirstPage"] = sc["fields"]["first"] if sc["fields"]["pattern"] == "article" else ""
            can = allow_download and downloads < max_downloads
            text = get_text(s, l, entry["itemKey"], cache_dir, can, opener=opener, log=log)
            if text.get("textSource") == "pdf" and can:
                downloads += 1
            entry.update(text)
        else:
            entry["candidates"] = []
            if best_unmatched:
                sc, runners, s, l = best_unmatched
                for r in runners:
                    rec = record_for(r, l, s)
                    entry["candidates"].append({"library": rec["library"], "itemKey": rec["itemKey"], "title": rec["title"][:120], "year": rec["year"]})
            report["unmatched"].append(src["key"])
        report["sources"][src["key"]] = entry
    m = sum(1 for e in report["sources"].values() if e["matched"])
    t = sum(1 for e in report["sources"].values() if e.get("textPath"))
    report["stats"] = {"sources": len(sources), "matched": m, "withText": t, "unmatched": len(sources) - m, "downloads": downloads}
    return report


def compact(report: dict) -> dict:
    """The map the workflow takes as `zoteroHits`: only matched sources, short fields."""
    out = {}
    for k, e in report["sources"].items():
        if not e.get("matched"):
            continue
        out[k] = {"lib": e["library"], "item": e["itemKey"], "title": e["title"][:100], "au": e["creators"][:4],
                  "year": e["year"], "vol": e["volume"], "pp": e["pages"], "text": e.get("textPath") or "",
                  "pages": e.get("textPages") or 0, "src": e.get("textSource") or "none",
                  "first": e.get("citedFirstPage") or "", "confirm": e.get("confirm") or []}
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    out_path = argv[1]
    rest = argv[2:]
    if rest[:1] == ["--compact"]:
        print(json.dumps(compact(json.load(open(out_path))), ensure_ascii=False))
        return 0
    if rest[:1] == ["--get"]:
        rep = json.load(open(out_path))
        e = rep["sources"].get(rest[1]) if len(rest) > 1 else None
        print(json.dumps(e or {"error": "no such key", "key": rest[1:2]}, ensure_ascii=False, indent=1))
        return 0
    args: dict = {"server": [], "secondary": [], "support": [], "cites": []}
    global TIMEOUT
    cache_dir, allow_download, max_downloads, timeout = "", True, MAX_DOWNLOADS, TIMEOUT
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--server", "--secondary", "--support", "--cites") and i + 1 < len(rest):
            args[a[2:]].append(rest[i + 1]); i += 2
        elif a == "--cache-dir" and i + 1 < len(rest):
            cache_dir = rest[i + 1]; i += 2
        elif a == "--no-download":
            allow_download = False; i += 1
        elif a == "--max-downloads" and i + 1 < len(rest):
            max_downloads = int(rest[i + 1]); i += 2
        elif a == "--timeout" and i + 1 < len(rest):
            timeout = int(rest[i + 1]); i += 2
        else:
            print(f"unknown argument {a}", file=sys.stderr)
            return 2
    TIMEOUT = timeout
    if not args["server"]:
        print("usage: at least one --server NAME (a Zotero MCP server in ~/.claude.json, or 'env')", file=sys.stderr)
        return 2
    try:
        servers = [resolve_server(n) for n in args["server"]]
    except ConfigError as e:
        print(f"zotero_lookup: {e}", file=sys.stderr)
        return 2
    sources = load_sources(args)
    cache_dir = cache_dir or os.path.join(os.path.dirname(os.path.abspath(out_path)) or ".", "zotero-cache")
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    report = run(sources, servers, cache_dir, allow_download, max_downloads, log=log)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report["stats"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
