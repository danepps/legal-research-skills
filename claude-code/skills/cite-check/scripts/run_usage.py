#!/usr/bin/env python3
"""What a cite-check run actually cost, from the workflow's agent transcripts — run after every run.

Why (2026-10-27): the workflow runtime exposes only output tokens (`budget.spent()`), and the
completion notification's `subagent_tokens` is the sum of each agent's PEAK CONTEXT (checked on
two runs: 1,988,912 by the transcripts against 1,989,264 reported; 1,102,009 against 1,102,299).
Neither is the cost. The cost of an agent is its turns times its context, which the transcripts
record per turn as input, cache-write, cache-read and output tokens. This script totals them per
agent and per phase, converts them to the unit the workflow's budget gates project in —
INPUT-EQUIVALENT TOKENS: uncached input + cache writes + cache reads / 10 + output x 5, the
Sonnet price ratios, so 1M is about three dollars at Sonnet rates — and prints the measured
figure beside the projection so the cost model (`COST` in cite-check.workflow.js, `costModel`
arg) can be recalibrated.

Usage:
    python3 run_usage.py <transcript dir>                 # the dir the Workflow launch result names
    python3 run_usage.py <transcript dir> --json          # machine-readable
    python3 run_usage.py <transcript dir> --projected N   # also print measured / projected

The transcript dir holds journal.jsonl (labels and phases per agent) and agent-*.jsonl (one
message per line; assistant messages carry `usage`). Stdlib only; read-only.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

CACHE_READ_WEIGHT = 0.1
OUTPUT_WEIGHT = 5.0


def iet(out: int, inp: int, cw: int, cr: int) -> int:
    return int(round(inp + cw + cr * CACHE_READ_WEIGHT + out * OUTPUT_WEIGHT))


def cost_kind(label: str, phase: str) -> str:
    """The workflow's cost kinds, inferred the same way spawn() infers them (Zotero variants aside)."""
    L = label or ""
    for prefix, kind in (("segment", "segment"), ("exist-secondary", "existWeb"), ("exist", "exist"), ("history", "history"),
                         ("verify-tail", "verifyTail"), ("verify", "verify"), ("support-tail", "supportTail"),
                         ("support", "support"), ("re-verify", "reverify")):
        if L.startswith(prefix):
            return kind
    return {"Form": "form", "Report": "report"}.get(phase or "", "verify")


def read_run(transcript_dir: str) -> dict:
    labels = {}
    jpath = os.path.join(transcript_dir, "journal.jsonl")
    if os.path.exists(jpath):
        for line in open(jpath, encoding="utf-8"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") == "started":
                labels[o.get("agentId")] = (o.get("label") or "", o.get("phase") or "")
    agents = []
    for f in sorted(glob.glob(os.path.join(transcript_dir, "agent-*.jsonl"))):
        aid = os.path.basename(f)[len("agent-"):-len(".jsonl")]
        out = inp = cw = cr = 0
        turns = 0
        peak = 0
        tools = collections.Counter()
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            m = o.get("message") if isinstance(o.get("message"), dict) else None
            u = (m or {}).get("usage")
            if not u or m.get("role") != "assistant":
                continue
            turns += 1
            out += u.get("output_tokens", 0)
            inp += u.get("input_tokens", 0)
            cw += u.get("cache_creation_input_tokens", 0)
            cr += u.get("cache_read_input_tokens", 0)
            peak = max(peak, u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0))
            for c in (m.get("content") or []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tools[c.get("name") or "?"] += 1
        label, phase = labels.get(aid, ("", ""))
        agents.append({"id": aid, "label": label, "phase": phase or "?", "kind": cost_kind(label, phase), "turns": turns,
                       "output": out, "input": inp, "cacheWrite": cw, "cacheRead": cr, "peakContext": peak,
                       "iet": iet(out, inp, cw, cr), "tools": dict(tools)})
    by_phase: dict = collections.OrderedDict()
    by_kind: dict = collections.OrderedDict()
    for a in agents:
        for table, key in ((by_phase, a["phase"]), (by_kind, a["kind"])):
            r = table.setdefault(key, {"agents": 0, "turns": 0, "output": 0, "input": 0, "cacheWrite": 0, "cacheRead": 0, "iet": 0})
            r["agents"] += 1
            for k in ("turns", "output", "input", "cacheWrite", "cacheRead", "iet"):
                r[k] += a[k]
    for r in by_kind.values():
        r["ietPerAgent"] = int(round(r["iet"] / r["agents"])) if r["agents"] else 0
    total = {k: sum(a[k] for a in agents) for k in ("turns", "output", "input", "cacheWrite", "cacheRead", "iet")}
    total["agents"] = len(agents)
    total["peakContextSum"] = sum(a["peakContext"] for a in agents)
    total["zoteroToolCalls"] = sum(n for a in agents for t, n in a["tools"].items() if "zotero" in t.lower())
    return {"dir": transcript_dir, "agents": agents, "byPhase": by_phase, "byKind": by_kind, "total": total}


def render(run: dict, projected: int | None = None) -> str:
    lines = []
    t = run["total"]
    lines.append(f"{'phase':11} {'agents':>6} {'turns':>6} {'output':>8} {'input+cw':>10} {'cache_r':>11} {'IET':>10}")
    for p, r in sorted(run["byPhase"].items(), key=lambda kv: -kv[1]["iet"]):
        lines.append(f"{p[:11]:11} {r['agents']:6} {r['turns']:6} {r['output']:8} {r['input'] + r['cacheWrite']:10} {r['cacheRead']:11} {r['iet']:10}")
    lines.append(f"{'TOTAL':11} {t['agents']:6} {t['turns']:6} {t['output']:8} {t['input'] + t['cacheWrite']:10} {t['cacheRead']:11} {t['iet']:10}")
    lines.append("")
    lines.append(f"{'cost kind':14} {'agents':>6} {'IET/agent':>10}   (compare with COST in cite-check.workflow.js)")
    for k, r in sorted(run["byKind"].items(), key=lambda kv: -kv[1]["ietPerAgent"]):
        lines.append(f"{k:14} {r['agents']:6} {r['ietPerAgent']:10}")
    lines.append("")
    lines.append(f"measured: {t['iet']:,} input-equivalent tokens (about ${t['iet'] / 1_000_000 * 3:.2f} at Sonnet rates); "
                 f"{t['agents']} agents, {t['turns']} turns, {t['zoteroToolCalls']} Zotero tool calls")
    lines.append(f"sum of peak contexts: {t['peakContextSum']:,} (this is what the completion notification reports as subagent_tokens)")
    if projected:
        lines.append(f"projected: {projected:,}; measured / projected = {t['iet'] / projected:.2f}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    d = argv[1]
    if not os.path.isdir(d):
        print(f"not a directory: {d}", file=sys.stderr)
        return 2
    projected = None
    if "--projected" in argv:
        try:
            projected = int(argv[argv.index("--projected") + 1].replace(",", "").replace("_", ""))
        except (IndexError, ValueError):
            print("--projected needs a number", file=sys.stderr)
            return 2
    run = read_run(d)
    if "--json" in argv:
        out = dict(run)
        if projected:
            out["projected"] = projected
            out["measuredOverProjected"] = round(run["total"]["iet"] / projected, 3)
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(render(run, projected))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
