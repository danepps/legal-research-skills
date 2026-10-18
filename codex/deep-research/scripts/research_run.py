#!/usr/bin/env python3
"""Manage state, staged subagent lanes, and validation for deep-research runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEPTHS = {"focused", "standard", "deep"}
EXIT_STATES = {
    "complete",
    "complete_with_limits",
    "needs_input",
    "source_unavailable",
    "budget_exhausted",
    "failed",
}
ACTIVE_STATES = {"initialized", "running", "synthesis", "audit"}
SOURCE_ROLES = {
    "direct_answer",
    "assumed_baseline",
    "method_or_process_only",
    "boundary_or_transition",
    "contrary_example",
    "adjacent_domain_analogy",
    "historical_background",
    "later_interpretation",
    "scholarly_analysis",
    "factual_record",
}
CLAIM_STATUSES = {
    "directly_supported",
    "indirectly_supported",
    "disputed",
    "stale",
    "unverified",
}
CONFIDENCE = {"high", "medium", "low"}
VERIFICATION_STATUSES = {"direct", "partial", "lead_only", "verified", "unverified"}
CLAIM_REQUIRED = {
    "claim_id",
    "subquestion",
    "coverage_cell",
    "importance",
    "evidence_needed",
    "status",
    "supporting_source_ids",
    "contrary_source_ids",
    "confidence",
}
SOURCE_REQUIRED = {
    "source_id",
    "canonical_location",
    "title_or_citation",
    "publisher_or_court",
    "date_or_version",
    "source_type",
    "source_role",
    "coverage_cells",
    "distinct_contribution",
    "relevant_passage_or_data",
    "supported_claim_ids",
    "reliability_notes",
    "verification_status",
}
LANE_STAGES = (
    "discovery",
    "read",
    "gap_fill",
    "verification",
    "mechanical_audit",
    "critique",
)
STAGE_ORDER = {
    "discovery": 0,
    "read": 1,
    "gap_fill": 2,
    "verification": 3,
    "mechanical_audit": 3,
    "critique": 4,
}
LANE_ROLES = {"research_mechanical", "research_balanced", "research_critic"}
STAGE_ROLES = {
    "discovery": {"research_mechanical", "research_balanced"},
    "read": {"research_balanced"},
    "gap_fill": {"research_balanced"},
    "verification": {"research_balanced"},
    "mechanical_audit": {"research_mechanical"},
    "critique": {"research_critic"},
}
LANE_STATUSES = {"pending", "running", "completed", "partial", "failed", "blocked"}
LANE_TERMINAL = {"completed", "partial", "failed", "blocked"}
LANE_SUCCESS = {"completed", "partial"}
DEPTH_WORKER_CAPS = {"focused": 2, "standard": 12, "deep": 32}
DEFAULT_LANE_ALLOCATIONS = {"focused": 2, "standard": 8, "deep": 24}
DEFAULT_INTERACTION_CAPS = {"focused": 3, "standard": 12, "deep": 36}
DEFAULT_FOLLOWUP_CAPS = {"focused": 1, "standard": 4, "deep": 8}
STAGE_CAPS = {
    "focused": {
        "discovery": 1,
        "read": 2,
        "gap_fill": 1,
        "verification": 2,
        "mechanical_audit": 1,
        "critique": 1,
    },
    "standard": {
        "discovery": 3,
        "read": 6,
        "gap_fill": 2,
        "verification": 4,
        "mechanical_audit": 1,
        "critique": 1,
    },
    "deep": {
        "discovery": 5,
        "read": 12,
        "gap_fill": 3,
        "verification": 20,
        "mechanical_audit": 2,
        "critique": 1,
    },
}
PACKET_REQUIRED = {
    "lane_id",
    "stage",
    "status",
    "exit_reason",
    "sources",
    "claims",
    "gaps",
    "confidence",
}
VOTE_VERDICTS = {"supported", "adverse", "uncertain"}
RESOLUTION_DISPOSITIONS = {
    "confirmed_after_lead_review",
    "narrowed",
    "disputed",
    "removed",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fail(message: str) -> None:
    raise SystemExit(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing required file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected a JSON object in {path}")
    return value


def parse_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"invalid {label} JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_event(run_dir: Path, event: dict[str, Any]) -> None:
    event.setdefault("timestamp", now())
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def lane_manifest_path(run_dir: Path) -> Path:
    return run_dir / "lane-manifest.json"


def load_lane_input(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    lanes = payload.get("lanes")
    if not isinstance(lanes, list) or any(not isinstance(lane, dict) for lane in lanes):
        fail(f"{path} must contain a lanes array of objects")
    return lanes


def normalize_lane(lane: dict[str, Any]) -> dict[str, Any]:
    lane_id = lane.get("lane_id")
    stage = lane.get("stage")
    output_path = lane.get("output_path") or (
        f"packets/{stage}/{lane_id}.json" if lane_id and stage else ""
    )
    return {
        **lane,
        "dependencies": lane.get("dependencies", []),
        "claim_ids": lane.get("claim_ids", []),
        "coverage_cells": lane.get("coverage_cells", []),
        "output_path": output_path,
        "status": "pending",
        "attempts": 0,
        "max_attempts": lane.get("max_attempts", 2),
        "followups": 0,
        "max_followups": lane.get("max_followups", 1),
        "fresh_context": lane.get("fresh_context", True),
        "required": lane.get("required", True),
        "created_at": now(),
        "updated_at": now(),
    }


def manifest_validation(
    manifest: dict[str, Any], run_dir: Path, depth: str, check_packets: bool
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    lanes = manifest.get("lanes")
    if not isinstance(lanes, list):
        return ["lane-manifest.json lanes must be an array"], warnings
    if len(lanes) > DEPTH_WORKER_CAPS.get(depth, 0):
        errors.append(
            f"lane count {len(lanes)} exceeds {depth} ceiling {DEPTH_WORKER_CAPS.get(depth)}"
        )
    ids: set[str] = set()
    outputs: set[str] = set()
    stage_counts = {stage: 0 for stage in LANE_STAGES}
    by_id: dict[str, dict[str, Any]] = {}
    for index, lane in enumerate(lanes, 1):
        if not isinstance(lane, dict):
            errors.append(f"lane {index} must be an object")
            continue
        lane_id = lane.get("lane_id")
        label = lane_id or str(index)
        if not isinstance(lane_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", lane_id):
            errors.append(f"lane {index} has invalid lane_id")
        elif lane_id in ids:
            errors.append(f"duplicate lane_id {lane_id}")
        else:
            ids.add(lane_id)
            by_id[lane_id] = lane
        stage = lane.get("stage")
        if stage not in STAGE_ORDER:
            errors.append(f"lane {label} has invalid stage")
        else:
            stage_counts[stage] += 1
        if lane.get("role") not in LANE_ROLES:
            errors.append(f"lane {label} has invalid role")
        elif stage in STAGE_ROLES and lane.get("role") not in STAGE_ROLES[stage]:
            errors.append(
                f"lane {label} role {lane.get('role')} is invalid for stage {stage}"
            )
        if not isinstance(lane.get("task"), str) or not lane.get("task", "").strip():
            errors.append(f"lane {label} has no task")
        if lane.get("status") not in LANE_STATUSES:
            errors.append(f"lane {label} has invalid status")
        if lane.get("fresh_context") is not True:
            errors.append(f"lane {label} must use fresh_context=true")
        if not isinstance(lane.get("required"), bool):
            errors.append(f"lane {label} required must be boolean")
        for field in ("dependencies", "claim_ids", "coverage_cells"):
            value = lane.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                errors.append(f"lane {label} {field} must be a list of strings")
        budget = lane.get("budget", {})
        if not isinstance(budget, dict):
            errors.append(f"lane {label} budget must be an object")
        else:
            for key, value in budget.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    errors.append(f"lane {label} budget {key} must be nonnegative")
        vote_group = lane.get("vote_group")
        if vote_group is not None:
            if not isinstance(vote_group, str) or not vote_group:
                errors.append(f"lane {label} vote_group must be a nonempty string")
            elif stage != "verification":
                errors.append(f"lane {label} vote_group is allowed only for verification")
            elif vote_group not in lane.get("claim_ids", []):
                errors.append(f"lane {label} vote_group must appear in claim_ids")
        attempts = lane.get("attempts")
        max_attempts = lane.get("max_attempts")
        followups = lane.get("followups")
        max_followups = lane.get("max_followups")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
            errors.append(f"lane {label} attempts must be a nonnegative integer")
        if (
            not isinstance(max_attempts, int)
            or isinstance(max_attempts, bool)
            or max_attempts < 1
            or max_attempts > 2
        ):
            errors.append(f"lane {label} max_attempts must be 1 or 2")
        elif isinstance(attempts, int) and attempts > max_attempts:
            errors.append(f"lane {label} attempts exceed max_attempts")
        if not isinstance(followups, int) or isinstance(followups, bool) or followups < 0:
            errors.append(f"lane {label} followups must be a nonnegative integer")
        if (
            not isinstance(max_followups, int)
            or isinstance(max_followups, bool)
            or max_followups not in {0, 1}
        ):
            errors.append(f"lane {label} max_followups must be 0 or 1")
        elif isinstance(followups, int) and followups > max_followups:
            errors.append(f"lane {label} followups exceed max_followups")
        output_path = lane.get("output_path")
        if not isinstance(output_path, str):
            errors.append(f"lane {label} output_path must be a string")
        else:
            relative = Path(output_path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or len(relative.parts) < 3
                or relative.parts[0] != "packets"
                or relative.parts[1] != stage
                or relative.suffix != ".json"
            ):
                errors.append(f"lane {label} has invalid packet path {output_path}")
            elif output_path in outputs:
                errors.append(f"duplicate packet path {output_path}")
            else:
                outputs.add(output_path)
        if check_packets and lane.get("status") in LANE_SUCCESS and isinstance(output_path, str):
            packet_path = run_dir / output_path
            if not packet_path.is_file():
                errors.append(f"lane {label} missing registered packet {output_path}")
            else:
                try:
                    packet = json.loads(packet_path.read_text(encoding="utf-8"))
                    if not isinstance(packet, dict):
                        raise ValueError("not an object")
                    missing = PACKET_REQUIRED - packet.keys()
                    if missing:
                        errors.append(f"packet {output_path} missing {sorted(missing)}")
                    if packet.get("lane_id") != lane_id:
                        errors.append(f"packet {output_path} lane_id mismatch")
                    if packet.get("stage") != stage:
                        errors.append(f"packet {output_path} stage mismatch")
                    if packet.get("status") != lane.get("status"):
                        errors.append(f"packet {output_path} status mismatch")
                    for field in ("sources", "claims", "gaps"):
                        if not isinstance(packet.get(field), list):
                            errors.append(f"packet {output_path} {field} must be an array")
                    if packet.get("confidence") not in CONFIDENCE:
                        errors.append(f"packet {output_path} has invalid confidence")
                    if isinstance(vote_group, str):
                        vote_claims = [
                            claim
                            for claim in packet.get("claims", [])
                            if isinstance(claim, dict) and claim.get("claim_id") == vote_group
                        ]
                        if len(vote_claims) != 1:
                            errors.append(
                                f"vote packet {output_path} must contain exactly one result for {vote_group}"
                            )
                        elif vote_claims[0].get("verdict") not in VOTE_VERDICTS:
                            errors.append(
                                f"vote packet {output_path} has invalid verdict for {vote_group}"
                            )
                    packet_hash = lane.get("packet_sha256")
                    if packet_hash and packet_hash != sha256(packet_path):
                        errors.append(f"packet {output_path} hash differs from manifest")
                except (json.JSONDecodeError, ValueError) as exc:
                    errors.append(f"invalid packet {output_path}: {exc}")
    caps = STAGE_CAPS.get(depth, {})
    for stage, count in stage_counts.items():
        if count > caps.get(stage, 0):
            errors.append(f"{stage} lane count {count} exceeds {depth} cap {caps.get(stage)}")
    for lane_id, lane in by_id.items():
        for dependency in lane.get("dependencies", []):
            if dependency == lane_id:
                errors.append(f"lane {lane_id} depends on itself")
            elif dependency not in by_id:
                errors.append(f"lane {lane_id} has unknown dependency {dependency}")
            elif STAGE_ORDER.get(by_id[dependency].get("stage"), 99) > STAGE_ORDER.get(
                lane.get("stage"), -1
            ):
                errors.append(f"lane {lane_id} depends on later-stage lane {dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(lane_id: str) -> None:
        if lane_id in visiting:
            errors.append(f"lane dependency cycle includes {lane_id}")
            return
        if lane_id in visited:
            return
        visiting.add(lane_id)
        for dependency in by_id.get(lane_id, {}).get("dependencies", []):
            if dependency in by_id:
                visit(dependency)
        visiting.remove(lane_id)
        visited.add(lane_id)

    for lane_id in by_id:
        visit(lane_id)
    for lane_id, lane in by_id.items():
        lane_rank = STAGE_ORDER.get(lane.get("stage"), -1)
        if lane_rank <= 0:
            continue
        closure: set[str] = set()
        stack = list(lane.get("dependencies", []))
        while stack:
            dependency = stack.pop()
            if dependency in closure or dependency not in by_id:
                continue
            closure.add(dependency)
            stack.extend(by_id[dependency].get("dependencies", []))
        required_predecessors = {
            predecessor_id
            for predecessor_id, predecessor in by_id.items()
            if predecessor.get("required")
            and STAGE_ORDER.get(predecessor.get("stage"), 99) < lane_rank
        }
        missing_predecessors = sorted(required_predecessors - closure)
        if missing_predecessors:
            errors.append(
                f"lane {lane_id} does not depend on required predecessor lanes {missing_predecessors}"
            )
    return errors, warnings


def ready_lanes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = manifest.get("lanes", [])
    by_id = {lane.get("lane_id"): lane for lane in lanes if isinstance(lane, dict)}
    ready: list[dict[str, Any]] = []
    for lane in lanes:
        if not isinstance(lane, dict) or lane.get("status") not in {"pending", "failed"}:
            continue
        if lane.get("attempts", 0) >= lane.get("max_attempts", 2):
            continue
        if all(by_id.get(dep, {}).get("status") in LANE_SUCCESS for dep in lane.get("dependencies", [])):
            ready.append(lane)
    if not ready:
        return []
    earliest = min(STAGE_ORDER[lane["stage"]] for lane in ready)
    return sorted(
        (lane for lane in ready if STAGE_ORDER[lane["stage"]] == earliest),
        key=lambda lane: lane["lane_id"],
    )


def validate_request(request: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("question", "depth", "cutoff"):
        if not request.get(field):
            errors.append(f"request.json missing nonempty {field}")
    if request.get("depth") not in DEPTHS:
        errors.append("request.json depth must be focused, standard, or deep")
    depth = request.get("depth")
    if depth == "deep" and request.get("plan_accepted") is not True:
        errors.append("deep runs require plan_accepted=true")
    if request.get("verification_quorum", "adaptive") not in {"adaptive", "triple"}:
        errors.append("verification_quorum must be adaptive or triple")
    cutoff = request.get("cutoff")
    if cutoff and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(cutoff)):
        errors.append("request.json cutoff must use YYYY-MM-DD")
    budgets = request.get("budgets", {})
    if not isinstance(budgets, dict):
        errors.append("request.json budgets must be an object")
    else:
        for key, value in budgets.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                errors.append(f"budget {key} must be a nonnegative number")
        guarded = {
            "worker_lanes": DEFAULT_LANE_ALLOCATIONS.get(depth, 0),
            "worker_interactions": DEFAULT_INTERACTION_CAPS.get(depth, 0),
            "followups": DEFAULT_FOLLOWUP_CAPS.get(depth, 0),
        }
        for key, maximum in guarded.items():
            if isinstance(budgets.get(key), (int, float)) and budgets[key] > maximum:
                errors.append(
                    f"initial budget {key} exceeds automatic {depth} allocation {maximum}; "
                    "use budget-expand after a productive wave"
                )
    return errors


def command_init(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        fail(f"refusing to overwrite nonempty run directory: {run_dir}")
    request = load_json(args.request)
    errors = validate_request(request)
    if errors:
        fail("; ".join(errors))
    run_dir.mkdir(parents=True, exist_ok=True)
    depth = request["depth"]
    budgets = {
        "worker_lanes": DEFAULT_LANE_ALLOCATIONS[depth],
        "worker_interactions": DEFAULT_INTERACTION_CAPS[depth],
        "followups": DEFAULT_FOLLOWUP_CAPS[depth],
        **request.get("budgets", {}),
    }
    request["budgets"] = budgets
    request.setdefault("verification_quorum", "adaptive")
    write_json(run_dir / "request.json", request)
    timestamp = now()
    state = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "depth": depth,
        "status": "initialized",
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_event": "run_initialized",
        "budgets": budgets,
        "usage": {},
        "guardrails": {
            "absolute_lane_ceiling": DEPTH_WORKER_CAPS[depth],
            "automatic_lane_allocation": DEFAULT_LANE_ALLOCATIONS[depth],
            "interaction_ceiling": DEFAULT_INTERACTION_CAPS[depth],
            "followup_ceiling": DEFAULT_FOLLOWUP_CAPS[depth],
            "expansions_used": 0,
            "max_expansions": 1,
        },
    }
    write_json(run_dir / "run-state.json", state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def command_checkpoint(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    state = load_json(run_dir / "run-state.json")
    usage_delta = parse_object(args.usage, "usage") if args.usage else {}
    guarded_usage = {"worker_lanes", "worker_interactions", "lane_starts", "followups"}
    manually_recorded = sorted(guarded_usage & usage_delta.keys())
    if manually_recorded:
        fail(
            "checkpoint cannot modify automatically counted usage fields: "
            + ", ".join(manually_recorded)
        )
    for key, value in usage_delta.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            fail(f"usage value {key} must be a nonnegative number")
    usage = state.setdefault("usage", {})
    if not isinstance(usage, dict):
        fail("run-state.json usage must be an object")
    for key, value in usage_delta.items():
        usage[key] = usage.get(key, 0) + value
    status = args.status or state.get("status", "running")
    if status not in ACTIVE_STATES | EXIT_STATES:
        fail(f"invalid status: {status}")
    budgets = state.get("budgets", {})
    exceeded = {
        key: {"used": usage[key], "limit": limit}
        for key, limit in budgets.items()
        if key in usage
        and isinstance(limit, (int, float))
        and isinstance(usage[key], (int, float))
        and usage[key] > limit
    }
    if exceeded:
        status = "budget_exhausted"
    timestamp = now()
    event = {
        "timestamp": timestamp,
        "run_id": state.get("run_id", run_dir.name),
        "event": args.event,
        "lane": args.lane,
        "reason": args.reason,
        "usage_delta": usage_delta,
        "cumulative_usage": usage,
        "budget_exceeded": exceeded,
        "status": status,
    }
    if args.data:
        event["data"] = parse_object(args.data, "data")
    append_event(run_dir, event)
    state.update(
        {"status": status, "updated_at": timestamp, "last_event": args.event}
    )
    write_json(run_dir / "run-state.json", state)
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


def add_lanes(run_dir: Path, lane_input: Path, initialize: bool) -> dict[str, Any]:
    request = load_json(run_dir / "request.json")
    depth = request.get("depth")
    state = load_json(run_dir / "run-state.json")
    if state.get("status") in EXIT_STATES:
        fail(f"cannot add lanes after run entered {state.get('status')}")
    manifest_path = lane_manifest_path(run_dir)
    if initialize:
        if manifest_path.exists():
            fail(f"refusing to overwrite existing lane manifest: {manifest_path}")
        manifest = {
            "schema_version": 1,
            "run_id": run_dir.name,
            "depth": depth,
            "created_at": now(),
            "updated_at": now(),
            "lanes": [],
        }
    else:
        manifest = load_json(manifest_path)
    additions = [normalize_lane(lane) for lane in load_lane_input(lane_input)]
    existing_ids = {
        lane.get("lane_id") for lane in manifest.get("lanes", []) if isinstance(lane, dict)
    }
    duplicates = sorted(
        lane.get("lane_id") for lane in additions if lane.get("lane_id") in existing_ids
    )
    if duplicates:
        fail(f"refusing duplicate lane IDs: {', '.join(duplicates)}")
    manifest.setdefault("lanes", []).extend(additions)
    lane_limit = state.get("budgets", {}).get(
        "worker_lanes", DEFAULT_LANE_ALLOCATIONS.get(depth, 0)
    )
    if len(manifest["lanes"]) > lane_limit:
        fail(
            f"lane count {len(manifest['lanes'])} exceeds current allocation {lane_limit}; "
            "finish the productive wave or use budget-expand"
        )
    manifest["updated_at"] = now()
    errors, _ = manifest_validation(manifest, run_dir, depth, check_packets=True)
    if errors:
        fail("; ".join(errors))
    write_json(manifest_path, manifest)
    append_event(
        run_dir,
        {
            "run_id": run_dir.name,
            "event": "lanes_initialized" if initialize else "lanes_added",
            "lane_count_added": len(additions),
            "lane_ids": [lane["lane_id"] for lane in additions],
        },
    )
    return manifest


def command_lanes_init(args: argparse.Namespace) -> int:
    manifest = add_lanes(args.run_directory.resolve(), args.lanes.resolve(), True)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def command_lanes_add(args: argparse.Namespace) -> int:
    manifest = add_lanes(args.run_directory.resolve(), args.lanes.resolve(), False)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def command_lanes_next(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    manifest = load_json(lane_manifest_path(run_dir))
    request = load_json(run_dir / "request.json")
    errors, _ = manifest_validation(
        manifest, run_dir, request.get("depth"), check_packets=True
    )
    if errors:
        fail("; ".join(errors))
    ready = ready_lanes(manifest)
    stages = sorted({lane["stage"] for lane in ready})
    payload = {
        "run_id": manifest.get("run_id", run_dir.name),
        "stage": stages[0] if len(stages) == 1 else None,
        "stages": stages,
        "ready_count": len(ready),
        "lanes": ready,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_lane_start(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    state_path = run_dir / "run-state.json"
    state = load_json(state_path)
    if state.get("status") in EXIT_STATES:
        fail(f"cannot start a lane after run entered {state.get('status')}")
    manifest_path = lane_manifest_path(run_dir)
    manifest = load_json(manifest_path)
    by_id = {
        lane.get("lane_id"): lane
        for lane in manifest.get("lanes", [])
        if isinstance(lane, dict)
    }
    lane = by_id.get(args.lane_id)
    if lane is None:
        fail(f"unknown lane: {args.lane_id}")
    if lane.get("status") not in {"pending", "failed"}:
        fail(f"lane {args.lane_id} cannot start from status {lane.get('status')}")
    if lane.get("attempts", 0) >= lane.get("max_attempts", 2):
        fail(f"lane {args.lane_id} exhausted its attempts")
    unresolved = [
        dependency
        for dependency in lane.get("dependencies", [])
        if by_id.get(dependency, {}).get("status") not in LANE_SUCCESS
    ]
    if unresolved:
        fail(f"lane {args.lane_id} has unresolved dependencies: {', '.join(unresolved)}")
    usage = state.setdefault("usage", {})
    budgets = state.get("budgets", {})
    next_interactions = usage.get("worker_interactions", 0) + 1
    if next_interactions > budgets.get("worker_interactions", 0):
        fail("worker interaction budget exhausted; synthesize or finish with limits")
    lane["status"] = "running"
    lane["attempts"] = lane.get("attempts", 0) + 1
    lane["started_at"] = now()
    lane["updated_at"] = now()
    lane.pop("finished_at", None)
    lane.pop("exit_reason", None)
    manifest["updated_at"] = now()
    usage["worker_interactions"] = next_interactions
    usage["lane_starts"] = usage.get("lane_starts", 0) + 1
    state["updated_at"] = now()
    state["last_event"] = "lane_started"
    write_json(manifest_path, manifest)
    write_json(state_path, state)
    append_event(
        run_dir,
        {
            "run_id": manifest.get("run_id", run_dir.name),
            "event": "lane_started",
            "lane": args.lane_id,
            "stage": lane.get("stage"),
            "attempt": lane["attempts"],
        },
    )
    print(json.dumps(lane, ensure_ascii=False, indent=2))
    return 0


def command_lane_followup(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    manifest_path = lane_manifest_path(run_dir)
    state_path = run_dir / "run-state.json"
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    if state.get("status") in EXIT_STATES:
        fail(f"cannot authorize a follow-up after run entered {state.get('status')}")
    lane = next(
        (
            lane
            for lane in manifest.get("lanes", [])
            if isinstance(lane, dict) and lane.get("lane_id") == args.lane_id
        ),
        None,
    )
    if lane is None:
        fail(f"unknown lane: {args.lane_id}")
    if lane.get("status") != "running":
        fail("follow-ups are allowed only while the original lane remains running")
    if lane.get("followups", 0) >= lane.get("max_followups", 1):
        fail(f"lane {args.lane_id} exhausted its follow-up allowance")
    usage = state.setdefault("usage", {})
    budgets = state.get("budgets", {})
    next_interactions = usage.get("worker_interactions", 0) + 1
    next_followups = usage.get("followups", 0) + 1
    if next_interactions > budgets.get("worker_interactions", 0):
        fail("worker interaction budget exhausted; do not send the follow-up")
    if next_followups > budgets.get("followups", 0):
        fail("run follow-up budget exhausted; do not send the follow-up")
    lane["followups"] = lane.get("followups", 0) + 1
    lane["updated_at"] = now()
    usage["worker_interactions"] = next_interactions
    usage["followups"] = next_followups
    state["updated_at"] = now()
    state["last_event"] = "lane_followup_authorized"
    manifest["updated_at"] = now()
    write_json(manifest_path, manifest)
    write_json(state_path, state)
    event = {
        "run_id": state.get("run_id", run_dir.name),
        "event": "lane_followup_authorized",
        "lane": args.lane_id,
        "followup": lane["followups"],
        "reason": args.reason,
        "expected_gain": args.expected_gain,
        "cumulative_usage": usage,
    }
    append_event(run_dir, event)
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


def command_budget_expand(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    state_path = run_dir / "run-state.json"
    manifest_path = lane_manifest_path(run_dir)
    state = load_json(state_path)
    manifest = load_json(manifest_path)
    if state.get("status") in EXIT_STATES:
        fail(f"cannot expand a run after it entered {state.get('status')}")
    guardrails = state.setdefault("guardrails", {})
    if guardrails.get("expansions_used", 0) >= guardrails.get("max_expansions", 1):
        fail("the run already used its one permitted lane expansion")
    if not any(
        isinstance(lane, dict) and lane.get("status") in LANE_SUCCESS
        for lane in manifest.get("lanes", [])
    ):
        fail("finish at least one productive lane before requesting expansion")
    current = state.get("budgets", {}).get("worker_lanes", 0)
    absolute = guardrails.get(
        "absolute_lane_ceiling", DEPTH_WORKER_CAPS.get(state.get("depth"), 0)
    )
    if args.new_lane_limit <= current:
        fail("new lane limit must exceed the current allocation")
    if args.new_lane_limit > absolute:
        fail(f"new lane limit exceeds absolute ceiling {absolute}")
    state.setdefault("budgets", {})["worker_lanes"] = args.new_lane_limit
    guardrails["expansions_used"] = guardrails.get("expansions_used", 0) + 1
    state["updated_at"] = now()
    state["last_event"] = "budget_expanded"
    write_json(state_path, state)
    event = {
        "run_id": state.get("run_id", run_dir.name),
        "event": "budget_expanded",
        "budget": "worker_lanes",
        "before": current,
        "after": args.new_lane_limit,
        "reason": args.reason,
        "evidence_gain": args.evidence_gain,
    }
    append_event(run_dir, event)
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


def command_lane_finish(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    manifest_path = lane_manifest_path(run_dir)
    manifest = load_json(manifest_path)
    lane = next(
        (
            lane
            for lane in manifest.get("lanes", [])
            if isinstance(lane, dict) and lane.get("lane_id") == args.lane_id
        ),
        None,
    )
    if lane is None:
        fail(f"unknown lane: {args.lane_id}")
    if lane.get("status") != "running":
        fail(f"lane {args.lane_id} cannot finish from status {lane.get('status')}")
    if args.status in LANE_SUCCESS:
        if not args.output:
            fail("completed or partial lanes require --output")
        supplied = Path(args.output)
        supplied_path = supplied.resolve() if supplied.is_absolute() else (run_dir / supplied).resolve()
        expected_path = (run_dir / lane["output_path"]).resolve()
        if supplied_path != expected_path:
            fail(f"lane {args.lane_id} output must be {lane['output_path']}")
        if not expected_path.is_file():
            fail(f"lane packet not found: {expected_path}")
        try:
            packet_text = expected_path.read_text(encoding="utf-8")
            packet = json.loads(packet_text)
        except json.JSONDecodeError as exc:
            fail(f"invalid lane packet JSON: {exc}")
        if not isinstance(packet, dict):
            fail("lane packet must be a JSON object")
        missing = PACKET_REQUIRED - packet.keys()
        if missing:
            fail(f"lane packet missing fields: {sorted(missing)}")
        if packet.get("lane_id") != args.lane_id or packet.get("stage") != lane.get("stage"):
            fail("lane packet identity does not match manifest")
        if packet.get("status") != args.status:
            fail("lane packet status does not match --status")
        for field in ("sources", "claims", "gaps"):
            if not isinstance(packet.get(field), list):
                fail(f"lane packet {field} must be an array")
        if packet.get("confidence") not in CONFIDENCE:
            fail("lane packet confidence must be high, medium, or low")
        output_cap = lane.get("budget", {}).get("output_chars")
        if isinstance(output_cap, (int, float)) and len(packet_text) > output_cap:
            fail(
                f"lane packet has {len(packet_text)} characters, exceeding output_chars cap {output_cap}"
            )
        lane["packet_sha256"] = sha256(expected_path)
    elif not args.reason:
        fail("failed or blocked lanes require --reason")
    lane["status"] = args.status
    lane["exit_reason"] = args.reason or (
        packet.get("exit_reason") if args.status in LANE_SUCCESS else None
    )
    lane["finished_at"] = now()
    lane["updated_at"] = now()
    manifest["updated_at"] = now()
    request = load_json(run_dir / "request.json")
    errors, _ = manifest_validation(
        manifest, run_dir, request.get("depth"), check_packets=True
    )
    if errors:
        fail("; ".join(errors))
    write_json(manifest_path, manifest)
    append_event(
        run_dir,
        {
            "run_id": manifest.get("run_id", run_dir.name),
            "event": "lane_finished",
            "lane": args.lane_id,
            "stage": lane.get("stage"),
            "lane_status": args.status,
            "attempt": lane.get("attempts"),
            "output_path": lane.get("output_path") if args.status in LANE_SUCCESS else None,
            "reason": args.reason,
        },
    )
    print(json.dumps(lane, ensure_ascii=False, indent=2))
    return 0


def jsonl_records(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number} invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path.name}:{line_number} must be an object")
            continue
        records.append(value)
    return records


def string_list(value: Any, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{label} must be a list of strings")
        return []
    return value


def production_block_ok(report: Path) -> bool:
    text = report.read_text(encoding="utf-8").rstrip()
    pattern = re.compile(
        r"(?:^|\n)Topic: .+\n"
        r"Date: \d{4}-\d{2}-\d{2}\n"
        r"By: Codex-.+\n"
        r"Production details: .+$"
    )
    return bool(pattern.search(text))


def validate_run(run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    request_path = run_dir / "request.json"
    state_path = run_dir / "run-state.json"
    if not request_path.is_file():
        errors.append("missing request.json")
        request: dict[str, Any] = {}
    else:
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                raise ValueError("not an object")
            errors.extend(validate_request(request))
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid request.json: {exc}")
            request = {}
    if not state_path.is_file():
        errors.append("missing run-state.json")
        state: dict[str, Any] = {}
    else:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("not an object")
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid run-state.json: {exc}")
            state = {}
    if state:
        if state.get("depth") not in DEPTHS:
            errors.append("run-state.json has invalid depth")
        if state.get("status") not in ACTIVE_STATES | EXIT_STATES:
            errors.append("run-state.json has invalid status")
        if request and state.get("depth") != request.get("depth"):
            errors.append("request and state depth values differ")
        budgets = state.get("budgets", {})
        usage = state.get("usage", {})
        if not isinstance(budgets, dict) or not isinstance(usage, dict):
            errors.append("state budgets and usage must be objects")
        else:
            for key, limit in budgets.items():
                used = usage.get(key, 0)
                if isinstance(limit, (int, float)) and isinstance(used, (int, float)):
                    if used > limit and state.get("status") != "budget_exhausted":
                        errors.append(f"budget {key} exceeded without budget_exhausted status")

    manifest_path = lane_manifest_path(run_dir)
    manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("not an object")
            manifest = value
            manifest_errors, manifest_warnings = manifest_validation(
                manifest,
                run_dir,
                request.get("depth") or state.get("depth"),
                check_packets=True,
            )
            errors.extend(manifest_errors)
            warnings.extend(manifest_warnings)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid lane-manifest.json: {exc}")
    if manifest is not None and state:
        lanes = [lane for lane in manifest.get("lanes", []) if isinstance(lane, dict)]
        lane_limit = state.get("budgets", {}).get("worker_lanes")
        if isinstance(lane_limit, (int, float)) and len(lanes) > lane_limit:
            errors.append(
                f"manifest has {len(lanes)} lanes but current allocation is {lane_limit}"
            )
        expected_interactions = sum(
            lane.get("attempts", 0) + lane.get("followups", 0) for lane in lanes
        )
        recorded_interactions = state.get("usage", {}).get("worker_interactions", 0)
        if recorded_interactions != expected_interactions:
            errors.append(
                "worker interaction accounting mismatch: "
                f"state records {recorded_interactions}, manifest records {expected_interactions}"
            )
        expected_followups = sum(lane.get("followups", 0) for lane in lanes)
        recorded_followups = state.get("usage", {}).get("followups", 0)
        if recorded_followups != expected_followups:
            errors.append(
                "follow-up accounting mismatch: "
                f"state records {recorded_followups}, manifest records {expected_followups}"
            )

    claim_records = jsonl_records(run_dir / "claim-ledger.jsonl", errors)
    source_records = jsonl_records(run_dir / "source-ledger.jsonl", errors)
    claim_ids: set[str] = set()
    source_ids: set[str] = set()
    for index, claim in enumerate(claim_records, 1):
        missing = CLAIM_REQUIRED - claim.keys()
        if missing:
            errors.append(f"claim-ledger record {index} missing {sorted(missing)}")
        claim_id = claim.get("claim_id")
        if claim_id in claim_ids:
            errors.append(f"duplicate claim_id {claim_id}")
        if isinstance(claim_id, str):
            claim_ids.add(claim_id)
        if claim.get("status") not in CLAIM_STATUSES:
            errors.append(f"claim {claim_id or index} has invalid status")
        if claim.get("confidence") not in CONFIDENCE:
            errors.append(f"claim {claim_id or index} has invalid confidence")
        string_list(
            claim.get("supporting_source_ids"),
            f"claim {claim_id or index} supporting_source_ids",
            errors,
        )
        string_list(
            claim.get("contrary_source_ids"),
            f"claim {claim_id or index} contrary_source_ids",
            errors,
        )
    for index, source in enumerate(source_records, 1):
        missing = SOURCE_REQUIRED - source.keys()
        if missing:
            errors.append(f"source-ledger record {index} missing {sorted(missing)}")
        source_id = source.get("source_id")
        if source_id in source_ids:
            errors.append(f"duplicate source_id {source_id}")
        if isinstance(source_id, str):
            source_ids.add(source_id)
        if source.get("source_role") not in SOURCE_ROLES:
            errors.append(f"source {source_id or index} has invalid source_role")
        if source.get("verification_status") not in VERIFICATION_STATUSES:
            errors.append(f"source {source_id or index} has invalid verification_status")
        string_list(
            source.get("coverage_cells"),
            f"source {source_id or index} coverage_cells",
            errors,
        )
        string_list(
            source.get("supported_claim_ids"),
            f"source {source_id or index} supported_claim_ids",
            errors,
        )
    if claim_records and source_records:
        for claim in claim_records:
            referenced = string_list(
                claim.get("supporting_source_ids"),
                f"claim {claim.get('claim_id')} supporting_source_ids",
                errors,
            ) + string_list(
                claim.get("contrary_source_ids"),
                f"claim {claim.get('claim_id')} contrary_source_ids",
                errors,
            )
            for source_id in referenced:
                if source_id not in source_ids:
                    errors.append(f"claim {claim.get('claim_id')} references unknown source {source_id}")
        for source in source_records:
            for claim_id in string_list(
                source.get("supported_claim_ids"),
                f"source {source.get('source_id')} supported_claim_ids",
                errors,
            ):
                if claim_id not in claim_ids:
                    errors.append(f"source {source.get('source_id')} references unknown claim {claim_id}")

    status = state.get("status")
    depth = request.get("depth") or state.get("depth")
    if status in {"complete", "complete_with_limits"}:
        required = {"report.md", "source-ledger.jsonl"}
        if depth in {"standard", "deep"}:
            required |= {
                "plan.md",
                "claim-ledger.jsonl",
                "evidence-table.md",
                "cost-report.json",
            }
        if status == "complete_with_limits":
            required.add("unresolved.md")
        for name in sorted(required):
            path = run_dir / name
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"completed run missing nonempty {name}")
        report = run_dir / "report.md"
        if report.is_file() and not production_block_ok(report):
            errors.append("report.md does not end with the required production block")
        if depth in {"standard", "deep"} and manifest is None:
            errors.append(f"completed {depth} run missing lane-manifest.json")
        if manifest is not None:
            lanes = [lane for lane in manifest.get("lanes", []) if isinstance(lane, dict)]
            nonterminal = [
                lane.get("lane_id") for lane in lanes if lane.get("status") not in LANE_TERMINAL
            ]
            if nonterminal:
                errors.append(f"completed run has nonterminal lanes: {nonterminal}")
            if status == "complete":
                unfinished_required = [
                    lane.get("lane_id")
                    for lane in lanes
                    if lane.get("required") and lane.get("status") != "completed"
                ]
                if unfinished_required:
                    errors.append(
                        f"complete run has required lanes not completed: {unfinished_required}"
                    )
            if depth in {"standard", "deep"}:
                discovery_lanes = [
                    lane for lane in lanes if lane.get("stage") == "discovery"
                ]
                read_lanes = [lane for lane in lanes if lane.get("stage") == "read"]
                verification_lanes = [
                    lane for lane in lanes if lane.get("stage") == "verification"
                ]
                mechanical_lanes = [
                    lane for lane in lanes if lane.get("stage") == "mechanical_audit"
                ]
                if not discovery_lanes:
                    errors.append("completed standard/deep run has no discovery lane")
                if not read_lanes:
                    errors.append("completed standard/deep run has no read lane")
                if not verification_lanes:
                    errors.append("completed standard/deep run has no verification lane")
                if not mechanical_lanes:
                    errors.append("completed standard/deep run has no mechanical_audit lane")
                material_claim_ids = {
                    claim.get("claim_id")
                    for claim in claim_records
                    if isinstance(claim.get("claim_id"), str)
                    and not any(
                        marker in str(claim.get("importance", "")).casefold()
                        for marker in ("low", "contextual")
                    )
                }
                verified_claim_ids = {
                    claim_id
                    for lane in verification_lanes
                    if lane.get("status") in LANE_SUCCESS
                    for claim_id in lane.get("claim_ids", [])
                }
                missing_verification = sorted(material_claim_ids - verified_claim_ids)
                if missing_verification:
                    message = (
                        "material claims lack registered verification lanes: "
                        f"{missing_verification}"
                    )
                    if status == "complete":
                        errors.append(message)
                    else:
                        warnings.append(message)
                if depth == "deep":
                    high_claim_ids = {
                        claim.get("claim_id")
                        for claim in claim_records
                        if isinstance(claim.get("claim_id"), str)
                        and any(
                            marker in str(claim.get("importance", "")).casefold()
                            for marker in ("high", "dispositive")
                        )
                    }
                    vote_groups: dict[str, list[dict[str, Any]]] = {}
                    for lane in verification_lanes:
                        group = lane.get("vote_group")
                        if isinstance(group, str):
                            vote_groups.setdefault(group, []).append(lane)
                    quorum_policy = request.get("verification_quorum", "adaptive")
                    allowed_sizes = {3} if quorum_policy == "triple" else {2, 3}
                    malformed_groups = sorted(
                        group
                        for group, group_lanes in vote_groups.items()
                        if len(group_lanes) not in allowed_sizes
                    )
                    if malformed_groups:
                        errors.append(
                            "deep vote groups have invalid quorum size "
                            f"for {quorum_policy} policy: {malformed_groups}"
                        )
                    target = min(8, len(high_claim_ids))
                    minimum = min(5, target)
                    completed_groups = {
                        group
                        for group, group_lanes in vote_groups.items()
                        if group in high_claim_ids
                        and len(group_lanes) in allowed_sizes
                        and all(lane.get("status") in LANE_SUCCESS for lane in group_lanes)
                    }
                    if len(completed_groups) < minimum:
                        message = (
                            f"deep run has {len(completed_groups)} completed quorum groups; "
                            f"requires {minimum} for {len(high_claim_ids)} high-importance claims"
                        )
                        if status == "complete":
                            errors.append(message)
                        else:
                            warnings.append(message)
                    contested: dict[str, list[str]] = {}
                    for group in completed_groups:
                        verdicts: list[str] = []
                        for lane in vote_groups[group]:
                            packet_path = run_dir / lane["output_path"]
                            try:
                                packet = json.loads(packet_path.read_text(encoding="utf-8"))
                            except (OSError, json.JSONDecodeError):
                                continue
                            for result in packet.get("claims", []):
                                if (
                                    isinstance(result, dict)
                                    and result.get("claim_id") == group
                                    and result.get("verdict") in VOTE_VERDICTS
                                ):
                                    verdicts.append(result["verdict"])
                        if (
                            quorum_policy == "adaptive"
                            and len(vote_groups[group]) == 2
                            and sorted(verdicts)
                            not in (["supported", "supported"], ["adverse", "adverse"])
                        ):
                            errors.append(
                                f"adaptive vote group {group} requires a third voter after "
                                f"non-unanimous or uncertain first votes: {verdicts}"
                            )
                        if (
                            verdicts.count("adverse") >= 2
                            or "uncertain" in verdicts
                            or len(set(verdicts)) > 1
                        ):
                            contested[group] = verdicts
                    if contested:
                        resolution_path = run_dir / "verification-resolution.json"
                        resolutions: dict[str, dict[str, Any]] = {}
                        if not resolution_path.is_file():
                            errors.append(
                                "contested deep vote groups require verification-resolution.json"
                            )
                        else:
                            try:
                                resolution_payload = json.loads(
                                    resolution_path.read_text(encoding="utf-8")
                                )
                                if not isinstance(resolution_payload, dict):
                                    raise ValueError("top-level value must be an object")
                                entries = resolution_payload.get("resolutions", [])
                                if not isinstance(entries, list):
                                    raise ValueError("resolutions must be an array")
                                for entry in entries:
                                    if isinstance(entry, dict) and isinstance(
                                        entry.get("claim_id"), str
                                    ):
                                        resolutions[entry["claim_id"]] = entry
                            except (json.JSONDecodeError, ValueError) as exc:
                                errors.append(f"invalid verification-resolution.json: {exc}")
                        for group in sorted(contested):
                            resolution = resolutions.get(group)
                            if resolution is None:
                                errors.append(f"contested vote group {group} lacks lead resolution")
                                continue
                            if resolution.get("disposition") not in RESOLUTION_DISPOSITIONS:
                                errors.append(
                                    f"resolution for {group} has invalid disposition"
                                )
                            if not isinstance(resolution.get("basis"), str) or not resolution.get(
                                "basis", ""
                            ).strip():
                                errors.append(f"resolution for {group} lacks a basis")
                            if not isinstance(resolution.get("source_ids"), list) or any(
                                not isinstance(item, str)
                                for item in resolution.get("source_ids", [])
                            ):
                                errors.append(
                                    f"resolution for {group} source_ids must be strings"
                                )
    if ".codex-memo" not in run_dir.parts or "runs" not in run_dir.parts:
        warnings.append("run directory is not under a hidden .codex-memo/runs path")
    lane_counts: dict[str, int] = {}
    ready_count = 0
    if manifest is not None:
        for lane in manifest.get("lanes", []):
            if isinstance(lane, dict):
                lane_counts[lane.get("status", "invalid")] = (
                    lane_counts.get(lane.get("status", "invalid"), 0) + 1
                )
        ready_count = len(ready_lanes(manifest))
    return {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "checked_at": now(),
        "run_directory": str(run_dir),
        "run_status": status,
        "claim_records": len(claim_records),
        "source_records": len(source_records),
        "lane_counts": lane_counts,
        "ready_lanes": ready_count,
        "errors": errors,
        "warnings": warnings,
    }


def command_resume(args: argparse.Namespace) -> int:
    run_dir = args.run_directory.resolve()
    state = load_json(run_dir / "run-state.json")
    artifacts = sorted(
        str(path.relative_to(run_dir)) for path in run_dir.rglob("*") if path.is_file()
    )
    errors: list[str] = []
    manifest = load_json(lane_manifest_path(run_dir)) if lane_manifest_path(run_dir).is_file() else None
    summary = {
        "run_directory": str(run_dir),
        "state": state,
        "artifacts": artifacts,
        "claim_records": len(jsonl_records(run_dir / "claim-ledger.jsonl", errors)),
        "source_records": len(jsonl_records(run_dir / "source-ledger.jsonl", errors)),
        "lane_counts": {
            status: sum(
                1
                for lane in (manifest or {}).get("lanes", [])
                if isinstance(lane, dict) and lane.get("status") == status
            )
            for status in sorted(LANE_STATUSES)
        }
        if manifest
        else {},
        "ready_lanes": ready_lanes(manifest) if manifest else [],
        "ledger_errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def command_validate(args: argparse.Namespace) -> int:
    result = validate_run(args.run_directory.resolve())
    if args.output:
        write_json(args.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="create a new run state")
    initialize.add_argument("run_directory", type=Path)
    initialize.add_argument("--request", type=Path, required=True)
    initialize.set_defaults(func=command_init)

    lanes_init = commands.add_parser("lanes-init", help="create the lane manifest")
    lanes_init.add_argument("run_directory", type=Path)
    lanes_init.add_argument("--lanes", type=Path, required=True)
    lanes_init.set_defaults(func=command_lanes_init)

    lanes_add = commands.add_parser("lanes-add", help="append lead-authorized lanes")
    lanes_add.add_argument("run_directory", type=Path)
    lanes_add.add_argument("--lanes", type=Path, required=True)
    lanes_add.set_defaults(func=command_lanes_add)

    lanes_next = commands.add_parser("lanes-next", help="show the earliest ready lane wave")
    lanes_next.add_argument("run_directory", type=Path)
    lanes_next.set_defaults(func=command_lanes_next)

    lane_start = commands.add_parser("lane-start", help="start one lane attempt")
    lane_start.add_argument("run_directory", type=Path)
    lane_start.add_argument("lane_id")
    lane_start.set_defaults(func=command_lane_start)

    lane_finish = commands.add_parser("lane-finish", help="register a terminal lane result")
    lane_finish.add_argument("run_directory", type=Path)
    lane_finish.add_argument("lane_id")
    lane_finish.add_argument(
        "--status", choices=sorted(LANE_TERMINAL), required=True
    )
    lane_finish.add_argument("--output")
    lane_finish.add_argument("--reason")
    lane_finish.set_defaults(func=command_lane_finish)

    lane_followup = commands.add_parser(
        "lane-followup", help="authorize and count one bounded worker follow-up"
    )
    lane_followup.add_argument("run_directory", type=Path)
    lane_followup.add_argument("lane_id")
    lane_followup.add_argument("--reason", required=True)
    lane_followup.add_argument("--expected-gain", required=True)
    lane_followup.set_defaults(func=command_lane_followup)

    budget_expand = commands.add_parser(
        "budget-expand", help="unlock the one bounded lane-allocation expansion"
    )
    budget_expand.add_argument("run_directory", type=Path)
    budget_expand.add_argument("--new-lane-limit", type=int, required=True)
    budget_expand.add_argument("--reason", required=True)
    budget_expand.add_argument("--evidence-gain", required=True)
    budget_expand.set_defaults(func=command_budget_expand)

    checkpoint = commands.add_parser("checkpoint", help="append an event and usage")
    checkpoint.add_argument("run_directory", type=Path)
    checkpoint.add_argument("--event", required=True)
    checkpoint.add_argument("--lane")
    checkpoint.add_argument("--reason")
    checkpoint.add_argument("--usage", help="JSON object of measured usage increments")
    checkpoint.add_argument("--data", help="JSON object with event-specific fields")
    checkpoint.add_argument("--status", choices=sorted(ACTIVE_STATES | EXIT_STATES))
    checkpoint.set_defaults(func=command_checkpoint)

    resume = commands.add_parser("resume", help="print resumable run state")
    resume.add_argument("run_directory", type=Path)
    resume.set_defaults(func=command_resume)

    validate = commands.add_parser("validate", help="validate a run artifact bundle")
    validate.add_argument("run_directory", type=Path)
    validate.add_argument("--output", type=Path)
    validate.set_defaults(func=command_validate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
