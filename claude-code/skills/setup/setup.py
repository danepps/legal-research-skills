#!/usr/bin/env python3
"""One-time setup helper for the legal-research plugin. Stdlib only.

The model runs this so the user never edits a configuration file by hand.

    python3 setup.py status
        Print a JSON report: Python version, whether the CourtListener token is
        present and actually works, whether WebFetch/WebSearch are pre-allowed,
        whether a Zotero MCP server is configured and uvx is installed, and
        whether git and pdftotext are on the PATH. Read-only.

    python3 setup.py courtlistener <token>
        Save a CourtListener API token to ~/.config/courtlistener/token (mode
        600), which every runtime's scripts read, then confirm it works with a
        live lookup. Prints JSON. Exit 0 only if the lookup succeeded.

    python3 setup.py allow-web
        Add "WebFetch" and "WebSearch" to permissions.allow in
        ~/.claude/settings.json, merging with whatever is there. Prints JSON.

    python3 setup.py enable-workflows
        Set "enableWorkflows": true in ~/.claude/settings.json, the same key the
        Dynamic workflows row in /config writes. Needed on a Claude Pro plan for
        cite-check, proofread, and legal-research; harmless elsewhere. Prints JSON.

    python3 setup.py zotero --key <api-key> --library-id <id> [--type user|group] [--name zotero]
        Register a Zotero MCP server (uvx zotero-mcp) under mcpServers in
        ~/.claude.json, merging with the existing file. Refuses to overwrite an
        entry of the same name unless --replace is given. Takes effect in the
        next session. Prints JSON.

Every writer makes a timestamped backup (<file>.bak-YYYYmmdd-HHMMSS) before it
rewrites a JSON file, and never removes keys it did not add.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
TOKEN_FILE = os.path.join(HOME, ".config", "courtlistener", "token")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CLAUDE_JSON = os.path.join(HOME, ".claude.json")
CL_API = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
PROBE_CITE = "347 U.S. 483"
PROBE_NAME = "Brown v. Board of Education"


# ----------------------------------------------------------------- helpers
def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError) as e:
        return None, f"{path}: {e}"


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    backup = None
    if os.path.exists(path):
        backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, backup)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return backup


def on_path(cmd):
    return shutil.which(cmd) is not None


def python_version():
    v = sys.version_info
    return {"version": f"{v.major}.{v.minor}.{v.micro}", "ok": (v.major, v.minor) >= (3, 11)}


def courtlistener_token():
    for var in ("COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip(), f"environment variable {var}"
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
            if tok:
                return tok, TOKEN_FILE
    except OSError:
        pass
    return None, None


def probe_courtlistener(token):
    """Look up Brown v. Board. Returns (ok, detail)."""
    data = urllib.parse.urlencode({"text": PROBE_CITE}).encode()
    req = urllib.request.Request(
        CL_API, data=data,
        headers={"User-Agent": "legal-research-skill/setup", "Authorization": f"Token {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            results = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"CourtListener rejected the token (HTTP {e.code}); check it was copied whole"
        return False, f"CourtListener returned HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"could not reach CourtListener: {e}"
    for r in results if isinstance(results, list) else []:
        for c in r.get("clusters") or []:
            if PROBE_NAME.lower() in (c.get("case_name") or "").lower():
                return True, f"token works: {PROBE_CITE} resolved to {c.get('case_name')}"
    return False, "token accepted but the probe citation did not resolve; try again later"


def web_allowed(settings):
    allow = ((settings or {}).get("permissions") or {}).get("allow") or []
    return {"WebFetch": "WebFetch" in allow, "WebSearch": "WebSearch" in allow}


def workflows_enabled(settings):
    """None = unset (on for Max/Team/Enterprise, off for Pro); else the explicit value."""
    return (settings or {}).get("enableWorkflows")


def zotero_servers(cfg):
    out = {}
    for name, s in ((cfg or {}).get("mcpServers") or {}).items():
        if not isinstance(s, dict):
            continue
        env = s.get("env") or {}
        if "ZOTERO_API_KEY" in env or "zotero" in (s.get("command") or "") or any("zotero" in str(a) for a in s.get("args") or []):
            out[name] = {
                "command": " ".join([s.get("command") or ""] + [str(a) for a in s.get("args") or []]).strip(),
                "library_type": env.get("ZOTERO_LIBRARY_TYPE", "user"),
                "library_id_set": bool(env.get("ZOTERO_LIBRARY_ID")),
            }
    return out


# ---------------------------------------------------------------- commands
def cmd_status(_args):
    settings, s_err = read_json(SETTINGS)
    cfg, c_err = read_json(CLAUDE_JSON)
    token, source = courtlistener_token()
    cl = {"configured": token is not None, "source": source, "works": None, "detail": None}
    if token:
        cl["works"], cl["detail"] = probe_courtlistener(token)
    report = {
        "python": python_version(),
        "courtlistener": cl,
        "web_permissions": web_allowed(settings),
        "enableWorkflows": workflows_enabled(settings),
        "zotero": {"uvx_installed": on_path("uvx"), "servers": zotero_servers(cfg)},
        "git_installed": on_path("git"),
        "pdftotext_installed": on_path("pdftotext"),
        "files": {"settings": SETTINGS, "claude_json": CLAUDE_JSON, "token_file": TOKEN_FILE},
        "errors": [e for e in (s_err, c_err) if e],
    }
    print(json.dumps(report, indent=2))
    return 0


def cmd_courtlistener(args):
    if len(args) != 1 or not args[0].strip():
        print("usage: setup.py courtlistener <token>", file=sys.stderr)
        return 2
    token = args[0].strip().strip('"').strip("'")
    ok, detail = probe_courtlistener(token)
    if not ok:
        print(json.dumps({"saved": False, "works": False, "detail": detail}))
        return 1
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    print(json.dumps({"saved": True, "works": True, "path": TOKEN_FILE, "detail": detail}))
    return 0


def cmd_allow_web(_args):
    settings, err = read_json(SETTINGS)
    if settings is None:
        print(json.dumps({"ok": False, "detail": err}))
        return 1
    perms = settings.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    added = [t for t in ("WebFetch", "WebSearch") if t not in allow]
    backup = None
    if added:
        allow.extend(added)
        backup = write_json(SETTINGS, settings)
    print(json.dumps({"ok": True, "added": added, "backup": backup, "path": SETTINGS}))
    return 0


def cmd_enable_workflows(_args):
    settings, err = read_json(SETTINGS)
    if settings is None:
        print(json.dumps({"ok": False, "detail": err}))
        return 1
    changed = settings.get("enableWorkflows") is not True
    backup = None
    if changed:
        settings["enableWorkflows"] = True
        backup = write_json(SETTINGS, settings)
    print(json.dumps({"ok": True, "changed": changed, "backup": backup, "path": SETTINGS,
                      "note": "takes effect in the next Claude Code session"}))
    return 0


def cmd_zotero(args):
    opts = {"--type": "user", "--name": "zotero"}
    flags = set()
    it = iter(args)
    for a in it:
        if a == "--replace":
            flags.add("replace")
        elif a in ("--key", "--library-id", "--type", "--name"):
            try:
                opts[a] = next(it)
            except StopIteration:
                print(f"{a} needs a value", file=sys.stderr)
                return 2
        else:
            print(f"unknown argument {a}", file=sys.stderr)
            return 2
    if not opts.get("--key") or not opts.get("--library-id"):
        print("usage: setup.py zotero --key <api-key> --library-id <id> [--type user|group] [--name zotero] [--replace]", file=sys.stderr)
        return 2
    if opts["--type"] not in ("user", "group"):
        print("--type must be user or group", file=sys.stderr)
        return 2
    if not str(opts["--library-id"]).isdigit():
        print("--library-id should be the numeric id shown on zotero.org/settings/keys (or the group's number)", file=sys.stderr)
        return 2
    cfg, err = read_json(CLAUDE_JSON)
    if cfg is None:
        print(json.dumps({"ok": False, "detail": err}))
        return 1
    servers = cfg.setdefault("mcpServers", {})
    name = opts["--name"]
    if name in servers and "replace" not in flags:
        print(json.dumps({"ok": False, "detail": f"an MCP server named {name!r} already exists; pass --replace to overwrite it or --name for a different name"}))
        return 1
    servers[name] = {
        "command": "uvx",
        "args": ["zotero-mcp"],
        "env": {
            "ZOTERO_API_KEY": opts["--key"],
            "ZOTERO_LIBRARY_ID": str(opts["--library-id"]),
            "ZOTERO_LIBRARY_TYPE": opts["--type"],
        },
    }
    backup = write_json(CLAUDE_JSON, cfg)
    print(json.dumps({
        "ok": True, "server": name, "path": CLAUDE_JSON, "backup": backup,
        "uvx_installed": on_path("uvx"),
        "note": "takes effect in the next Claude Code session",
    }))
    return 0


COMMANDS = {
    "status": cmd_status,
    "courtlistener": cmd_courtlistener,
    "allow-web": cmd_allow_web,
    "enable-workflows": cmd_enable_workflows,
    "zotero": cmd_zotero,
}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
