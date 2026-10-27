#!/usr/bin/env python3
"""Summarize explicitly supplied Codex session logs without double-counting counters.

Counts requests reported during the inclusive --start/--end window. A request may
have started before that window. Cached input is a subset of input; reasoning is
a subset of output. This reports usage, not prices or an enforced spending limit.
No logs are discovered or modified. Keep the output in the hidden run directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

REQUIRED = ("input_tokens", "output_tokens", "total_tokens")
OPTIONAL = ("cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens")


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return result


def usage_values(value: dict) -> dict:
    result = {}
    for key in REQUIRED + OPTIONAL:
        number = value.get(key)
        if key in OPTIONAL and number is None:
            result[key] = None
            continue
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ValueError(f"invalid runtime counter: {key}")
        result[key] = number
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        raise ValueError("unsupported token schema: total is not input + output")
    for subset, whole in (("cached_input_tokens", "input_tokens"), ("reasoning_output_tokens", "output_tokens")):
        if result[subset] is not None and result[subset] > result[whole]:
            raise ValueError(f"unsupported token schema: {subset} exceeds {whole}")
    return result


def summarize_session(path: Path, start: datetime | None, end: datetime | None) -> dict:
    session_id = None
    session_started = None
    ancestor_ids = set()
    baseline = {key: 0 for key in REQUIRED + OPTIONAL}
    previous = None
    latest = None
    generations = 0
    first_at = last_at = None
    previous_time = None
    baseline_basis = "session_lifetime" if start is None else None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        payload = entry.get("payload") or {}
        if entry.get("type") == "session_meta":
            # Forked logs may carry the parent's metadata in their copied prefix.
            # The first metadata record owns the file; do not relabel it as its parent.
            identity = payload.get("id")
            if session_id is None:
                session_id = identity
                if payload.get("timestamp"):
                    session_started = instant(payload["timestamp"])
            elif identity != session_id and identity not in ancestor_ids:
                raise ValueError("multiple unrelated session identities in one log")
            if payload.get("forked_from_id"):
                ancestor_ids.add(payload["forked_from_id"])
        if entry.get("type") != "event_msg" or payload.get("type") != "token_count":
            continue
        raw = (payload.get("info") or {}).get("total_token_usage")
        if raw is None:
            continue
        when = instant(entry["timestamp"])
        if session_started and when < session_started:
            continue
        if end and when > end:
            continue
        counters = usage_values(raw)
        if previous_time and when < previous_time:
            raise ValueError("usage timestamps are out of order")
        if previous:
            for key, number in counters.items():
                if number is not None and previous[key] is not None and number < previous[key]:
                    raise ValueError(f"runtime counter reset: {key}; use separate session segments")
        changed = not previous or counters["total_tokens"] != previous["total_tokens"]
        previous, previous_time = counters, when
        if start and when < start:
            baseline = counters
            baseline_basis = "observed_counter_before_window"
            continue
        if baseline_basis is None:
            if session_started and session_started >= start:
                baseline_basis = "session_started_in_window"
            elif (payload.get("info") or {}).get("last_token_usage"):
                last = usage_values(payload["info"]["last_token_usage"])
                if all(last[k] == counters[k] for k in REQUIRED):
                    baseline_basis = "first_request_reported_in_window"
            if baseline_basis is None:
                baseline_basis = "unavailable_pre_window_counter"
        if changed:
            generations += 1
            first_at = first_at or entry["timestamp"]
            last_at = entry["timestamp"]
        latest = counters
    if not session_id:
        raise ValueError(f"missing Codex session identity: {path.name}")
    totals = None if latest is None or baseline_basis == "unavailable_pre_window_counter" else {
        key: latest[key] - baseline[key] if latest[key] is not None and baseline[key] is not None else None
        for key in REQUIRED + OPTIONAL
    }
    if totals is not None:
        # Individually plausible snapshots can yield impossible window deltas.
        totals = usage_values(totals)
    return {"session_id": session_id, "log": str(path.resolve()),
            "status": "measured" if totals is not None else "unavailable",
            "baseline_basis": baseline_basis,
            "generations": generations, "first_usage_at": first_at, "last_usage_at": last_at,
            "tokens": totals}


def build_report(paths: list[Path], start: datetime | None = None, end: datetime | None = None) -> dict:
    if start and end and start > end:
        raise ValueError("start must not follow end")
    sessions = []
    identities = set()
    for path in dict.fromkeys(p.resolve() for p in paths):
        summary = summarize_session(path, start, end)
        if summary["session_id"] in identities:
            raise ValueError("duplicate session identity: supply only one log per session")
        identities.add(summary["session_id"])
        sessions.append(summary)
    measured = [s["tokens"] for s in sessions if s["tokens"] is not None]
    complete = bool(sessions) and len(measured) == len(sessions)
    totals = {key: sum(m[key] for m in measured)
              if complete and all(m[key] is not None for m in measured) else None
              for key in REQUIRED + OPTIONAL}
    return {"schema_version": 1, "status": "measured" if complete else "unavailable",
            "window": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
            "basis": "Cumulative-counter differences for explicitly supplied sessions; cached input and reasoning are subsets, not additional tokens.",
            "limitations": "Not a price estimate or a hard cap. Includes requests reported in this window; they may have started earlier. Unlisted workers are not included.",
            "sessions": sessions, "tokens": totals}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, action="append", required=True)
    parser.add_argument("--start", type=instant)
    parser.add_argument("--end", type=instant)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.session, args.start, args.end)
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            if args.output.resolve() in {p.resolve() for p in args.session}:
                raise ValueError("output must not overwrite a session log")
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
