#!/usr/bin/env python3
"""Checkpoint autonomous legal-research state with script-stamped UTC time."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASES = ["frame", "research", "verify", "synthesize", "draft", "audit", "deliver"]
STATUSES = {
    "active",
    "complete",
    "complete_with_limits",
    "needs_input",
    "source_unavailable",
    "budget_exhausted",
    "failed",
}
GATE_STATUSES = {"pending", "pass", "not_applicable", "blocked"}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def assignments(values: list[str], option: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} requires NAME=VALUE: {value!r}")
        name, content = value.split("=", 1)
        if not name.strip():
            raise ValueError(f"{option} has an empty name")
        parsed[name.strip()] = content.strip()
    return parsed


def scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--detail", default="")
    parser.add_argument("--next-action")
    parser.add_argument("--complete-phase", action="append", choices=PHASES, default=[])
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--gate", action="append", default=[], metavar="NAME=STATUS")
    parser.add_argument("--gate-note", action="append", default=[], metavar="NAME=TEXT")
    parser.add_argument("--gate-evidence", action="append", default=[], metavar="NAME=POINTERS")
    parser.add_argument("--artifact", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--assumption", action="append", default=[])
    parser.add_argument("--unresolved", action="append", default=[])
    parser.add_argument("--resolve-unresolved", action="append", default=[])
    parser.add_argument("--blocker", action="append", default=[])
    parser.add_argument("--coverage-cell", action="append", default=[])
    parser.add_argument("--budget", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--actual-usage", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--estimated-usage", action="append", default=[], metavar="NAME=VALUE")
    args = parser.parse_args()

    try:
        gate_updates = assignments(args.gate, "--gate")
        gate_notes = assignments(args.gate_note, "--gate-note")
        gate_evidence = assignments(args.gate_evidence, "--gate-evidence")
        artifact_updates = assignments(args.artifact, "--artifact")
        budget_updates = assignments(args.budget, "--budget")
        actual_usage = assignments(args.actual_usage, "--actual-usage")
        estimated_usage = assignments(args.estimated_usage, "--estimated-usage")
    except ValueError as exc:
        parser.error(str(exc))

    run_dir = args.run_dir.expanduser().resolve()
    manifest_path = run_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read manifest: {exc}")

    gates = manifest.setdefault("completion_gates", {})
    for name, status in gate_updates.items():
        if name not in gates:
            parser.error(f"unknown completion gate: {name}")
        if status not in GATE_STATUSES:
            parser.error(f"invalid gate status for {name}: {status}")
        gates[name]["status"] = status
    for name, note in gate_notes.items():
        if name not in gates:
            parser.error(f"unknown completion gate: {name}")
        gates[name]["note"] = note
    for name, evidence in gate_evidence.items():
        if name not in gates:
            parser.error(f"unknown completion gate: {name}")
        gates[name]["evidence"] = [item.strip() for item in evidence.split(",") if item.strip()]
    for name, value in gates.items():
        if value.get("status") == "pass" and not value.get("evidence"):
            parser.error(f"passing gate {name} requires evidence pointers")

    completed = manifest.setdefault("completed_phases", [])
    for phase in args.complete_phase:
        if phase not in completed:
            completed.append(phase)
    completed.sort(key=PHASES.index)
    manifest["phase"] = args.phase
    if args.next_action is not None:
        manifest["next_action"] = args.next_action
    if args.status is not None:
        manifest["status"] = args.status
    manifest.setdefault("artifacts", {}).update(artifact_updates)
    for field, additions in (
        ("assumptions", args.assumption),
        ("unresolved", args.unresolved),
        ("blockers", args.blocker),
    ):
        values = manifest.setdefault(field, [])
        for addition in additions:
            if addition not in values:
                values.append(addition)
    if args.resolve_unresolved:
        manifest["unresolved"] = [
            item for item in manifest.setdefault("unresolved", []) if item not in args.resolve_unresolved
        ]
    coverage_cells = manifest.setdefault("coverage_cells", [])
    for cell in args.coverage_cell:
        cell = cell.strip()
        if not cell:
            parser.error("--coverage-cell requires a nonempty stable ID")
        if cell not in coverage_cells:
            coverage_cells.append(cell)
    manifest.setdefault("budgets", {}).update(
        {key: scalar(value) for key, value in budget_updates.items()}
    )

    usage = manifest.setdefault("usage", {"availability": "unavailable", "actual": {}, "estimated": {}})
    if actual_usage:
        usage.setdefault("actual", {}).update({key: scalar(value) for key, value in actual_usage.items()})
        usage["availability"] = "actual" if not usage.get("estimated") else "mixed"
    if estimated_usage:
        usage.setdefault("estimated", {}).update(
            {key: scalar(value) for key, value in estimated_usage.items()}
        )
        usage["availability"] = "estimated" if not usage.get("actual") else "mixed"

    now = timestamp()
    manifest["updated_at"] = now
    atomic_json(manifest_path, manifest)

    event = {"timestamp": now, "event": args.event, "phase": args.phase}
    if args.detail:
        event["detail"] = args.detail
    event_path = run_dir / manifest.get("artifacts", {}).get("events", "events.jsonl")
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
