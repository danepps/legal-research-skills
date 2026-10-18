#!/usr/bin/env python3
"""Integration test for the schema-v6 draft claim-map gate."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
INITIALIZER = HERE / "init_research_run.py"
VALIDATOR = HERE / "validate_research_run.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        run = root / ".codex-memo" / "runs" / "test"
        memo = run / "memo.md"
        process = subprocess.run(
            [
                sys.executable,
                str(INITIALIZER),
                str(run),
                "--project-dir",
                str(root),
                "--question",
                "What rule governs?",
                "--mode",
                "doctrinal",
                "--effort",
                "standard",
                "--memo-path",
                "memo.md",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert process.returncode == 0, process.stderr
        memo.write_text(
            "# Test Memo\n\n## Analysis\n\nThe governing rule supports the answer.\n",
            encoding="utf-8",
        )
        claim = {
            "id": "C1",
            "proposition": "The governing rule supports the answer.",
            "claim_type": "doctrinal_synthesis",
            "claim_strength": "existence",
            "coverage_cells": ["issue-rule"],
            "importance": "dispositive",
            "status": "supported",
            "supporting_source_ids": ["S1"],
            "adverse_source_ids": [],
            "included_in_memo": True,
            "memo_section": "Analysis",
            "analysis_roles": ["conclusion", "rule_or_synthesis"],
            "draft_anchor": "The governing rule supports the answer.",
        }
        source = {
            "id": "S1",
            "citation": "Test Authority",
            "location": "local:test",
            "authority_level": "binding",
            "verification": "direct-full-text",
            "pinpoint": "1",
            "claim_ids": ["C1"],
            "coverage_cells": ["issue-rule"],
            "source_role": "direct_answer",
            "classification_status": "decided",
            "precedential_effect": "majority_holding",
            "distinct_contribution": "Supplies the governing rule.",
        }
        (run / "claim-ledger.jsonl").write_text(json.dumps(claim) + "\n", encoding="utf-8")
        (run / "source-ledger.jsonl").write_text(json.dumps(source) + "\n", encoding="utf-8")
        manifest_path = run / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["coverage_cells"] = ["issue-rule"]
        manifest["phase"] = "audit"
        manifest["artifacts"]["memo"] = "memo.md"
        for name, gate in manifest["completion_gates"].items():
            if name == "direct_source_audit":
                gate.update({"status": "not_applicable", "evidence": [], "note": ""})
            elif name == "quantifier_audit":
                gate.update(
                    {
                        "status": "pass",
                        "evidence": ["artifact:quantifier_audit"],
                        "note": "No trigger occurrences.",
                    }
                )
            elif name == "draft_claim_map":
                gate.update(
                    {
                        "status": "pass",
                        "evidence": ["artifact:memo", "claim:C1"],
                        "note": "Final claim anchors checked.",
                    }
                )
            else:
                gate.update(
                    {
                        "status": "pass",
                        "evidence": ["claim:C1", "source:S1"],
                        "note": "Test evidence.",
                    }
                )
        write_json(manifest_path, manifest)

        valid = subprocess.run(
            [sys.executable, str(VALIDATOR), str(run), "--require-ready"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert valid.returncode == 0, valid.stdout + valid.stderr

        claim["draft_anchor"] = "This text is absent."
        (run / "claim-ledger.jsonl").write_text(json.dumps(claim) + "\n", encoding="utf-8")
        invalid = subprocess.run(
            [sys.executable, str(VALIDATOR), str(run), "--require-ready"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid.returncode == 1
        assert "draft_anchor must occur exactly once" in invalid.stdout

    print("schema-v6 claim-map tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
