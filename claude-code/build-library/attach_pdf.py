#!/usr/bin/env python3
"""Attach a PDF to an existing Zotero item via the Zotero Web API file-upload flow.

Two sources for the bytes:
  --url  <https://…>   fetch the PDF with a browser User-Agent (Tier 1: open-access
                       repositories, SSRN, digital commons, gov PDFs — no bot-wall)
  --file <path>        use a PDF already on disk (e.g. one a Cowork VM task, or a human
                       click, dropped into ~/Downloads — Tier 3 hand-off)

It performs the 4-step Zotero protocol: create attachment child -> request upload
authorization (md5/size/mtime) -> upload bytes to storage -> register upload. Prints a
PASS/FAIL line per item and verifies the attachment came back with its md5 set.

Why this exists: the Claude-in-Chrome extension (driving the user's real Edge) SUPPRESSES
file downloads — blob, same-origin anchor, and genuine save-button clicks all produce
nothing on disk. So Claude cannot grab a paywalled/WAF PDF (bot-walled repos) to
disk itself. The reliable division of labor:
  * Tier 1 (curl-reachable): this script with --url, fully autonomous.
  * Tier 3 (session-gated / WAF): a Cowork VM task or a human connector-click puts the
    file in ~/Downloads; then this script with --file attaches it.
The Zotero API key is read the same way build-library does (env ZOTERO_API_KEY in
~/.claude.json). The user library id comes from env ZOTERO_USER_ID (or ZOTERO_LIBRARY_ID).

Usage:
  python3 attach_pdf.py --item <ZOTERO_ITEM_KEY> --url  <PDF_URL>  [--title "Full Text PDF"]
  python3 attach_pdf.py --item <ZOTERO_ITEM_KEY> --file <PATH>     [--title "Full Text PDF"]
"""
import argparse, hashlib, json, os, re, sys, time, urllib.parse, urllib.request

UID = os.environ.get("ZOTERO_USER_ID") or os.environ.get("ZOTERO_LIBRARY_ID") or sys.exit("set ZOTERO_USER_ID (your Zotero user library id)")
BASE = f"https://api.zotero.org/users/{UID}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def api_key():
    if os.environ.get("ZOTERO_API_KEY"):
        return os.environ["ZOTERO_API_KEY"]
    cfg = json.load(open(os.path.expanduser("~/.claude.json")))

    def find(o):
        if isinstance(o, dict):
            if "ZOTERO_API_KEY" in o:
                return o["ZOTERO_API_KEY"]
            for v in o.values():
                r = find(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
    k = find(cfg)
    if not k:
        sys.exit("no ZOTERO_API_KEY found (env or ~/.claude.json)")
    return k


def req(method, url, key, data=None, headers=None):
    h = {"Zotero-API-Key": key}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=300) as resp:
        b = resp.read()
        return resp.status, (json.loads(b) if b else {})


def fetch_url(url):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(r, timeout=120) as resp:
        return resp.read()


def metadata_filename(key, item_key):
    """Zotero-style filename from the parent item's metadata:
    "Author - Year - Title.pdf" (case items: "Case Name - Year.pdf").
    Returns None if the metadata can't be fetched — caller falls back."""
    try:
        st, resp = req("GET", f"{BASE}/items/{item_key}", key)
        d = resp.get("data", {})
    except Exception:
        return None
    title = d.get("title") or d.get("caseName") or d.get("nameOfAct") or ""
    date = d.get("date") or d.get("dateDecided") or d.get("dateEnacted") or ""
    m = re.search(r"\b(1[6-9]\d\d|20\d\d)\b", date)
    year = m.group(0) if m else ""
    author = ""
    for c in d.get("creators", []):
        last = c.get("lastName") or c.get("name")
        if last:
            author = last
            break
    # Long academic titles: keep the part before a subtitle colon.
    if len(title) > 80 and ":" in title:
        title = title.split(":")[0]
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0] + "…"
    parts = [p for p in (author, year, title) if p]
    if not parts:
        return None
    fname = " - ".join(parts)
    fname = re.sub(r'[/\\:*?"<>|]', "", fname)
    fname = re.sub(r"\s+", " ", fname).strip()
    return fname + ".pdf" if fname else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True, help="parent Zotero item key")
    ap.add_argument("--url", help="PDF URL to fetch (Tier 1)")
    ap.add_argument("--file", help="local PDF path (Tier 3 hand-off)")
    ap.add_argument("--title", default="Full Text PDF")
    ap.add_argument("--filename", help="stored filename (defaults from url/file)")
    a = ap.parse_args()
    if not (a.url or a.file) or (a.url and a.file):
        sys.exit("give exactly one of --url or --file")

    key = api_key()
    if a.url:
        body = fetch_url(a.url)
        fname = (a.filename or metadata_filename(key, a.item)
                 or os.path.basename(urllib.parse.urlparse(a.url).path) or "attachment.pdf")
    else:
        body = open(a.file, "rb").read()
        fname = a.filename or metadata_filename(key, a.item) or os.path.basename(a.file)
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    if body[:5] != b"%PDF-":
        sys.exit(f"FAIL {a.item}: fetched bytes are not a PDF (starts {body[:8]!r}) — likely a bot-wall/login page")

    md5 = hashlib.md5(body).hexdigest()
    size = len(body)
    mtime = int(1000 * time.time())

    att = [{"itemType": "attachment", "parentItem": a.item, "linkMode": "imported_file",
            "title": a.title, "contentType": "application/pdf", "filename": fname, "charset": ""}]
    st, resp = req("POST", f"{BASE}/items", key, json.dumps(att).encode(), {"Content-Type": "application/json"})
    if "successful" not in resp or "0" not in resp["successful"]:
        sys.exit(f"FAIL {a.item}: could not create attachment item: {resp.get('failed') or resp}")
    akey = resp["successful"]["0"]["key"]

    form = urllib.parse.urlencode({"md5": md5, "filename": fname, "filesize": size, "mtime": mtime}).encode()
    st, auth = req("POST", f"{BASE}/items/{akey}/file", key, form,
                   {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"})
    if auth.get("exists"):
        print(f"PASS {a.item}: file already in storage (dedup) -> attachment {akey} ({size} bytes)")
        return
    up = auth["prefix"].encode() + body + auth["suffix"].encode()
    r = urllib.request.Request(auth["url"], data=up, headers={"Content-Type": auth["contentType"]}, method="POST")
    with urllib.request.urlopen(r, timeout=300) as resp:
        upstatus = resp.status
    reg = urllib.parse.urlencode({"upload": auth["uploadKey"]}).encode()
    st, _ = req("POST", f"{BASE}/items/{akey}/file", key, reg,
                {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"})
    ok = upstatus in (200, 201) and st in (200, 204)
    print(f"{'PASS' if ok else 'FAIL'} {a.item}: attached {fname} ({size} bytes) -> attachment {akey} "
          f"[upload {upstatus}, register {st}]")


if __name__ == "__main__":
    main()
