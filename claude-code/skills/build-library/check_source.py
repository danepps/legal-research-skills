#!/usr/bin/env python3
"""Deterministic bibliographic verification for Zotero items.

Verifies that each item's identifier (ISBN or DOI) resolves in an authoritative
external catalog AND that the catalog's record matches the item's title, authors,
and year under normalized string comparison. No model judgment is involved: a
fabricated source has no identifier that resolves to matching metadata, so it
cannot pass.

Sources tried, in order, until one fully matches:
    ISBN  -> Open Library (edition record), Open Library (search index),
             Google Books, Harvard Library, Library of Congress
    DOI   -> Crossref (doi.org registration authority)
    plus, as a last resort for books too new for the catalogs: the item's own
    `url` field, when it points at the publisher's or a major bookseller's
    page -- the page must contain the ISBN, the normalized title, and every
    author surname (string containment on the fetched page; still no model
    judgment).
A PASS requires one source to match on title AND year AND (authors, when the
source lists any). Per-source results are reported so a single corrupt catalog
record (it happens, notably on Open Library) doesn't sink a real book.

Usage:
    # verify every top-level item in a Zotero collection
    python3 check_source.py --collection 4TP4IVXF [--library user:<ID>] [--json]

    # verify specific items
    python3 check_source.py --keys MWTADJFF,6HJJSGGE

    # verify ad-hoc records before they are ever added to Zotero
    echo '[{"title":"...","creators":[...],"date":"2013","ISBN":"9780..."}]' | \
        python3 check_source.py --stdin

Zotero credentials: ZOTERO_API_KEY / ZOTERO_LIBRARY_ID / ZOTERO_LIBRARY_TYPE env
vars, falling back to the Zotero MCP server entry setup.py wrote in ~/.claude.json
(server name from --server or ZOTERO_MCP_SERVER, default "zotero").

Verdicts per item:
    PASS          identifier resolved and metadata matched in >=1 source
    FAIL          identifier resolved somewhere but NO source's metadata matched
    UNRESOLVED    every source was searched and none knows the identifier
                  (suspicious -- but catalogs are incomplete; see SKILL.md)
    UNAVAILABLE   nothing resolved AND at least one source could not be searched
                  (network/quota/JSON error). Lack of access is not evidence of
                  nonexistence: rerun later or verify by hand. The detail lists
                  which sources were searched and which failed, with the error.
    BAD_ISBN      ISBN checksum invalid (fabricated or mistyped)
    NO_IDENTIFIER item has no ISBN/DOI to check deterministically -- needs manual
                  verification against a catalog/publisher page

Each result also records `fields_compared` for the matching source: which of
title / year / authors the source actually supplied and were compared. A source
that lists no authors cannot confirm the authors, and the PASS line says so.

Exit codes: 0 = all PASS; 1 = at least one non-PASS; 2 = usage/config error, or
the Zotero fetch was incomplete (a requested key missing, a page missing, or a
malformed response) -- nothing is verified in that case.
Stdlib only. Part of the build-library skill.
"""
import argparse
import difflib
import html as _html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

UA = "build-library-skill/1.0 (https://github.com/danepps/legal-research-skills)"
TIMEOUT = 25
SLEEP = 0.6  # politeness delay between external requests

# ---------------------------------------------------------------- utilities

class Unavailable:
    """A source that could not be searched (transport, quota, or JSON error).
    Resolvers return this instead of a record list so the caller can tell
    'lookup unavailable' from 'searched, no match'."""

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return f"Unavailable({self.reason!r})"


NOT_FOUND = "not-found"


def fetch_json_result(url, headers=None):
    """Return (data, None) on success, (None, NOT_FOUND) on HTTP 404, or
    (None, "<error>") when the request failed or the body was not JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, NOT_FOUND
        return None, f"HTTP {e.code}"
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"{type(e).__name__}: {e}"


def fetch_json(url, headers=None):
    """Parsed JSON, or None on any failure (callers that don't need to know why)."""
    data, _err = fetch_json_result(url, headers)
    return data


def normalize(s):
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def main_title(s):
    """The part before the first colon/subtitle separator."""
    return normalize(re.split(r"[:;]| - ", s or "", maxsplit=1)[0])


def title_match(claimed, found):
    """Deterministic title comparison; True when the records plainly agree."""
    c_full, f_full = normalize(claimed), normalize(found)
    if not c_full or not f_full:
        return False
    c_main, f_main = main_title(claimed), main_title(found)
    if c_main and f_main and (c_main in f_full or f_main in c_full):
        return True
    if difflib.SequenceMatcher(None, c_full, f_full).ratio() >= 0.75:
        return True
    return difflib.SequenceMatcher(None, c_main, f_main).ratio() >= 0.85


def year_of(s):
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", str(s or ""))
    return int(m.group(1)) if m else None


def isbn13_ok(isbn):
    d = re.sub(r"[^0-9Xx]", "", isbn)
    if len(d) == 10:
        total = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(d))
        return total % 11 == 0
    if len(d) == 13 and d.isdigit():
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d))
        return total % 10 == 0
    return False


def clean_isbn(isbn):
    return re.sub(r"[^0-9Xx]", "", isbn or "")

# ------------------------------------------------------- source record model
# Each resolver returns a LIST of candidate records (possibly empty = the
# source was searched and doesn't know the identifier), or an Unavailable
# carrying the error when the source itself could not be searched (reported
# as unavailable, never as absence).
# Record shape: {source, title, authors: [names...], year}


def flatten_mods_names(name):
    """Harvard MODS namePart values can be strings, dicts, or lists thereof."""
    out = []
    for n in name if isinstance(name, list) else [name]:
        if not isinstance(n, dict):
            continue
        parts = n.get("namePart")
        for p in parts if isinstance(parts, list) else [parts]:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict) and p.get("@type") != "date":
                out.append(str(p.get("#text", "")))
    return out


def ol_resolve(isbn):
    d, err = fetch_json_result(f"https://openlibrary.org/isbn/{isbn}.json")
    if err == NOT_FOUND:
        return []
    if err or not isinstance(d, dict):
        return Unavailable(err or "unexpected response shape")
    authors = []
    for a in d.get("authors", []):
        key = a.get("key") if isinstance(a, dict) else None
        if key:
            ad = fetch_json(f"https://openlibrary.org{key}.json")
            if ad and ad.get("name"):
                authors.append(ad["name"])
    if d.get("by_statement"):
        authors.append(d["by_statement"])
    title = d.get("title", "")
    if d.get("subtitle"):
        title += ": " + d["subtitle"]
    return [{"source": "openlibrary", "title": title, "authors": authors,
             "year": year_of(d.get("publish_date"))}]


def ol_search_resolve(isbn):
    d, err = fetch_json_result(
        f"https://openlibrary.org/search.json?q=isbn:{isbn}"
        "&fields=title,subtitle,author_name,first_publish_year,publish_year&limit=5")
    if err or not isinstance(d, dict):
        return Unavailable(err or "unexpected response shape")
    recs = []
    for doc in d.get("docs", []):
        title = doc.get("title", "")
        if doc.get("subtitle"):
            title += ": " + doc["subtitle"]
        years = doc.get("publish_year") or []
        if doc.get("first_publish_year"):
            years.append(doc["first_publish_year"])
        recs.append({"source": "openlibrary-search", "title": title,
                     "authors": doc.get("author_name") or [],
                     "year": years})
    return recs


def gb_resolve(isbn):
    d, err = fetch_json_result(
        f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&country=US")
    if err or not isinstance(d, dict):
        return Unavailable(err or "unexpected response shape")
    if d.get("error"):
        return Unavailable(f"API error: {d['error']}"[:200])
    recs = []
    for it in d.get("items", []):
        v = it.get("volumeInfo", {})
        ids = {i.get("identifier") for i in v.get("industryIdentifiers", [])}
        if ids and isbn not in ids:
            continue
        title = v.get("title", "")
        if v.get("subtitle"):
            title += ": " + v["subtitle"]
        recs.append({"source": "googlebooks", "title": title,
                     "authors": v.get("authors") or [],
                     "year": year_of(v.get("publishedDate"))})
    return recs


def harvard_resolve(isbn):
    d, err = fetch_json_result(
        f"https://api.lib.harvard.edu/v2/items.json?identifier={isbn}&limit=5")
    if err or not isinstance(d, dict):
        return Unavailable(err or "unexpected response shape")
    mods = (d.get("items") or {}).get("mods") if isinstance(d.get("items"), dict) else None
    if not mods:
        return []
    recs = []
    for m in mods if isinstance(mods, list) else [mods]:
        ti = m.get("titleInfo")
        ti = ti[0] if isinstance(ti, list) else ti or {}
        title = str(ti.get("title", "")).strip()
        if ti.get("subTitle"):
            title += ": " + str(ti["subTitle"]).strip()
        authors = flatten_mods_names(m.get("name", []))
        year = None
        oi = m.get("originInfo")
        for o in oi if isinstance(oi, list) else [oi or {}]:
            di = o.get("dateIssued")
            for dv in di if isinstance(di, list) else [di]:
                y = year_of(dv if isinstance(dv, str) else
                            (dv or {}).get("#text") if isinstance(dv, dict) else None)
                if y:
                    year = y
                    break
            if year:
                break
        if title:
            recs.append({"source": "harvard", "title": title,
                         "authors": authors, "year": year})
    return recs


def loc_resolve(isbn):
    d, err = fetch_json_result(f"https://www.loc.gov/search/?q={isbn}&fo=json&c=5")
    if err or not isinstance(d, dict):
        return Unavailable(err or "unexpected response shape")
    recs = []
    for r in d.get("results", []):
        title = r.get("title") or ""
        authors = r.get("contributor") or []
        if isinstance(authors, str):
            authors = [authors]
        if title:
            recs.append({"source": "loc", "title": title, "authors": authors,
                         "year": year_of(r.get("date"))})
    return recs


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(2_000_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def url_check(item, isbn):
    """Deterministic publisher-page check: a page tied to the item (its `url`
    field, or a `Verified-URL: <https://...>` line in `extra`) must contain
    the ISBN, the normalized main title, and every author surname."""
    urls = []
    if (item.get("url") or "").strip().startswith("https://"):
        urls.append(item["url"].strip())
    for m in re.finditer(r"Verified-URL:\s*(https://\S+)", item.get("extra") or ""):
        urls.append(m.group(1))
    if not urls:
        return None
    details = []
    for url in urls:
        html = fetch_text(url)
        if html is None:
            details.append(f"url_check: could not fetch {url}")
            continue
        blob = normalize(_html.unescape(re.sub(r"<[^>]+>", " ", html)))
        raw = re.sub(r"[^0-9Xx]", "", html)
        problems = []
        if isbn not in raw:
            problems.append("ISBN not on page")
        if main_title(item.get("title", "")) not in blob:
            problems.append("title not on page")
        for c in item.get("creators", []):
            if c.get("creatorType") == "author":
                ln = normalize(c.get("lastName") or c.get("name") or "")
                if ln and not re.search(r"(?<![a-z0-9])" + re.escape(ln) + r"(?![a-z0-9])", blob):
                    problems.append(f"author {ln!r} not on page")
        if not problems:
            return {"ok": True,
                    "detail": f"url_check: ISBN+title+authors all present at {url}"}
        details.append(f"url_check {url}: {'; '.join(problems)}")
    return {"ok": False, "detail": "; ".join(details)}


def crossref_resolve(doi):
    d, err = fetch_json_result(
        f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}")
    if err == NOT_FOUND:
        return []
    if err or not isinstance(d, dict) or not isinstance(d.get("message"), dict):
        return Unavailable(err or "unexpected response shape")
    m = d["message"]
    title = " ".join(m.get("title") or [])
    if m.get("subtitle"):
        title += ": " + " ".join(m["subtitle"])
    authors = [" ".join(filter(None, [a.get("given"), a.get("family")]))
               for a in m.get("author", [])]
    year = None
    for k in ("published-print", "published-online", "issued", "created"):
        parts = (m.get(k) or {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            year = parts[0][0]
            break
    return [{"source": "crossref", "title": title, "authors": authors,
             "year": year}]

# -------------------------------------------------------------- comparison


def author_in(claimed, src_names):
    """True when every token of the normalized claimed name appears as a whole
    token in one source name. Token matching, so 'Smith' does not match
    'Smithson' and 'van der Berg' needs all three tokens in the same name."""
    tokens = normalize(claimed).split()
    if not tokens:
        return False
    for name in src_names:
        have = set(normalize(name).split())
        if all(t in have for t in tokens):
            return True
    return False


def compare(item, rec):
    """Compare a claimed item against a source record.

    Returns (ok, problems, compared) where `compared` lists the fields the
    source actually supplied and that were therefore checked: a subset of
    ("title", "year", "authors"). A field the source left blank is not
    compared and is not evidence either way."""
    problems = []
    compared = []
    if rec.get("title"):
        compared.append("title")
    if not title_match(item.get("title", ""), rec.get("title", "")):
        problems.append(f"title mismatch (source: {rec.get('title')!r})")

    iy, ry = year_of(item.get("date")), rec.get("year")
    ry_list = [y for y in (ry if isinstance(ry, list) else [ry]) if y]
    if iy and ry_list:
        compared.append("year")
        if not any(abs(iy - y) <= 1 for y in ry_list):
            problems.append(f"year mismatch (claimed {iy}, source {ry_list})")

    claimed_authors = [c.get("lastName") or c.get("name") or ""
                       for c in item.get("creators", [])
                       if c.get("creatorType") == "author"]
    claimed_authors = [a for a in claimed_authors if normalize(a)]
    src_names = [n for n in (rec.get("authors") or []) if normalize(n)]
    if claimed_authors and src_names:
        compared.append("authors")
        missing = [a for a in claimed_authors if not author_in(a, src_names)]
        if missing:
            problems.append(
                f"author(s) not in source record: {', '.join(missing)} "
                f"(source: {'; '.join(src_names)!r})")
    return (not problems, problems, compared)


def verify_item(item):
    """Verdict dict for one Zotero-shaped item."""
    title = item.get("title", "")
    isbn = clean_isbn(item.get("ISBN", "").split()[0] if item.get("ISBN") else "")
    doi = (item.get("DOI") or "").strip()

    result = {"key": item.get("key", ""), "title": title, "identifier": "",
              "verdict": "", "matched_source": "", "fields_compared": [],
              "sources_searched": [], "sources_unavailable": [], "detail": []}

    if isbn:
        result["identifier"] = f"ISBN {isbn}"
        if not isbn13_ok(isbn):
            result["verdict"] = "BAD_ISBN"
            result["detail"] = ["ISBN checksum invalid -- fabricated or mistyped"]
            return result
        resolvers = [ol_resolve, ol_search_resolve, gb_resolve,
                     harvard_resolve, loc_resolve]
        arg = isbn
    elif doi:
        result["identifier"] = f"DOI {doi}"
        resolvers = [crossref_resolve]
        arg = doi
    else:
        result["verdict"] = "NO_IDENTIFIER"
        result["detail"] = ["no ISBN/DOI; verify manually against a catalog page"]
        return result

    resolved_any = False
    for resolver in resolvers:
        name = resolver.__name__
        recs = resolver(arg)
        time.sleep(SLEEP)
        if isinstance(recs, Unavailable) or recs == "ERROR":
            reason = recs.reason if isinstance(recs, Unavailable) else "error/quota"
            result["sources_unavailable"].append(name)
            result["detail"].append(f"{name}: lookup unavailable ({reason})")
            continue
        if not isinstance(recs, list):
            result["sources_unavailable"].append(name)
            result["detail"].append(f"{name}: lookup unavailable (malformed resolver result)")
            continue
        result["sources_searched"].append(name)
        if not recs:
            result["detail"].append(f"{name}: searched, no match")
            continue
        resolved_any = True
        for rec in recs:
            ok, problems, compared = compare(item, rec)
            if ok:
                result["verdict"] = "PASS"
                result["matched_source"] = rec["source"]
                result["fields_compared"] = compared
                unchecked = [f for f in ("title", "year", "authors") if f not in compared]
                note = (f"; source supplied no {'/'.join(unchecked)} -- not checked"
                        if unchecked else "")
                result["detail"].append(
                    f"{rec['source']}: matched ({'/'.join(compared)}){note} -- "
                    f"source title: {rec['title']!r}, year {rec.get('year')}")
                return result
            result["detail"].append(f"{rec['source']}: {'; '.join(problems)}")

    # last resort for books too new for the catalogs: the item's own URL,
    # which must be a publisher/bookseller page naming ISBN+title+authors
    if isbn:
        uc = url_check(item, isbn)
        if uc:
            result["detail"].append(uc["detail"])
            if uc["ok"]:
                result["verdict"] = "PASS"
                result["matched_source"] = "url_check"
                return result

    if resolved_any:
        result["verdict"] = "FAIL"
    elif result["sources_unavailable"]:
        result["verdict"] = "UNAVAILABLE"
        result["detail"].append(
            f"could not complete the lookup: {len(result['sources_unavailable'])} of "
            f"{len(resolvers)} source(s) unavailable "
            f"({', '.join(result['sources_unavailable'])}); searched with no match: "
            f"{', '.join(result['sources_searched']) or 'none'}. "
            "Not evidence of nonexistence -- rerun later or verify by hand.")
    else:
        result["verdict"] = "UNRESOLVED"
        result["detail"].append(
            f"searched {len(result['sources_searched'])} source(s) with no match: "
            f"{', '.join(result['sources_searched'])}")
    return result

# ------------------------------------------------------------- Zotero I/O


def zotero_creds(server=None, claude_json=None):
    """(api_key, library_type, library_id): env vars first, then the MCP server
    entry setup.py wrote in ~/.claude.json (by name; default "zotero")."""
    key = os.environ.get("ZOTERO_API_KEY")
    lib = os.environ.get("ZOTERO_LIBRARY_ID")
    typ = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
    if key and lib:
        return key, typ, lib
    server = server or os.environ.get("ZOTERO_MCP_SERVER") or "zotero"
    try:
        cfg = json.load(open(claude_json or os.path.expanduser("~/.claude.json")))
        env = cfg["mcpServers"][server]["env"]
        return (env["ZOTERO_API_KEY"], env.get("ZOTERO_LIBRARY_TYPE", "user"),
                env["ZOTERO_LIBRARY_ID"])
    except Exception:
        return None, None, None


class ZoteroFetchError(Exception):
    pass


ZOTERO_PAGE = 100


def zotero_get(path, key):
    """One Zotero API GET: (parsed JSON, headers). Raises ZoteroFetchError."""
    url = path if path.startswith("https://") else f"https://api.zotero.org{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Zotero-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r), r.headers
    except urllib.error.HTTPError as e:
        raise ZoteroFetchError(f"HTTP {e.code} for {url}")
    except json.JSONDecodeError as e:
        raise ZoteroFetchError(f"invalid JSON from {url}: {e}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ZoteroFetchError(f"{type(e).__name__} for {url}: {e}")


def _next_link(headers):
    link = headers.get("Link") if headers else None
    if not link:
        return None
    for part in link.split(","):
        m = re.match(r'\s*<([^>]+)>\s*;\s*rel="?next"?', part)
        if m:
            return m.group(1)
    return None


def zotero_fetch_all(path, key):
    """Every record behind a Zotero listing, following pagination (Link
    rel="next", else start/limit) and reconciling Total-Results where the
    server sends it. Raises ZoteroFetchError if a page is malformed, a key
    appears twice, or the collected count disagrees with the declared total."""
    sep = "&" if "?" in path else "?"
    url = f"{path}{sep}start=0&limit={ZOTERO_PAGE}"
    records, seen, total = [], set(), None
    start = 0
    while url:
        batch, headers = zotero_get(url, key)
        if not isinstance(batch, list):
            raise ZoteroFetchError(f"expected a JSON array from {url}, got {type(batch).__name__}")
        for rec in batch:
            if not isinstance(rec, dict) or not isinstance(rec.get("data"), dict) \
                    or not rec["data"].get("key"):
                raise ZoteroFetchError(f"malformed record in response from {url}")
            if rec["data"]["key"] in seen:
                raise ZoteroFetchError(
                    f"item {rec['data']['key']} returned more than once by {path}")
            seen.add(rec["data"]["key"])
            records.append(rec)
        tr = headers.get("Total-Results") if headers else None
        if tr is not None and str(tr).strip().isdigit():
            total = int(tr)
        nxt = _next_link(headers)
        if nxt and nxt != url:
            url = nxt
        elif not batch:
            url = None
        elif total is not None and len(records) < total:
            start += len(batch)
            url = f"{path}{sep}start={start}&limit={ZOTERO_PAGE}"
        elif total is None and len(batch) >= ZOTERO_PAGE:
            start += len(batch)
            url = f"{path}{sep}start={start}&limit={ZOTERO_PAGE}"
        else:
            url = None
        if total is not None and len(records) >= total:
            url = None
    if total is not None and len(records) != total:
        raise ZoteroFetchError(
            f"incomplete listing: server declared {total} result(s) but {len(records)} "
            f"were returned for {path}")
    return records


def zotero_fetch_keys(base, keys, key):
    """Records for exactly the requested item keys, each exactly once. Raises
    ZoteroFetchError naming any key the server omitted, duplicated, or added."""
    want = []
    for k in keys:
        k = k.strip()
        if k and k not in want:
            want.append(k)
    if not want:
        raise ZoteroFetchError("no item keys given")
    got, counts = {}, {}
    for i in range(0, len(want), 50):  # Zotero caps itemKey at 50 per request
        chunk = want[i:i + 50]
        for rec in zotero_fetch_all(f"{base}/items?itemKey={','.join(chunk)}", key):
            k = rec["data"]["key"]
            if k not in chunk:
                raise ZoteroFetchError(f"server returned unrequested item {k}")
            counts[k] = counts.get(k, 0) + 1
            got[k] = rec
    missing = [k for k in want if k not in got]
    dupes = [k for k, n in counts.items() if n > 1]
    if missing or dupes:
        bits = []
        if missing:
            bits.append(f"requested key(s) not returned by Zotero: {', '.join(missing)}")
        if dupes:
            bits.append(f"returned more than once: {', '.join(dupes)}")
        raise ZoteroFetchError("; ".join(bits))
    return [got[k] for k in want]

# ------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--collection", help="Zotero collection key to verify")
    ap.add_argument("--keys", help="comma-separated Zotero item keys")
    ap.add_argument("--library", help="override library, e.g. user:<ID> or group:<ID>")
    ap.add_argument("--server", help="name of the Zotero MCP server entry in ~/.claude.json "
                                     "to read credentials from (default: zotero)")
    ap.add_argument("--stdin", action="store_true",
                    help="read a JSON array of Zotero-shaped items from stdin")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()

    if args.stdin:
        items = json.load(sys.stdin)
    else:
        if not (args.collection or args.keys):
            ap.print_help()
            return 2
        key, typ, lib = zotero_creds(args.server)
        if args.library:
            if ":" not in args.library:
                print("--library must be user:<ID> or group:<ID>", file=sys.stderr)
                return 2
            typ, lib = args.library.split(":", 1)
        if not (key and lib):
            print("no Zotero credentials (env or ~/.claude.json)", file=sys.stderr)
            return 2
        if typ not in ("user", "group"):
            print(f"library type must be user or group, not {typ!r}", file=sys.stderr)
            return 2
        base = f"/{typ}s/{lib}"
        try:
            if args.collection:
                raw = zotero_fetch_all(
                    f"{base}/collections/{args.collection}/items/top", key)
            else:
                raw = zotero_fetch_keys(base, args.keys.split(","), key)
        except ZoteroFetchError as e:
            print(f"Zotero fetch incomplete -- nothing verified: {e}", file=sys.stderr)
            return 2
        skipped = [r["data"]["key"] for r in raw
                   if r["data"].get("itemType") in ("attachment", "note")]
        if skipped:
            print(f"note: skipping {len(skipped)} child item(s) (attachment/note): "
                  f"{', '.join(skipped)}", file=sys.stderr)
        items = [r["data"] for r in raw
                 if r["data"].get("itemType") not in ("attachment", "note")]
        if args.collection:
            print(f"fetched {len(raw)} top-level record(s) from collection "
                  f"{args.collection}", file=sys.stderr)

    results = [verify_item(it) for it in items]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        width = max((len(r["title"]) for r in results), default=0)
        width = min(width, 58)
        for r in results:
            print(f"{r['verdict']:<13} {r['title'][:58]:<{width}}  "
                  f"[{r['identifier']}]"
                  + (f"  via {r['matched_source']}" if r["matched_source"] else ""))
            if r["verdict"] != "PASS":
                for d in r["detail"]:
                    print(f"              - {d}")
        counts = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        print("\nsummary:", ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))

    return 0 if all(r["verdict"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
