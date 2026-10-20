#!/usr/bin/env python3
"""Self-test for setup.py. Run: python3 test_setup.py

Everything happens in a temp directory with dummy values: the token file, settings.json
and .claude.json paths are patched, the live CourtListener probe is stubbed, and the
environment is restored afterwards. No network, no real credentials, nothing under ~.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("setup_mod", os.path.join(HERE, "setup.py"))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails += 1


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def run_cmd(fn, args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(args)
    return rc, json.loads(buf.getvalue())


@contextlib.contextmanager
def env(**values):
    """Set (or, for None, clear) environment variables for the block, then restore."""
    saved = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


tmp = tempfile.mkdtemp()
old_umask = os.umask(0o022)      # the default umask the review tested under
setup.TOKEN_FILE = os.path.join(tmp, "config", "courtlistener", "token")
setup.SETTINGS = os.path.join(tmp, "claude", "settings.json")
setup.CLAUDE_JSON = os.path.join(tmp, "claude.json")
setup.probe_courtlistener = lambda tok: (True, "probe stubbed")
NO_ENV = {"COURTLISTENER_API_TOKEN": None, "COURTLISTENER_TOKEN": None}

try:
    # ---- CLAUDE-05: atomic replace keeps restrictive modes ------------------------------
    p = os.path.join(tmp, "existing600.json")
    with open(p, "w") as f:
        json.dump({"a": 1}, f)
    os.chmod(p, 0o600)
    backup = setup.write_json(p, {"a": 2, "secret": "dummy"})
    check("existing 0600 file stays 0600 after write_json", mode(p) == 0o600)
    check("content replaced", json.load(open(p)) == {"a": 2, "secret": "dummy"})
    check("backup of a 0600 file is 0600", backup and mode(backup) == 0o600)
    check("no temp file left behind", not [n for n in os.listdir(tmp) if ".tmp-" in n])

    p = os.path.join(tmp, "existing644.json")
    with open(p, "w") as f:
        json.dump({"mcpServers": {}}, f)
    os.chmod(p, 0o644)
    setup.write_json(p, {"mcpServers": {}})
    check("existing 0644 non-credential file keeps 0644", mode(p) == 0o644)
    backup = setup.write_json(p, {"mcpServers": {"z": {"env": {"ZOTERO_API_KEY": "dummy"}}}}, private=True)
    check("existing 0644 file is tightened to 0600 when written as private", mode(p) == 0o600)
    check("backup of a file written as private is 0600", backup and mode(backup) == 0o600)

    p = os.path.join(tmp, "new_private.json")
    setup.write_json(p, {"key": "dummy"}, private=True)
    check("newly created credential file is 0600", mode(p) == 0o600)

    p = os.path.join(tmp, "new_plain.json")
    setup.write_json(p, {"x": 1})
    check("newly created non-credential file gets the umask default (0644)", mode(p) == 0o644)

    # the zotero command writes the MCP config as a credential file
    with env(**NO_ENV):
        rc, out = run_cmd(setup.cmd_zotero, ["--key", "dummy-zotero-key", "--library-id", "123"])
    check("zotero: ok", rc == 0 and out.get("ok") is True)
    check("zotero: new ~/.claude.json carrying the key is 0600", mode(setup.CLAUDE_JSON) == 0o600)
    check("zotero: key stored", json.load(open(setup.CLAUDE_JSON))["mcpServers"]["zotero"]["env"]["ZOTERO_API_KEY"] == "dummy-zotero-key")
    os.chmod(setup.CLAUDE_JSON, 0o644)
    with env(**NO_ENV):
        rc, out = run_cmd(setup.cmd_zotero, ["--key", "dummy-zotero-key-2", "--library-id", "123", "--replace"])
    check("zotero: existing 0644 ~/.claude.json is tightened to 0600 on rewrite", rc == 0 and mode(setup.CLAUDE_JSON) == 0o600)

    # the courtlistener command saves the token file 0600
    with env(**NO_ENV):
        rc, out = run_cmd(setup.cmd_courtlistener, ["dummy-new-token"])
    check("courtlistener: saved, works, exit 0", rc == 0 and out.get("saved") and out.get("works"))
    check("courtlistener: token file is 0600", mode(setup.TOKEN_FILE) == 0o600)
    check("courtlistener: token file holds the token", open(setup.TOKEN_FILE).read() == "dummy-new-token\n")
    check("courtlistener: no env var, so the file is effective and there is no warning",
          out.get("effective") is True and out.get("effective_source") == setup.TOKEN_FILE and "warning" not in out)
    os.chmod(setup.TOKEN_FILE, 0o644)
    with env(**NO_ENV):
        run_cmd(setup.cmd_courtlistener, ["dummy-new-token"])
    check("courtlistener: a loosened token file is tightened back to 0600", mode(setup.TOKEN_FILE) == 0o600)

    # ---- CLAUDE-12: an environment token overrides the file just saved ------------------
    with env(COURTLISTENER_API_TOKEN="dummy-old-env-token", COURTLISTENER_TOKEN=None):
        rc, out = run_cmd(setup.cmd_courtlistener, ["dummy-new-token"])
    check("override: still saved and exit 0", rc == 0 and out.get("saved") is True)
    check("override: reported as not effective", out.get("effective") is False)
    check("override: effective source names the variable",
          out.get("effective_source") == "environment variable COURTLISTENER_API_TOKEN")
    check("override: warning names the variable and the shell profile / settings env block",
          "COURTLISTENER_API_TOKEN" in out.get("warning", "")
          and "shell profile" in out.get("warning", "") and setup.SETTINGS in out.get("warning", ""))
    check("override: file still holds the new token", open(setup.TOKEN_FILE).read() == "dummy-new-token\n")

    with env(COURTLISTENER_API_TOKEN=None, COURTLISTENER_TOKEN="dummy-old-env-token"):
        rc, out = run_cmd(setup.cmd_courtlistener, ["dummy-new-token"])
    check("override: the second variable is named when it is the one set",
          "COURTLISTENER_TOKEN" in out.get("warning", "") and "COURTLISTENER_API_TOKEN" not in out.get("warning", ""))

    os.makedirs(os.path.dirname(setup.SETTINGS), exist_ok=True)
    with open(setup.SETTINGS, "w") as f:
        json.dump({"env": {"COURTLISTENER_API_TOKEN": "dummy-old-env-token"}}, f)
    with env(COURTLISTENER_API_TOKEN="dummy-old-env-token", COURTLISTENER_TOKEN=None):
        rc, out = run_cmd(setup.cmd_courtlistener, ["dummy-new-token"])
    check("override: points at settings.json's env block when the variable is defined there",
          out.get("warning", "").startswith("the environment variable COURTLISTENER_API_TOKEN")
          and f'"env" block of {setup.SETTINGS}' in out["warning"] and "shell profile" not in out["warning"])
    check("override: settings.json was not rewritten",
          json.load(open(setup.SETTINGS)) == {"env": {"COURTLISTENER_API_TOKEN": "dummy-old-env-token"}}
          and not [n for n in os.listdir(os.path.dirname(setup.SETTINGS)) if ".bak-" in n])

    with env(COURTLISTENER_API_TOKEN="dummy-new-token", COURTLISTENER_TOKEN=None):
        rc, out = run_cmd(setup.cmd_courtlistener, ["dummy-new-token"])
    check("override: same token in the environment is effective, no warning",
          out.get("effective") is True and "warning" not in out)

    with env(COURTLISTENER_API_TOKEN="dummy-old-env-token", COURTLISTENER_TOKEN=None):
        rc, out = run_cmd(setup.cmd_status, [])
    cl = out.get("courtlistener", {})
    check("status: reports the environment source and that it overrides the file",
          cl.get("source") == "environment variable COURTLISTENER_API_TOKEN"
          and cl.get("token_file_present") is True and cl.get("env_overrides_file") is True)
finally:
    os.umask(old_umask)
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
