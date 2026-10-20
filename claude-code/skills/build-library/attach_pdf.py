#!/usr/bin/env python3
"""Attach a PDF to an existing Zotero item via the Zotero Web API file-upload flow.

Two sources for the bytes:
  --url  <https://…>   fetch the PDF with a browser User-Agent (Tier 1: open-access
                       repositories, SSRN, digital commons, gov PDFs — no bot-wall)
  --file <path>        use a PDF already on disk (e.g. one a Cowork VM task, or a human
                       click, dropped into ~/Downloads — Tier 3 hand-off)

It performs the 4-step Zotero protocol: create attachment child -> request upload
authorization (md5/size/mtime) -> upload bytes to storage -> register upload. Then it
reads the attachment back from the API and checks that it landed in the intended
library (user vs group, id), under the intended parent item, as application/pdf with
the uploaded md5 -- and prints PASS only when all of that holds (exit 1 otherwise).

Why this exists: the Claude-in-Chrome extension (driving the user's real Edge) SUPPRESSES
file downloads — blob, same-origin anchor, and genuine save-button clicks all produce
nothing on disk. So Claude cannot grab a paywalled/WAF PDF (bot-walled repos) to
disk itself. The reliable division of labor:
  * Tier 1 (curl-reachable): this script with --url, fully autonomous.
  * Tier 3 (session-gated / WAF): a Cowork VM task or a human connector-click puts the
    file in ~/Downloads; then this script with --file attaches it.

Library and credentials are resolved together, only when the command runs (so --help
never needs them), in this order:
  1. --library user:<ID> | group:<ID> on the command line (key still from 2/3);
  2. environment: ZOTERO_API_KEY, ZOTERO_LIBRARY_ID (or ZOTERO_USER_ID),
     ZOTERO_LIBRARY_TYPE (user|group; default user);
  3. the Zotero MCP server entry setup.py wrote in ~/.claude.json: mcpServers.<name>.env
     with ZOTERO_API_KEY / ZOTERO_LIBRARY_ID / ZOTERO_LIBRARY_TYPE. <name> comes from
     --server or ZOTERO_MCP_SERVER, default "zotero"; if that name is absent and exactly
     one server entry carries Zotero credentials, that one is used.
Group libraries post to https://api.zotero.org/groups/<ID>, user libraries to /users/<ID>.

Usage:
  python3 attach_pdf.py --item <ZOTERO_ITEM_KEY> --url  <PDF_URL>  [--title "Full Text PDF"]
  python3 attach_pdf.py --item <ZOTERO_ITEM_KEY> --file <PATH>     [--title "Full Text PDF"]
      [--library group:<ID>] [--server <mcp-server-name>]
"""
import argparse, hashlib, json, os, re, sys, time, urllib.parse, urllib.request

API = "https://api.zotero.org"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
DEFAULT_SERVER = "zotero"


class ConfigError(Exception):
    pass


def _zotero_servers(cfg):
    """{name: env} for every mcpServers entry carrying Zotero credentials."""
    out = {}
    for name, s in ((cfg or {}).get("mcpServers") or {}).items():
        if isinstance(s, dict) and isinstance(s.get("env"), dict) \
                and s["env"].get("ZOTERO_API_KEY") and s["env"].get("ZOTERO_LIBRARY_ID"):
            out[name] = s["env"]
    return out


def resolve_library(library=None, server=None, environ=None, claude_json=None):
    """Return {"key", "type", "id", "source"} for the destination library.

    Resolution order: --library override for type/id; env vars; then the named
    MCP server entry in ~/.claude.json. Raises ConfigError with a message that
    says what was looked at and what is missing. Never called at import time."""
    env = os.environ if environ is None else environ
    path = claude_json or os.path.expanduser("~/.claude.json")
    key = env.get("ZOTERO_API_KEY") or None
    typ = (env.get("ZOTERO_LIBRARY_TYPE") or "").strip().lower() or None
    lib = env.get("ZOTERO_LIBRARY_ID") or env.get("ZOTERO_USER_ID") or None
    if lib and not typ:
        typ = "user"
    source = []
    if key:
        source.append("key from env ZOTERO_API_KEY")
    if lib:
        source.append(f"library from env ({typ}:{lib})")

    if not (key and lib):
        name = server or env.get("ZOTERO_MCP_SERVER") or DEFAULT_SERVER
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            cfg = None
        except (OSError, ValueError) as e:
            raise ConfigError(f"could not read {path}: {e}")
        servers = _zotero_servers(cfg)
        entry = servers.get(name)
        if entry is None and not server and not env.get("ZOTERO_MCP_SERVER") and len(servers) == 1:
            name, entry = next(iter(servers.items()))
        if entry is None:
            have = ", ".join(sorted(servers)) or "none"
            raise ConfigError(
                "no Zotero credentials: set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID "
                f"(+ ZOTERO_LIBRARY_TYPE=group for a group library), or run setup.py zotero "
                f"so {path} has an MCP server entry named {name!r} (entries with Zotero "
                f"credentials there: {have}; pick one with --server)")
        if not key:
            key = entry["ZOTERO_API_KEY"]
            source.append(f"key from {path} mcpServers[{name!r}]")
        if not lib:
            lib = str(entry["ZOTERO_LIBRARY_ID"])
            typ = (entry.get("ZOTERO_LIBRARY_TYPE") or "user").strip().lower()
            source.append(f"library from {path} mcpServers[{name!r}] ({typ}:{lib})")

    if library:
        if ":" not in library:
            raise ConfigError("--library must be user:<ID> or group:<ID>")
        typ, lib = library.split(":", 1)
        typ = typ.strip().lower()
        lib = lib.strip()
        source.append(f"library from --library ({typ}:{lib})")
    if typ not in ("user", "group"):
        raise ConfigError(f"library type must be user or group, not {typ!r}")
    if not str(lib).isdigit():
        raise ConfigError(f"library id should be numeric, not {lib!r}")
    return {"key": key, "type": typ, "id": str(lib), "source": "; ".join(source)}


def base_url(typ, lib):
    return f"{API}/{typ}s/{lib}"


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


def metadata_filename(base, key, item_key):
    """Zotero-style filename from the parent item's metadata:
    "Author - Year - Title.pdf" (case items: "Case Name - Year.pdf").
    Returns None if the metadata can't be fetched — caller falls back."""
    try:
        st, resp = req("GET", f"{base}/items/{item_key}", key)
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


def verify_attachment(base, key, akey, parent, lib, md5=None):
    """Read the attachment back and check parent, destination library, type and
    (when given) md5. Returns a list of problems; empty means verified."""
    try:
        st, resp = req("GET", f"{base}/items/{akey}", key)
    except Exception as e:
        return [f"could not read attachment {akey} back: {type(e).__name__}: {e}"]
    if not isinstance(resp, dict) or not isinstance(resp.get("data"), dict):
        return [f"readback of {akey} was not an item record"]
    d = resp["data"]
    got_lib = resp.get("library") or {}
    problems = []
    if d.get("key") != akey:
        problems.append(f"readback key {d.get('key')!r} != {akey}")
    if d.get("itemType") != "attachment":
        problems.append(f"itemType is {d.get('itemType')!r}, not attachment")
    if d.get("parentItem") != parent:
        problems.append(f"parentItem is {d.get('parentItem')!r}, expected {parent}")
    if got_lib:
        if got_lib.get("type") != lib["type"] or str(got_lib.get("id")) != lib["id"]:
            problems.append(f"stored in library {got_lib.get('type')}:{got_lib.get('id')}, "
                            f"expected {lib['type']}:{lib['id']}")
    if (d.get("contentType") or "").lower() != "application/pdf":
        problems.append(f"contentType is {d.get('contentType')!r}, not application/pdf")
    if md5 and d.get("md5") != md5:
        problems.append(f"stored md5 {d.get('md5')!r} != uploaded {md5}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--item", required=True, help="parent Zotero item key")
    ap.add_argument("--url", help="PDF URL to fetch (Tier 1)")
    ap.add_argument("--file", help="local PDF path (Tier 3 hand-off)")
    ap.add_argument("--title", default="Full Text PDF")
    ap.add_argument("--filename", help="stored filename (defaults from url/file)")
    ap.add_argument("--library", help="destination library, user:<ID> or group:<ID> "
                                      "(default: env, then the MCP server entry in ~/.claude.json)")
    ap.add_argument("--server", help="name of the Zotero MCP server entry in ~/.claude.json "
                                     f"to read credentials from (default: {DEFAULT_SERVER})")
    a = ap.parse_args(argv)
    if not (a.url or a.file) or (a.url and a.file):
        sys.exit("give exactly one of --url or --file")

    try:
        lib = resolve_library(a.library, a.server)
    except ConfigError as e:
        sys.exit(f"FAIL {a.item}: {e}")
    key, base = lib["key"], base_url(lib["type"], lib["id"])
    print(f"destination {lib['type']}:{lib['id']} ({lib['source']})", file=sys.stderr)

    if a.url:
        body = fetch_url(a.url)
        fname = (a.filename or metadata_filename(base, key, a.item)
                 or os.path.basename(urllib.parse.urlparse(a.url).path) or "attachment.pdf")
    else:
        body = open(a.file, "rb").read()
        fname = a.filename or metadata_filename(base, key, a.item) or os.path.basename(a.file)
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    if body[:5] != b"%PDF-":
        sys.exit(f"FAIL {a.item}: fetched bytes are not a PDF (starts {body[:8]!r}) — likely a bot-wall/login page")

    md5 = hashlib.md5(body).hexdigest()
    size = len(body)
    mtime = int(1000 * time.time())

    att = [{"itemType": "attachment", "parentItem": a.item, "linkMode": "imported_file",
            "title": a.title, "contentType": "application/pdf", "filename": fname, "charset": ""}]
    st, resp = req("POST", f"{base}/items", key, json.dumps(att).encode(), {"Content-Type": "application/json"})
    if not isinstance(resp, dict) or "successful" not in resp or "0" not in resp["successful"]:
        sys.exit(f"FAIL {a.item}: could not create attachment item: "
                 f"{resp.get('failed') if isinstance(resp, dict) else resp}")
    akey = resp["successful"]["0"]["key"]

    form = urllib.parse.urlencode({"md5": md5, "filename": fname, "filesize": size, "mtime": mtime}).encode()
    st, auth = req("POST", f"{base}/items/{akey}/file", key, form,
                   {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"})
    if auth.get("exists"):
        upstatus, regstatus = "dedup", "dedup"
    else:
        up = auth["prefix"].encode() + body + auth["suffix"].encode()
        r = urllib.request.Request(auth["url"], data=up, headers={"Content-Type": auth["contentType"]}, method="POST")
        with urllib.request.urlopen(r, timeout=300) as resp:
            upstatus = resp.status
        reg = urllib.parse.urlencode({"upload": auth["uploadKey"]}).encode()
        regstatus, _ = req("POST", f"{base}/items/{akey}/file", key, reg,
                           {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"})
        if upstatus not in (200, 201) or regstatus not in (200, 204):
            sys.exit(f"FAIL {a.item}: upload {upstatus}, register {regstatus} -> attachment {akey} "
                     f"created but the file did not register")

    problems = verify_attachment(base, key, akey, a.item, lib, md5)
    if problems:
        sys.exit(f"FAIL {a.item}: attachment {akey} did not verify on readback: "
                 + "; ".join(problems))
    print(f"PASS {a.item}: attached {fname} ({size} bytes) -> attachment {akey} in "
          f"{lib['type']}:{lib['id']} [upload {upstatus}, register {regstatus}; "
          f"readback: parent, library, application/pdf, md5 all verified]")


if __name__ == "__main__":
    main()
