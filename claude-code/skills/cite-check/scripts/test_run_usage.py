#!/usr/bin/env python3
"""Offline test for run_usage.py on a hand-built transcript dir."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_usage as ru  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


def turn(out, inp, cw, cr, tools=()):
    content = [{"type": "tool_use", "name": t} for t in tools]
    return json.dumps({"message": {"role": "assistant", "usage": {"output_tokens": out, "input_tokens": inp,
                                                                    "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr},
                                   "content": content}})


with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, "journal.jsonl"), "w") as j:
        j.write(json.dumps({"type": "launched"}) + "\n")
        j.write(json.dumps({"type": "started", "agentId": "a1", "label": "verify:Doe", "phase": "Verify"}) + "\n")
        j.write(json.dumps({"type": "started", "agentId": "a2", "label": "exist-secondary:5", "phase": "Existence"}) + "\n")
        j.write(json.dumps({"type": "started", "agentId": "a3", "label": "You are assembling", "phase": "Report"}) + "\n")
    with open(os.path.join(td, "agent-a1.jsonl"), "w") as f:
        f.write(turn(1000, 100, 50_000, 0, ("Bash",)) + "\n" + json.dumps({"message": {"role": "user", "content": []}}) + "\n"
                + turn(2000, 0, 5_000, 50_000, ("Bash", "mcp__zotero__zotero_search_items")) + "\n")
    with open(os.path.join(td, "agent-a2.jsonl"), "w") as f:
        f.write(turn(500, 0, 40_000, 0) + "\n")
    with open(os.path.join(td, "agent-a3.jsonl"), "w") as f:
        f.write(turn(10_000, 0, 100_000, 0) + "\n")

    run = ru.read_run(td)
    a = {x["label"]: x for x in run["agents"]}
    check(a["verify:Doe"]["turns"] == 2 and a["verify:Doe"]["output"] == 3000 and a["verify:Doe"]["cacheRead"] == 50_000, "per-agent turns and tokens summed over assistant turns only")
    check(a["verify:Doe"]["peakContext"] == 55_000, "peak context = max over turns of input + cache write + cache read (%d)" % a["verify:Doe"]["peakContext"])
    check(a["verify:Doe"]["iet"] == ru.iet(3000, 100, 55_000, 50_000) == 100 + 55_000 + 5_000 + 15_000, "input-equivalent tokens: input + cache writes + reads/10 + output x 5 (%d)" % a["verify:Doe"]["iet"])
    check(a["verify:Doe"]["kind"] == "verify" and a["exist-secondary:5"]["kind"] == "existWeb" and a["You are assembling"]["kind"] == "report", "cost kinds inferred from label and phase like the workflow")
    check(run["total"]["agents"] == 3 and run["total"]["turns"] == 4 and run["total"]["zoteroToolCalls"] == 1, "totals: agents, turns, Zotero tool calls (%s)" % {k: run["total"][k] for k in ("agents", "turns", "zoteroToolCalls")})
    check(run["total"]["peakContextSum"] == 55_000 + 40_000 + 100_000, "sum of peak contexts (the notification's subagent_tokens)")
    check(run["byKind"]["existWeb"]["ietPerAgent"] == 40_000 + 2_500, "per-kind IET per agent for recalibrating COST")
    text = ru.render(run, projected=100_000)
    check("measured / projected" in text and "sum of peak contexts: 195,000" in text, "render prints the ratio and the peak-context sum")

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
