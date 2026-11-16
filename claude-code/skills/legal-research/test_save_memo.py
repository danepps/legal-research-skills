#!/usr/bin/env python3
"""Checks for save_memo.py (2026-11-16): the memo is copied out of a workflow task output file
byte for byte, the header and footer land where the memo format puts them, an existing file is
never overwritten, and an output file with no memo is reported instead of producing an empty file.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "save_memo.py"

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


MEMO = "# Title of the Memo\n\n## Brief Answer\nYes — see “Alpha v. Beta,” 500 U.S. 1 (1991).\n\n## Limits of this research\nOpen web only.\n"
RESULT = {
    "exitState": "complete_with_limits",
    "degradation": ["1 edit could not be placed"],
    "counts": {"verified": 3, "editsApplied": 4, "editsUnapplied": 1},
    "finalize": {"model": "opus", "callIn": "ran", "callInAuthorities": [{"citation": "Alpha v. Beta", "reasons": ["x"]}],
                 "unappliedEdits": [{"find": "a", "replace": "b", "why": "caveat Gamma", "reason": "not found", "pass": "finalize"}]},
    "memo": MEMO,
}


def run(output_text, dest, *extra):
    with tempfile.NamedTemporaryFile("w", suffix=".output", delete=False, encoding="utf-8") as fh:
        fh.write(output_text)
    p = subprocess.run([sys.executable, str(SCRIPT), fh.name, str(dest), *extra], capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"raw": p.stdout + p.stderr}


with tempfile.TemporaryDirectory() as d:
    d = Path(d)

    print("the task output file as the harness writes it")
    wrapped = json.dumps({"summary": "s", "agentCount": 24, "logs": [], "result": RESULT, "workflowProgress": [], "totalTokens": 1, "totalToolCalls": 2})
    code, out = run(wrapped, d / "a.md")
    check(code == 0 and out.get("saved") and (d / "a.md").read_text(encoding="utf-8") == MEMO, "the memo is copied byte for byte")
    check(out["exitState"] == "complete_with_limits" and out["finalizeModel"] == "opus" and out["callIn"] == "ran", "the summary reports the exit state and how Finalize ran")
    check(len(out["unappliedEdits"]) == 1 and "by hand" in out["next"], "unapplied edits are passed on with the instruction to apply them")
    check(MEMO[:40] not in json.dumps(out), "the summary does not echo the memo")

    print("other shapes of the same result")
    code, out = run(json.dumps({"result": json.dumps(RESULT)}), d / "b.md")
    check(code == 0 and (d / "b.md").read_text(encoding="utf-8") == MEMO, "a result stored as a JSON string")
    code, out = run(json.dumps(RESULT), d / "c.md")
    check(code == 0 and (d / "c.md").read_text(encoding="utf-8") == MEMO, "a bare result")

    print("header and footer")
    code, out = run(wrapped, d / "h.md", "--header", "Topic: T\nDate: 2026-11-16\nBy: Claude", "--footer", "Production details:\nSkill: legal-research")
    text = (d / "h.md").read_text(encoding="utf-8")
    check(text.startswith("# Title of the Memo\n\nTopic: T\nDate: 2026-11-16\nBy: Claude\n\n## Brief Answer\n"), "the header sits directly under the title")
    check(text.endswith("Open web only.\n\n---\n\nProduction details:\nSkill: legal-research\n"), "the footer is the last thing in the file, after a rule")
    check(text.replace("\nTopic: T\nDate: 2026-11-16\nBy: Claude\n", "").replace("\n---\n\nProduction details:\nSkill: legal-research\n", "") == MEMO, "the memo between them is untouched")

    print("a memo that already carries header lines")
    OWN = "# Title\n\nBy: Claude (legal-research skill)\nResearch as of: 2026-11-16\nJurisdiction: U.S. Supreme Court\n\n**Scope warning.** Note: this is prose.\n"
    code, out = run(json.dumps({"result": {**RESULT, "memo": OWN}}), d / "own.md", "--header", "Topic: T\nDate: 2026-11-16\nBy: Claude-model-id")
    text = (d / "own.md").read_text(encoding="utf-8")
    check(text == "# Title\n\nTopic: T\nDate: 2026-11-16\nBy: Claude-model-id\n\nResearch as of: 2026-11-16\nJurisdiction: U.S. Supreme Court\n\n**Scope warning.** Note: this is prose.\n",
          "the memo's own By line is replaced; its other header lines stay, below the header")
    check(out.get("replacedHeaderLines") == ["By: Claude (legal-research skill)"], "the summary names the line replaced")
    code, out = run(json.dumps({"result": {**RESULT, "memo": OWN}}), d / "own2.md")
    check((d / "own2.md").read_text(encoding="utf-8") == OWN and out.get("replacedHeaderLines") == [], "with no header given, nothing is touched")

    print("refusals")
    code, out = run(wrapped, d / "a.md")
    check(code == 2 and not out.get("saved") and (d / "a.md").read_text(encoding="utf-8") == MEMO, "an existing destination is never overwritten")
    code, out = run(json.dumps({"result": {"exitState": "complete"}}), d / "n.md")
    check(code == 1 and not (d / "n.md").exists(), "no memo in the output file: reported, no file written")
    code, out = run("not json at all", d / "j.md")
    check(code == 1 and not (d / "j.md").exists(), "an unreadable output file: reported, no file written")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
