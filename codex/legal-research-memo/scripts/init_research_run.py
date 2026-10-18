#!/usr/bin/env python3
"""Initialize durable state for an autonomous legal research run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path


PHASES = ["frame", "research", "verify", "synthesize", "draft", "audit", "deliver"]
GATES = [
    "controlling_law",
    "currentness",
    "adverse_authority",
    "planned_coverage",
    "direct_source_audit",
    "quantifier_audit",
    "draft_claim_map",
    "material_claim_support",
    "citation_audit",
    "limitations_disclosed",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def skill_sha256() -> str:
    skill_file = Path(__file__).resolve().parent.parent / "SKILL.md"
    return hashlib.sha256(skill_file.read_bytes()).hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:60].rstrip("-") or "memo")


def default_run_dir(project_dir: Path, question: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return project_dir / ".codex-memo" / "runs" / f"{slugify(question)}-{stamp}-{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run_dir",
        nargs="?",
        type=Path,
        help="hidden run directory; defaults to PROJECT/.codex-memo/runs/<unique-run-id>",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="project root used by the default hidden run directory",
    )
    parser.add_argument("--question", required=True)
    parser.add_argument("--mode", choices=["doctrinal", "scholarly", "hybrid"], required=True)
    parser.add_argument("--effort", choices=["targeted", "standard", "deep"], required=True)
    parser.add_argument("--jurisdiction", default="")
    parser.add_argument("--cutoff", default=date.today().isoformat())
    parser.add_argument("--output-format", default="md")
    parser.add_argument(
        "--memo-path",
        action="append",
        default=[],
        help="final memo path; repeat only for expressly requested derivative deliverables",
    )
    parser.add_argument("--producer", default="Codex")
    parser.add_argument(
        "--session-id",
        default=os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID") or "",
    )
    args = parser.parse_args()

    try:
        date.fromisoformat(args.cutoff)
    except ValueError as exc:
        parser.error(f"--cutoff must be YYYY-MM-DD: {exc}")

    project_dir = args.project_dir.expanduser().resolve()
    run_dir = (
        args.run_dir.expanduser().resolve()
        if args.run_dir is not None
        else default_run_dir(project_dir, args.question).resolve()
    )
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        parser.error(f"refusing to overwrite existing run: {manifest_path}")

    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("claim-ledger.jsonl", "source-ledger.jsonl", "quantifier-audit.jsonl"):
        path = run_dir / name
        if path.exists() and path.stat().st_size:
            parser.error(f"refusing to reuse nonempty ledger: {path}")
        path.touch(exist_ok=True)

    now = timestamp()
    artifacts = {
        "claim_ledger": "claim-ledger.jsonl",
        "source_ledger": "source-ledger.jsonl",
        "events": "events.jsonl",
        "quantifier_audit": "quantifier-audit.jsonl",
    }
    if args.memo_path:
        markdown_paths = [path for path in args.memo_path if Path(path).suffix.lower() == ".md"]
        artifacts["memo"] = markdown_paths[0] if markdown_paths else args.memo_path[0]
        artifacts["deliverables"] = args.memo_path
    manifest = {
        "schema_version": 6,
        "run_id": str(uuid.uuid4()),
        "question": args.question,
        "mode": args.mode,
        "effort": args.effort,
        "jurisdiction": args.jurisdiction,
        "cutoff": args.cutoff,
        "output_format": args.output_format,
        "status": "active",
        "phase": PHASES[0],
        "next_action": "Frame the assignment and create the claim matrix.",
        "completed_phases": [],
        "assumptions": [],
        "unresolved": [],
        "blockers": [],
        "coverage_cells": [],
        "budgets": {},
        "usage": {"availability": "unavailable", "actual": {}, "estimated": {}},
        "completion_gates": {
            gate: {"status": "pending", "evidence": [], "note": ""} for gate in GATES
        },
        "artifacts": artifacts,
        "provenance": {
            "producer": args.producer,
            "skill": "legal-research-memo",
            "skill_sha256": skill_sha256(),
            "session_id": args.session_id,
        },
        "publication": {
            "working_artifacts_hidden": True,
            "visible_outputs": "completed_markdown_and_requested_derivatives_only",
            "required_formats": [part.strip() for part in args.output_format.split(",") if part.strip()],
            "provenance_header_required": True,
            "markdown_publication_nonblocking": True,
            "docx_conversion_budget_seconds": 120,
            "docx_max_conversion_attempts": 1,
            "docx_max_render_attempts": 0,
            "docx_visual_verification": "prohibited",
            "docx_structural_verification_required": True,
        },
        "created_at": now,
        "updated_at": now,
    }
    write_json(manifest_path, manifest)
    event = {
        "timestamp": now,
        "event": "run_initialized",
        "phase": PHASES[0],
        "detail": "Created autonomous legal research run state.",
    }
    (run_dir / artifacts["events"]).write_text(
        json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
