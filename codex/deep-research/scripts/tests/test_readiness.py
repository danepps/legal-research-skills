"""Regression coverage for evidence readiness and malformed-input boundaries."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from test_scripts import RUN_HELPER, lane_packet, run, source_record


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def claim_record() -> dict[str, object]:
    return {
        "claim_id": "C1", "subquestion": "Core", "coverage_cell": "core",
        "importance": "high", "evidence_needed": "Direct source text",
        "status": "directly_supported", "supporting_source_ids": ["S1"],
        "contrary_source_ids": [], "confidence": "high",
    }


class ReadinessTests(unittest.TestCase):
    def initialize(self, root: Path, depth: str = "focused") -> Path:
        request = root / "input.json"
        write_json(request, {"question": "What does the corpus support?", "depth": depth, "cutoff": "2026-10-19"})
        directory = root / ".codex-memo" / "runs" / "fixture"
        result = run(RUN_HELPER, "init", directory, "--request", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        return directory

    def complete(self, directory: Path, status: str = "complete") -> None:
        source = source_record()
        source["supported_claim_ids"] = ["C1"]
        write_json(directory / "source-ledger.jsonl", source)
        write_json(directory / "claim-ledger.jsonl", claim_record())
        (directory / "report.md").write_text(
            "# Answer\n\nThe corpus supports the conclusion.\n\n"
            "Topic: Fixture\nDate: 2026-10-19\nBy: Codex-gpt-test\n"
            "Production details: tokens unavailable (runtime did not expose exact usage); "
            "elapsed 1 minute; subagents: none\n", encoding="utf-8",
        )
        result = run(RUN_HELPER, "checkpoint", directory, "--event", "audit_complete", "--status", status)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unverified_material_claim_fails_complete_but_allows_disclosed_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = self.initialize(Path(temporary))
            self.complete(directory)
            self.assertEqual(run(RUN_HELPER, "validate", directory).returncode, 0)
            claim = claim_record()
            claim.update(status="unverified", supporting_source_ids=[])
            write_json(directory / "claim-ledger.jsonl", claim)
            source = source_record()
            source.update(verification_status="unverified", relevant_passage_or_data="")
            write_json(directory / "source-ledger.jsonl", source)
            result = run(RUN_HELPER, "validate", directory)
            self.assertEqual(result.returncode, 1)
            self.assertIn("remains unverified", result.stdout)
            self.assertIn("lacks directly verified source support", result.stdout)
            (directory / "unresolved.md").write_text("C1 could not be verified; the report discloses this limit.\n")
            run(RUN_HELPER, "checkpoint", directory, "--event", "limits_disclosed", "--status", "complete_with_limits")
            limited = run(RUN_HELPER, "validate", directory)
            self.assertEqual(limited.returncode, 0, limited.stdout + limited.stderr)
            self.assertIn("remains unverified", limited.stdout)

    def test_disputed_claim_can_be_grounded_in_direct_adverse_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = self.initialize(Path(temporary))
            self.complete(directory)
            claim = claim_record()
            claim.update(status="disputed", supporting_source_ids=[], contrary_source_ids=["S1"])
            write_json(directory / "claim-ledger.jsonl", claim)
            result = run(RUN_HELPER, "validate", directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_references_checked_when_either_ledger_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = self.initialize(Path(temporary))
            self.complete(directory)
            (directory / "source-ledger.jsonl").write_text("\n")
            result = run(RUN_HELPER, "validate", directory)
            self.assertEqual(result.returncode, 1)
            self.assertIn("references unknown source S1", result.stdout)
            self.assertIn("no source records", result.stdout)
            source = source_record()
            source["supported_claim_ids"] = ["C1"]
            write_json(directory / "source-ledger.jsonl", source)
            (directory / "claim-ledger.jsonl").unlink()
            result = run(RUN_HELPER, "validate", directory)
            self.assertEqual(result.returncode, 1)
            self.assertIn("references unknown claim C1", result.stdout)

    def test_verification_lane_requires_actual_assigned_claim_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = self.initialize(root, "standard")
            lanes = [
                {"lane_id": "discover", "stage": "discovery", "role": "research_mechanical", "task": "Find sources"},
                {"lane_id": "read", "stage": "read", "role": "research_balanced", "task": "Read sources", "dependencies": ["discover"]},
                {"lane_id": "verify", "stage": "verification", "role": "research_balanced", "task": "Verify C1", "dependencies": ["read"], "claim_ids": ["C1"]},
                {"lane_id": "audit", "stage": "mechanical_audit", "role": "research_mechanical", "task": "Check records", "dependencies": ["read"]},
            ]
            lane_file = root / "lanes.json"
            write_json(lane_file, {"lanes": lanes})
            result = run(RUN_HELPER, "lanes-init", directory, "--lanes", lane_file)
            self.assertEqual(result.returncode, 0, result.stderr)
            for lane in lanes:
                lane_id, stage = lane["lane_id"], lane["stage"]
                self.assertEqual(run(RUN_HELPER, "lane-start", directory, lane_id).returncode, 0)
                path = directory / "packets" / stage / f"{lane_id}.json"
                packet = lane_packet(lane_id, stage)
                write_json(path, packet)
                if stage == "verification":
                    empty = run(RUN_HELPER, "lane-finish", directory, lane_id, "--status", "completed", "--output", path)
                    self.assertEqual(empty.returncode, 1)
                    self.assertIn("lacks one valid verdict", empty.stderr)
                    packet["claims"] = [{"claim_id": "C1", "verdict": []}]
                    write_json(path, packet)
                    malformed = run(RUN_HELPER, "lane-finish", directory, lane_id, "--status", "completed", "--output", path)
                    self.assertEqual(malformed.returncode, 1)
                    self.assertNotIn("Traceback", malformed.stderr)
                    packet["claims"] = [{"claim_id": "C1", "verdict": "supported"}]
                    write_json(path, packet)
                result = run(RUN_HELPER, "lane-finish", directory, lane_id, "--status", "completed", "--output", path)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.complete(directory)
            for name in ("plan.md", "evidence-table.md"):
                (directory / name).write_text("Fixture evidence recorded.\n")
            write_json(directory / "cost-report.json", {"tokens": "unavailable"})
            result = run(RUN_HELPER, "validate", directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            # A legitimately partial packet may omit a claim, but that assignment
            # must not count as completed review at the delivery gate.
            manifest_path = directory / "lane-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            verification = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "verify")
            verification.update(status="partial", required=False)
            verification.pop("packet_sha256", None)
            write_json(manifest_path, manifest)
            write_json(directory / verification["output_path"], lane_packet("verify", "verification", "partial"))
            result = run(RUN_HELPER, "validate", directory)
            self.assertEqual(result.returncode, 1)
            self.assertIn("material claims lack registered verification lanes", result.stdout)
            (directory / "unresolved.md").write_text("C1 independent verification remains incomplete.\n")
            run(RUN_HELPER, "checkpoint", directory, "--event", "limits_disclosed", "--status", "complete_with_limits")
            limited = run(RUN_HELPER, "validate", directory)
            self.assertEqual(limited.returncode, 0, limited.stdout + limited.stderr)

    def test_rejects_impossible_dates_nonfinite_budgets_and_missing_authorization_basis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = {"question": "Bounded review", "depth": "focused", "cutoff": "2026-10-19"}
            for label, changes, message in (
                ("date", {"cutoff": "2026-99-99"}, "valid YYYY-MM-DD"),
                ("nan", {"budgets": {"tool_calls": float("nan")}}, "finite nonnegative"),
                ("infinity", {"budgets": {"tool_calls": float("inf")}}, "finite nonnegative"),
                ("basis", {"depth": "deep", "plan_accepted": True}, "plan_authorization_basis"),
            ):
                path = root / f"{label}.json"
                write_json(path, {**base, **changes})
                result = run(RUN_HELPER, "init", root / label, "--request", path)
                self.assertEqual(result.returncode, 1, label)
                self.assertIn(message, result.stderr)
            directory = self.initialize(root)
            prior_state = (directory / "run-state.json").read_bytes()
            result = run(RUN_HELPER, "checkpoint", directory, "--event", "invalid_usage", "--usage", '{"tool_calls": NaN}')
            self.assertEqual(result.returncode, 1)
            self.assertEqual((directory / "run-state.json").read_bytes(), prior_state)


if __name__ == "__main__":
    unittest.main()
