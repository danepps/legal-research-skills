#!/usr/bin/env python3
"""Validate autonomous legal research run state and completion readiness."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quantifier_audit import extract_deliverable_text, find_quantifier_hits

VALID_PHASES = {"frame", "research", "verify", "synthesize", "draft", "audit", "deliver"}
VALID_STATUSES = {
    "active",
    "complete",
    "complete_with_limits",
    "needs_input",
    "source_unavailable",
    "budget_exhausted",
    "failed",
}
VALID_IMPORTANCE = {"dispositive", "material", "supporting", "contextual"}
VALID_CLAIM_STATUS = {"open", "supported", "disputed", "unresolved"}
VALID_CLAIM_TYPE = {
    "holding_rule",
    "doctrinal_synthesis",
    "factual_historical_inference",
    "cross_doctrinal_analogy",
    "normative_proposal",
}
VALID_CLAIM_STRENGTH = {
    "existence",
    "illustrative",
    "comparative",
    "frequency",
    "priority",
    "universal",
}
PROTOCOL_CLAIM_STRENGTH = {"frequency", "priority", "universal"}
V3_VALID_SOURCE_ROLE = {
    "direct_rule",
    "assumed_baseline",
    "procedure_or_remedy_only",
    "boundary_or_transition",
    "contrary_example",
    "adjacent_doctrine_analogy",
    "historical_background",
    "later_interpretation",
    "scholarly_analysis",
    "factual_record",
}
V4_VALID_SOURCE_ROLE = {
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
VALID_CLASSIFICATION_STATUS = {
    "decided",
    "assumed",
    "arguendo",
    "dictum",
    "reserved",
    "not_applicable",
}
VALID_PRECEDENTIAL_EFFECT = {
    "majority_holding",
    "plurality",
    "concurrence_or_dissent",
    "summary_disposition",
    "equally_divided_or_nonprecedential",
    "binding_noncase_text",
    "persuasive_or_historical",
    "not_applicable",
}
VALID_VERIFICATION = {
    "direct",
    "partial",
    "lead_only",
    "direct-full-text",
    "authoritative-reproduction",
    "secondary-corroboration",
    "citation-only",
    "unverified",
}
DIRECT_VERIFICATION = {"direct", "direct-full-text", "authoritative-reproduction"}
REQUIRED_GATES = {
    "controlling_law",
    "currentness",
    "adverse_authority",
    "material_claim_support",
    "citation_audit",
    "limitations_disclosed",
}
V3_REQUIRED_GATES = {"planned_coverage"}
V4_REQUIRED_GATES = {"quantifier_audit"}
V5_REQUIRED_GATES = {"direct_source_audit"}
V6_REQUIRED_GATES = {"draft_claim_map"}
NON_WAIVABLE_GATES = {"quantifier_audit"}
VALID_ANALYSIS_ROLES = {
    "conclusion",
    "rule_or_synthesis",
    "application_or_inference",
    "counterauthority",
    "limitation",
}


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing file: {path}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected JSON object: {path}")
        return {}
    return value


def load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        errors.append(f"missing file: {path}")
        return rows
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSONL at {path}:{number}: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"expected object at {path}:{number}")
            continue
        rows.append(row)
    return rows


def unique_index(rows: list[dict[str, Any]], label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for number, row in enumerate(rows, 1):
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            errors.append(f"{label} row {number} lacks a nonempty id")
            continue
        if identifier in index:
            errors.append(f"duplicate {label} id: {identifier}")
            continue
        index[identifier] = row
    return index


def string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    return value


def artifact_path(run_dir: Path, value: Any, default: str, errors: list[str]) -> Path:
    candidate = (run_dir / str(value or default)).resolve()
    if candidate != run_dir and run_dir not in candidate.parents:
        errors.append(f"artifact path escapes run directory: {candidate}")
        return run_dir / default
    return candidate


def referenced_path(run_dir: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = run_dir / candidate
    return candidate.resolve()


def validate_quantifier_audit(
    run_dir: Path,
    artifacts: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    errors: list[str],
) -> int:
    deliverable = referenced_path(run_dir, artifacts.get("memo"))
    if deliverable is None:
        errors.append("schema v4 quantifier audit requires a memo artifact")
        return 0
    if not deliverable.is_file():
        errors.append(f"quantifier-audit deliverable does not exist: {deliverable}")
        return 0
    audit_path = artifact_path(
        run_dir,
        artifacts.get("quantifier_audit"),
        "quantifier-audit.jsonl",
        errors,
    )
    rows = load_jsonl(audit_path, errors)
    try:
        hits = find_quantifier_hits(extract_deliverable_text(deliverable))
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"cannot scan deliverable for quantifiers: {exc}")
        return 0

    audit_rows: dict[str, dict[str, Any]] = {}
    for number, row in enumerate(rows, 1):
        hit_id = row.get("hit_id")
        if not isinstance(hit_id, str) or not hit_id.strip():
            errors.append(f"quantifier-audit row {number} lacks hit_id")
            continue
        if hit_id in audit_rows:
            errors.append(f"duplicate quantifier-audit hit_id: {hit_id}")
            continue
        audit_rows[hit_id] = row

    detected_ids = {str(hit["hit_id"]) for hit in hits}
    for hit in hits:
        hit_id = str(hit["hit_id"])
        row = audit_rows.get(hit_id)
        if row is None:
            errors.append(
                f"quantifier hit {hit_id} ({hit['term']!r} at line {hit['line']}) lacks an audit row"
            )
            continue
        for field in ("term", "line", "excerpt"):
            if row.get(field) != hit[field]:
                errors.append(f"quantifier-audit {hit_id} has stale or incorrect {field}")
        claim_id = row.get("claim_id")
        waiver = row.get("waiver")
        has_claim = isinstance(claim_id, str) and bool(claim_id.strip())
        has_waiver = isinstance(waiver, str) and bool(waiver.strip())
        if has_claim == has_waiver:
            errors.append(
                f"quantifier-audit {hit_id} requires exactly one of claim_id or waiver"
            )
            continue
        if has_claim:
            claim = claims.get(claim_id)
            if claim is None:
                errors.append(f"quantifier-audit {hit_id} refers to unknown claim: {claim_id}")
                continue
            if claim.get("claim_strength") not in PROTOCOL_CLAIM_STRENGTH:
                errors.append(
                    f"quantifier-audit {hit_id} maps to claim {claim_id} without frequency/priority/universal strength"
                )
            if not isinstance(claim.get("coverage_protocol"), str) or not claim["coverage_protocol"].strip():
                errors.append(
                    f"quantifier-audit {hit_id} maps to claim {claim_id} without coverage_protocol"
                )

    for extra_id in sorted(set(audit_rows) - detected_ids):
        errors.append(f"quantifier-audit contains stale hit not present in deliverable: {extra_id}")
    return len(hits)


def parse_timestamp(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} lacks a timestamp")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} has invalid timestamp: {value!r}")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} timestamp lacks timezone: {value!r}")
        return None
    return parsed.astimezone(timezone.utc)


def evidence_pointer_valid(
    pointer: str,
    claims: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    artifacts: dict[str, Any],
    run_dir: Path,
) -> bool:
    kind, separator, identifier = pointer.partition(":")
    if not separator or not identifier:
        return False
    if kind == "source":
        return identifier in sources
    if kind == "claim":
        return identifier in claims
    if kind == "event":
        return any(row.get("event") == identifier or row.get("phase") == identifier for row in events)
    if kind == "artifact" and identifier in artifacts:
        path = Path(str(artifacts[identifier])).expanduser()
        if not path.is_absolute():
            path = run_dir / path
        return path.resolve().exists()
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    manifest = load_json(run_dir / "manifest.json", errors)
    schema_version = manifest.get("schema_version", 1)
    if not isinstance(schema_version, int) or schema_version < 1:
        errors.append(f"invalid schema_version: {schema_version!r}")
        schema_version = 1
    required_gates = (
        REQUIRED_GATES
        | (V3_REQUIRED_GATES if schema_version >= 3 else set())
        | (V4_REQUIRED_GATES if schema_version >= 4 else set())
        | (V5_REQUIRED_GATES if schema_version >= 5 else set())
    )
    strict_coverage = schema_version >= 3 and manifest.get("effort") in {"standard", "deep"}
    claim_map_required = schema_version >= 6 and manifest.get("effort") in {"standard", "deep"}
    if claim_map_required:
        required_gates |= V6_REQUIRED_GATES
    direct_source_required = (
        schema_version >= 5
        and manifest.get("mode") in {"scholarly", "hybrid"}
        and manifest.get("effort") in {"standard", "deep"}
    )
    non_waivable_gates = set(NON_WAIVABLE_GATES)
    if direct_source_required:
        non_waivable_gates.add("direct_source_audit")
    if claim_map_required:
        non_waivable_gates.add("draft_claim_map")

    for field in ("schema_version", "question", "mode", "effort", "cutoff", "status", "phase", "next_action"):
        if field not in manifest:
            errors.append(f"manifest missing field: {field}")
    if manifest.get("phase") not in VALID_PHASES:
        errors.append(f"invalid phase: {manifest.get('phase')!r}")
    if manifest.get("status") not in VALID_STATUSES:
        errors.append(f"invalid status: {manifest.get('status')!r}")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("manifest artifacts must be an object")
        artifacts = {}
    claim_path = artifact_path(run_dir, artifacts.get("claim_ledger"), "claim-ledger.jsonl", errors)
    source_path = artifact_path(run_dir, artifacts.get("source_ledger"), "source-ledger.jsonl", errors)
    event_path = artifact_path(run_dir, artifacts.get("events"), "events.jsonl", errors)
    claims = unique_index(load_jsonl(claim_path, errors), "claim", errors)
    sources = unique_index(load_jsonl(source_path, errors), "source", errors)
    events = load_jsonl(event_path, errors)
    memo_text = ""
    memo_headings: set[str] = set()
    if claim_map_required:
        memo_path = referenced_path(run_dir, artifacts.get("memo"))
        if memo_path is None:
            errors.append("schema v6 standard/deep claim map requires a memo artifact")
        elif not memo_path.is_file():
            errors.append(f"claim-map memo does not exist: {memo_path}")
        else:
            try:
                memo_text = extract_deliverable_text(memo_path)
            except (OSError, ValueError, KeyError) as exc:
                errors.append(f"cannot read memo for claim-map validation: {exc}")
            if memo_path.suffix.lower() in {".md", ".markdown"}:
                memo_headings = {
                    match.group(1).strip()
                    for line in memo_text.splitlines()
                    if (match := re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line))
                }

    if schema_version >= 2:
        if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"].strip():
            errors.append("schema v2 manifest lacks run_id")
        provenance = manifest.get("provenance")
        if not isinstance(provenance, dict):
            errors.append("schema v2 manifest provenance must be an object")
        else:
            for field in ("producer", "skill", "skill_sha256"):
                if not isinstance(provenance.get(field), str) or not provenance[field].strip():
                    errors.append(f"schema v2 provenance lacks {field}")
        usage = manifest.get("usage")
        if not isinstance(usage, dict) or usage.get("availability") not in {
            "unavailable",
            "actual",
            "estimated",
            "mixed",
        }:
            errors.append("schema v2 usage has invalid structure or availability")

    planned_coverage = string_list(manifest.get("coverage_cells", []))
    if schema_version >= 3:
        if planned_coverage is None:
            errors.append("schema v3 coverage_cells must be a list of strings")
            planned_coverage = []
        elif any(not cell.strip() for cell in planned_coverage):
            errors.append("schema v3 coverage_cells contains an empty ID")
        elif len(set(planned_coverage)) != len(planned_coverage):
            errors.append("schema v3 coverage_cells contains duplicate IDs")
        if strict_coverage and not planned_coverage:
            errors.append("schema v3 standard/deep run lacks planned coverage cells")
    else:
        planned_coverage = []

    previous: datetime | None = None
    event_limit = datetime.fromtimestamp(event_path.stat().st_mtime, timezone.utc) + timedelta(minutes=5)
    now_limit = datetime.now(timezone.utc) + timedelta(minutes=5)
    for number, event in enumerate(events, 1):
        parsed = parse_timestamp(event.get("timestamp"), f"event row {number}", errors)
        if parsed is None:
            continue
        if previous is not None and parsed < previous:
            errors.append(f"event timestamps are not monotonic at row {number}")
        if schema_version >= 2 and parsed > event_limit:
            errors.append(f"event row {number} is later than the event-file mtime plus allowed skew")
        if parsed > now_limit:
            errors.append(f"event row {number} is implausibly in the future")
        previous = parsed
    created = parse_timestamp(manifest.get("created_at"), "manifest created_at", errors)
    updated = parse_timestamp(manifest.get("updated_at"), "manifest updated_at", errors)
    if created and updated and updated < created:
        errors.append("manifest updated_at precedes created_at")
    if updated and previous and updated < previous:
        errors.append("manifest updated_at precedes the latest event")
    if schema_version >= 2 and updated and updated > now_limit:
        errors.append("manifest updated_at is implausibly in the future")

    for source_id, source in sources.items():
        for field in ("citation", "location", "authority_level", "verification"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f"source {source_id} lacks {field}")
        if source.get("verification") not in VALID_VERIFICATION:
            errors.append(f"source {source_id} has invalid verification status")
        claim_ids = string_list(source.get("claim_ids", []))
        if claim_ids is None:
            errors.append(f"source {source_id} claim_ids must be a list of strings")
        elif any(claim_id not in claims for claim_id in claim_ids):
            missing = sorted(claim_id for claim_id in claim_ids if claim_id not in claims)
            errors.append(f"source {source_id} refers to unknown claims: {', '.join(missing)}")
        if source.get("verification") in DIRECT_VERIFICATION and not str(source.get("pinpoint", "")).strip():
            errors.append(f"directly verified source {source_id} lacks a pinpoint")
        if schema_version >= 3:
            valid_source_roles = (
                V4_VALID_SOURCE_ROLE if schema_version >= 4 else V3_VALID_SOURCE_ROLE
            )
            if source.get("source_role") not in valid_source_roles:
                errors.append(f"source {source_id} has invalid or missing source_role")
            if source.get("classification_status") not in VALID_CLASSIFICATION_STATUS:
                errors.append(f"source {source_id} has invalid or missing classification_status")
            if source.get("precedential_effect") not in VALID_PRECEDENTIAL_EFFECT:
                errors.append(f"source {source_id} has invalid or missing precedential_effect")
            if not isinstance(source.get("distinct_contribution"), str) or not source["distinct_contribution"].strip():
                errors.append(f"source {source_id} lacks distinct_contribution")
            source_cells = string_list(source.get("coverage_cells", []))
            if source_cells is None:
                errors.append(f"source {source_id} coverage_cells must be a list of strings")
            else:
                unknown_cells = sorted(set(source_cells) - set(planned_coverage))
                if unknown_cells:
                    errors.append(
                        f"source {source_id} refers to unknown coverage cells: {', '.join(unknown_cells)}"
                    )
                if strict_coverage and source.get("verification") in DIRECT_VERIFICATION and not source_cells:
                    errors.append(f"directly verified source {source_id} lacks coverage_cells")

    for claim_id, claim in claims.items():
        if not isinstance(claim.get("proposition"), str) or not claim["proposition"].strip():
            errors.append(f"claim {claim_id} lacks proposition")
        if claim.get("importance") not in VALID_IMPORTANCE:
            errors.append(f"claim {claim_id} has invalid importance")
        if claim.get("status") not in VALID_CLAIM_STATUS:
            errors.append(f"claim {claim_id} has invalid status")
        if schema_version >= 2 and claim.get("claim_type") not in VALID_CLAIM_TYPE:
            errors.append(f"claim {claim_id} has invalid or missing claim_type")
        if schema_version >= 3:
            strength = claim.get("claim_strength")
            if strength not in VALID_CLAIM_STRENGTH:
                errors.append(f"claim {claim_id} has invalid or missing claim_strength")
            if strength in PROTOCOL_CLAIM_STRENGTH and (
                not isinstance(claim.get("coverage_protocol"), str)
                or not claim["coverage_protocol"].strip()
            ):
                errors.append(f"claim {claim_id} with strength {strength} lacks coverage_protocol")
            claim_cells = string_list(claim.get("coverage_cells", []))
            if claim_cells is None:
                errors.append(f"claim {claim_id} coverage_cells must be a list of strings")
            else:
                unknown_cells = sorted(set(claim_cells) - set(planned_coverage))
                if unknown_cells:
                    errors.append(
                        f"claim {claim_id} refers to unknown coverage cells: {', '.join(unknown_cells)}"
                    )
                if strict_coverage and claim.get("importance") in {"dispositive", "material"} and not claim_cells:
                    errors.append(f"material claim {claim_id} lacks coverage_cells")
        support = string_list(claim.get("supporting_source_ids", []))
        adverse = string_list(claim.get("adverse_source_ids", []))
        if support is None or adverse is None:
            errors.append(f"claim {claim_id} source-id fields must be lists of strings")
            continue
        missing = sorted(source_id for source_id in support + adverse if source_id not in sources)
        if missing:
            errors.append(f"claim {claim_id} refers to unknown sources: {', '.join(missing)}")
        if claim.get("status") == "supported" and not support:
            errors.append(f"supported claim {claim_id} has no supporting source")
        if claim.get("importance") in {"dispositive", "material"} and claim.get("status") == "supported":
            direct = [
                source_id
                for source_id in support
                if source_id in sources and sources[source_id].get("verification") in DIRECT_VERIFICATION
            ]
            if not direct:
                errors.append(f"material claim {claim_id} lacks directly verified support")
        if claim_map_required:
            included = claim.get("included_in_memo")
            if not isinstance(included, bool):
                errors.append(f"claim {claim_id} lacks boolean included_in_memo")
            if claim.get("importance") == "dispositive" and included is not True:
                errors.append(f"dispositive claim {claim_id} is not mapped into the memo")
            if included is True and claim.get("importance") in {"dispositive", "material"}:
                roles = string_list(claim.get("analysis_roles"))
                if not roles:
                    errors.append(f"included material claim {claim_id} lacks analysis_roles")
                else:
                    invalid_roles = sorted(set(roles) - VALID_ANALYSIS_ROLES)
                    if invalid_roles:
                        errors.append(
                            f"claim {claim_id} has invalid analysis_roles: {', '.join(invalid_roles)}"
                        )
                memo_section = claim.get("memo_section")
                if not isinstance(memo_section, str) or not memo_section.strip():
                    errors.append(f"included material claim {claim_id} lacks memo_section")
                elif memo_headings and memo_section.strip() not in memo_headings:
                    errors.append(
                        f"claim {claim_id} memo_section is not a Markdown heading in the memo"
                    )
                anchor = claim.get("draft_anchor")
                if not isinstance(anchor, str) or not anchor.strip():
                    errors.append(f"included material claim {claim_id} lacks draft_anchor")
                elif memo_text.count(anchor.strip()) != 1:
                    errors.append(
                        f"claim {claim_id} draft_anchor must occur exactly once in the memo"
                    )

    if claim_map_required and claims and not any(
        claim.get("importance") == "dispositive"
        and claim.get("included_in_memo") is True
        for claim in claims.values()
    ):
        errors.append("schema v6 standard/deep run lacks an included dispositive claim")

    if strict_coverage:
        for cell in planned_coverage:
            cell_claims = {
                claim_id
                for claim_id, claim in claims.items()
                if claim.get("importance") in {"dispositive", "material"}
                and cell in (string_list(claim.get("coverage_cells", [])) or [])
            }
            if not cell_claims:
                errors.append(f"coverage cell {cell} lacks a material claim")
                continue
            cell_sources = [
                source_id
                for source_id, source in sources.items()
                if source.get("verification") in DIRECT_VERIFICATION
                and cell in (string_list(source.get("coverage_cells", [])) or [])
                and bool(cell_claims & set(string_list(source.get("claim_ids", [])) or []))
            ]
            if not cell_sources:
                errors.append(f"coverage cell {cell} lacks directly verified source support")

    quantifier_hit_count = 0
    quantifier_audit_errors: list[str] = []
    if schema_version >= 4:
        quantifier_hit_count = validate_quantifier_audit(
            run_dir, artifacts, claims, quantifier_audit_errors
        )

    gates = manifest.get("completion_gates")
    if not isinstance(gates, dict):
        errors.append("manifest completion_gates must be an object")
        gates = {}
    missing_gates = sorted(required_gates - set(gates))
    if missing_gates:
        errors.append(f"manifest missing completion gates: {', '.join(missing_gates)}")
    gate_statuses: dict[str, str] = {}
    for gate in required_gates & set(gates):
        value = gates[gate]
        if not isinstance(value, dict) or value.get("status") not in {"pending", "pass", "not_applicable", "blocked"}:
            errors.append(f"completion gate {gate} has invalid structure or status")
        else:
            gate_statuses[gate] = value["status"]
            if gate in non_waivable_gates and value["status"] == "not_applicable":
                errors.append(f"completion gate {gate} may not be not_applicable")
            if value["status"] in {"pass", "blocked"} and not str(value.get("note", "")).strip():
                errors.append(f"completion gate {gate} requires a note when {value['status']}")
            if schema_version >= 2 and value["status"] == "pass":
                evidence = string_list(value.get("evidence"))
                if not evidence:
                    errors.append(f"completion gate {gate} requires evidence pointers")
                else:
                    invalid = [
                        pointer
                        for pointer in evidence
                        if not evidence_pointer_valid(
                            pointer, claims, sources, events, artifacts, run_dir
                        )
                    ]
                    if invalid:
                        errors.append(
                            f"completion gate {gate} has invalid evidence: {', '.join(invalid)}"
                        )

    if schema_version >= 5 and gate_statuses.get("direct_source_audit") == "pass":
        gate_evidence = string_list(gates["direct_source_audit"].get("evidence")) or []
        if "event:direct_source_search" not in gate_evidence:
            errors.append(
                "completion gate direct_source_audit requires event:direct_source_search evidence"
            )
        directly_verified = {
            source_id
            for source_id, source in sources.items()
            if source.get("source_role") == "direct_answer"
            and source.get("verification") in DIRECT_VERIFICATION
        }
        if directly_verified and not any(
            pointer == f"source:{source_id}"
            for source_id in directly_verified
            for pointer in gate_evidence
        ):
            errors.append(
                "completion gate direct_source_audit must cite a directly verified direct_answer source"
            )
    if claim_map_required and gate_statuses.get("draft_claim_map") == "pass":
        gate_evidence = string_list(gates["draft_claim_map"].get("evidence")) or []
        if "artifact:memo" not in gate_evidence:
            errors.append("completion gate draft_claim_map requires artifact:memo evidence")

    enforce_quantifier_audit = (
        args.require_ready
        or manifest.get("status") in {"complete", "complete_with_limits"}
        or gate_statuses.get("quantifier_audit") == "pass"
    )
    if enforce_quantifier_audit:
        errors.extend(quantifier_audit_errors)
    else:
        warnings.extend(f"quantifier audit pending: {error}" for error in quantifier_audit_errors)

    material_open = sorted(
        claim_id
        for claim_id, claim in claims.items()
        if claim.get("importance") in {"dispositive", "material"}
        and claim.get("status") in {"open", "unresolved"}
    )
    ready = (
        bool(claims)
        and not errors
        and not material_open
        and all(
            gate_statuses.get(gate) == "pass"
            if gate in non_waivable_gates
            else gate_statuses.get(gate) in {"pass", "not_applicable"}
            for gate in required_gates
        )
    )

    if material_open:
        warnings.append(f"unresolved material claims: {', '.join(material_open)}")
    pending_gates = sorted(
        gate
        for gate, status in gate_statuses.items()
        if status not in {"pass", "not_applicable"}
        or (gate in non_waivable_gates and status != "pass")
    )
    if pending_gates:
        warnings.append(f"completion gates not passed: {', '.join(pending_gates)}")
    if not claims:
        warnings.append("claim ledger is empty")

    status = manifest.get("status")
    if status == "complete":
        if not ready:
            errors.append("manifest is marked complete but readiness checks do not pass")
        if manifest.get("phase") != "deliver" or "audit" not in manifest.get("completed_phases", []):
            errors.append("complete status requires phase=deliver and a completed audit phase")
    if status == "complete_with_limits":
        if manifest.get("phase") != "deliver":
            errors.append("complete_with_limits requires phase=deliver")
        unresolved = manifest.get("unresolved")
        if not isinstance(unresolved, list) or not unresolved:
            errors.append("complete_with_limits requires a nonempty unresolved list")
        if gate_statuses.get("limitations_disclosed") != "pass":
            errors.append("complete_with_limits requires limitations_disclosed=pass")
        if schema_version >= 4 and gate_statuses.get("quantifier_audit") != "pass":
            errors.append("schema v4-and-newer complete_with_limits requires quantifier_audit=pass")
    if args.require_ready and not ready:
        errors.append("run is not ready for complete delivery")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(
        f"claims={len(claims)} sources={len(sources)} quantifier_hits={quantifier_hit_count} "
        f"ready={'yes' if ready else 'no'}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
