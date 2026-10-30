#!/usr/bin/env python3
"""Offline tests for zotero_servers.py (fake config, fake Zotero API)."""
import io
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zotero_servers as zs  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


CFG = {"mcpServers": {
    "zotero": {"env": {"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "1", "ZOTERO_LIBRARY_TYPE": "user"}},
    "zotero-group": {"env": {"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "77", "ZOTERO_LIBRARY_TYPE": "group"}},
    "zotero-fccl": {"env": {"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "88", "ZOTERO_LIBRARY_TYPE": "group"}},
    "courtlistener": {"env": {"TOKEN": "x"}},
}}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(req, timeout=0):
    if req.full_url.endswith("/groups/77"):
        return Resp(json.dumps({"data": {"name": "Epps–Dave Federalism Project", "description": "<p>Shared sources for the federalism paper with Dave.</p>"}}).encode())
    raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)


print("registered libraries")
regs = zs.registered(CFG)
check([r["server"] for r in regs] == ["zotero", "zotero-fccl", "zotero-group"] and all("key" in r for r in regs), "only servers with a Zotero key and library id, sorted (%s)" % [r["server"] for r in regs])
libs = zs.libraries(CFG, network=True, opener=opener)
by = {l["server"]: l for l in libs}
check(by["zotero"]["label"] == "Personal library" and by["zotero"]["type"] == "user", "the user library is labelled Personal library")
check(by["zotero-group"]["label"] == "Group: Epps–Dave Federalism Project" and "Dave" in by["zotero-group"]["description"], "a group gets its real name and plain-text description from the API")
check(by["zotero-fccl"]["label"] == "Group: fccl" and by["zotero-fccl"]["name"] == "fccl", "a group whose lookup fails falls back to the server's short name")
check(all("key" not in l for l in libs), "the API key never leaves the script")
offline = zs.libraries(CFG, network=False)
check({l["server"]: l["label"] for l in offline}["zotero-group"] == "Group: group", "--no-network uses server names only")

print("description matching")
m = zs.match("my library with Dave", libs)
check(m["match"] and m["match"]["server"] == "zotero-group", "a typed description resolves by shared words with the group name/description (%s)" % m["reason"])
m = zs.match("the one for the federalism paper", libs)
check(m["match"] and m["match"]["server"] == "zotero-group", "shared word 'federalism' resolves it")
m = zs.match("my personal library", libs)
check(m["match"] and m["match"]["server"] == "zotero", "'personal' resolves to the user library")
m = zs.match("the criminal law one", libs)
check(m["match"] is None and len(m["candidates"]) == 2, "no shared words with two groups registered -> no match, both listed as candidates")
one = [l for l in libs if l["server"] != "zotero-fccl"]
m = zs.match("the criminal law one", one)
check(m["match"] and m["match"]["server"] == "zotero-group" and "only one group" in m["reason"], "with a single group registered, any non-personal description resolves to it")
m = zs.match("", libs)
check(m["match"] is None, "empty text never matches")

m = zs.match("5A", [dict(l, name="5A General Law", label="Group: 5A General Law") if l["server"] == "zotero-fccl" else l for l in libs])
check(m["match"] and m["match"]["server"] == "zotero-fccl", "a short token with a digit ('5A') matches the group named with it (%s)" % m["reason"])
check("an" not in zs.words("an 5A ok"), "short words without a digit are still dropped")

print("scopes and unusable servers")
import tempfile
with tempfile.TemporaryDirectory() as proj:
    json.dump({"mcpServers": {"zotero-proj": {"env": {"ZOTERO_API_KEY": "k", "ZOTERO_LIBRARY_ID": "99", "ZOTERO_LIBRARY_TYPE": "group"}}}},
              open(os.path.join(proj, ".mcp.json"), "w"))
    cfg = dict(CFG, projects={os.path.abspath(proj): {"mcpServers": {
        "zotero-desk": {"command": "uvx", "args": ["zotero-mcp"], "env": {"ZOTERO_LOCAL": "true"}}}}})
    names = [r["server"] for r in zs.registered(cfg, project=proj)]
    check("zotero-proj" in names and "zotero" in names, "project .mcp.json servers are listed with user-scope ones (%s)" % names)
    check("zotero-proj" not in [r["server"] for r in zs.registered(cfg)], "without a project, only user scope")
    bad = zs.unusable(cfg, project=proj)
    check([b["server"] for b in bad] == ["zotero-desk"] and bad[0]["local"] and bad[0]["missing"] == ["ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID"],
          "a local-API Zotero server is reported as not usable, not ignored (%s)" % bad)
    check(zs.unusable(cfg) == [], "courtlistener and keyed Zotero servers are never reported unusable")

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
