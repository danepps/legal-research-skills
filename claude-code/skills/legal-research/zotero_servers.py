#!/usr/bin/env python3
"""List the Zotero libraries registered as MCP servers, by their real names — for the up-front dialog.

Why (2026-10-27, DESIGN-upfront-dialog.md): the cite-check dialog offers the registered Zotero
libraries as options by name ("Personal library", "Group: <real group name>"), so nobody types a
server name. A group's name comes from one request to https://api.zotero.org/groups/<id> with the
server's own API key; when that fails or takes too long the server name stands in. The same
script resolves a free-text description the user typed instead ("my library with Dave", "the one
for the federalism paper") against each library's group name, description and server name.

Usage:
    python3 zotero_servers.py                      # JSON list of registered libraries
    python3 zotero_servers.py --text               # one line per library
    python3 zotero_servers.py --match "<text>"     # resolve a description: {"match": ..., "candidates": [...]}
    options: --timeout N (seconds per group lookup, default 5); --no-network (server names only);
             --project DIR (whose .mcp.json and local-scope servers count; default the current directory)

Each library: {"server", "type" (user|group), "id", "name", "description", "label"} where `label`
is the dialog option text. Credentials come from the server entries' `env` (ZOTERO_API_KEY, ZOTERO_LIBRARY_ID,
ZOTERO_LIBRARY_TYPE), the same entries the MCP tools use, in all three Claude Code scopes: user
(~/.claude.json `mcpServers`), project (`<project>/.mcp.json`) and local (~/.claude.json
`projects.<project>.mcpServers`). A Zotero server without those credentials (e.g. one using the
desktop app's local API) is listed by `--text` as NOT USABLE rather than ignored.
Stdlib only; read-only. Exit 0 always (an empty list means no server is registered).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.zotero.org"
TIMEOUT = 5
STOP = set("a an the of and or in on at to for by with from my our its it this that one library lib group project paper article zotero".split())


def load_config() -> dict | None:
    try:
        return json.load(open(os.path.expanduser("~/.claude.json")))
    except (OSError, ValueError):
        return None


def server_entries(config: dict | None, project: str | None = None) -> dict:
    """Every MCP server Claude Code would load in `project`: user scope (~/.claude.json
    `mcpServers`), then the project's `.mcp.json`, then local scope (~/.claude.json
    `projects.<path>.mcpServers`); a later scope wins on a name clash, as in Claude Code."""
    out = dict((config or {}).get("mcpServers") or {})
    if project:
        project = os.path.abspath(project)
        try:
            out.update(json.load(open(os.path.join(project, ".mcp.json"))).get("mcpServers") or {})
        except (OSError, ValueError, AttributeError):
            pass
        out.update((((config or {}).get("projects") or {}).get(project) or {}).get("mcpServers") or {})
    return out


def looks_like_zotero(name: str, entry: dict) -> bool:
    entry = entry or {}
    env = entry.get("env") or {}
    blob = " ".join([name, str(entry.get("command") or ""), str(entry.get("url") or "")] + [str(a) for a in entry.get("args") or []])
    return "zotero" in blob.lower() or any(k.startswith("ZOTERO_") for k in env)


def registered(config: dict | None = None, project: str | None = None) -> list[dict]:
    if config is None:
        config = load_config()
        if config is None and not project:
            return []
    out = []
    for name, entry in sorted(server_entries(config, project).items()):
        env = (entry or {}).get("env") or {}
        key, lib = env.get("ZOTERO_API_KEY"), env.get("ZOTERO_LIBRARY_ID") or env.get("ZOTERO_USER_ID")
        if not key or not lib:
            continue
        out.append({"server": name, "type": "group" if env.get("ZOTERO_LIBRARY_TYPE") == "group" else "user",
                    "id": str(lib), "key": key})
    return out


def unusable(config: dict | None = None, project: str | None = None) -> list[dict]:
    """Zotero servers this skill cannot use: no Web API key and library id (typically a server
    that talks to the Zotero desktop app's local API). Listed so the run can say so in one line
    instead of silently checking scholarship on the web only."""
    if config is None:
        config = load_config()
    out = []
    for name, entry in sorted(server_entries(config, project).items()):
        env = (entry or {}).get("env") or {}
        if not looks_like_zotero(name, entry):
            continue
        key, lib = env.get("ZOTERO_API_KEY"), env.get("ZOTERO_LIBRARY_ID") or env.get("ZOTERO_USER_ID")
        if key and lib:
            continue
        missing = [n for n, v in (("ZOTERO_API_KEY", key), ("ZOTERO_LIBRARY_ID", lib)) if not v]
        out.append({"server": name, "missing": missing,
                    "local": str(env.get("ZOTERO_LOCAL", "")).lower() in ("1", "true", "yes")})
    return out


def group_record(lib: dict, timeout: int = TIMEOUT, opener=None) -> dict:
    """{"name", "description"} for a group library from the Zotero API; empty strings on failure."""
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(f"{API}/groups/{lib['id']}", headers={"Zotero-API-Key": lib["key"], "Zotero-API-Version": "3",
                                                                       "User-Agent": "legal-research-skill/1.0"})
    try:
        with opener(req, timeout=timeout) as resp:
            o = json.loads(resp.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError):
        return {"name": "", "description": ""}
    data = o.get("data") or {}
    return {"name": data.get("name") or "", "description": re.sub(r"<[^>]+>", " ", data.get("description") or "").strip()}


def libraries(config: dict | None = None, network: bool = True, timeout: int = TIMEOUT, opener=None,
              project: str | None = None) -> list[dict]:
    libs = []
    for lib in registered(config, project):
        rec = group_record(lib, timeout, opener) if (network and lib["type"] == "group") else {"name": "", "description": ""}
        short = lib["server"][len("zotero-"):] if lib["server"].startswith("zotero-") else lib["server"]
        name = rec["name"] or (short if lib["type"] == "group" else "Personal library")
        label = "Personal library" if lib["type"] == "user" else f"Group: {name}"
        libs.append({"server": lib["server"], "type": lib["type"], "id": lib["id"], "name": name,
                     "description": rec["description"], "label": label})
    return libs


def words(s: str) -> set[str]:
    # A short token counts when it carries a digit ("5A", "2L"), which is how groups get told apart.
    return {w for w in re.split(r"[^a-z0-9]+", (s or "").lower())
            if (len(w) >= 3 or (len(w) >= 2 and any(c.isdigit() for c in w))) and w not in STOP}


def match(text: str, libs: list[dict]) -> dict:
    """Resolve a typed description. One clear match -> {"match": lib}; otherwise candidates."""
    t = (text or "").strip().lower()
    groups = [l for l in libs if l["type"] == "group"]
    personal = [l for l in libs if l["type"] == "user"]
    if re.search(r"\b(personal|my own|mine|own library)\b", t) and personal:
        return {"match": personal[0], "candidates": [], "reason": "personal"}
    tw = words(t)
    scored = []
    for l in groups:
        hay = words(l["name"]) | words(l["description"]) | words(l["server"].replace("zotero-", ""))
        shared = tw & hay
        if shared:
            scored.append((len(shared), l, sorted(shared)))
    scored.sort(key=lambda x: -x[0])
    if len(scored) == 1 or (len(scored) > 1 and scored[0][0] > scored[1][0]):
        return {"match": scored[0][1], "candidates": [s[1] for s in scored[1:]], "reason": "shared words: " + ", ".join(scored[0][2])}
    if not scored and len(groups) == 1 and tw:
        return {"match": groups[0], "candidates": [], "reason": "only one group library is registered"}
    return {"match": None, "candidates": [s[1] for s in scored] or groups, "reason": "no single match"}


def main(argv: list[str]) -> int:
    network = "--no-network" not in argv
    timeout = TIMEOUT
    if "--timeout" in argv:
        try:
            timeout = int(argv[argv.index("--timeout") + 1])
        except (IndexError, ValueError):
            pass
    project = os.getcwd()
    if "--project" in argv:
        try:
            project = argv[argv.index("--project") + 1]
        except IndexError:
            print("--project needs a directory", file=sys.stderr)
            return 2
    libs = libraries(network=network, timeout=timeout, project=project)
    if "--match" in argv:
        try:
            text = argv[argv.index("--match") + 1]
        except IndexError:
            print("--match needs the typed text", file=sys.stderr)
            return 2
        print(json.dumps(match(text, libs), ensure_ascii=False))
        return 0
    if "--text" in argv:
        for l in libs:
            print(f"{l['server']:16} {l['type']:5} {l['id']:>8}  {l['label']}" + (f" — {l['description'][:80]}" if l["description"] else ""))
        bad = unusable(project=project)
        for u in bad:
            how = "local desktop API" if u["local"] else "no Web API credentials"
            print(f"{u['server']:16} NOT USABLE ({how}; missing {', '.join(u['missing'])}) — run /legal-research:setup to add an API key")
        if not libs and not bad:
            print("no Zotero MCP server registered")
        return 0
    print(json.dumps(libs, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
