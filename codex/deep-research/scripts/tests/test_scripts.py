from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
RUN_HELPER = SCRIPTS / "research_run.py"
DOCX_HELPER = SCRIPTS / "verify_docx_ooxml.py"


def run(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(argument) for argument in arguments)],
        text=True,
        capture_output=True,
        check=False,
    )


def make_docx(path: Path, text: str) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>
"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)


def source_record() -> dict[str, object]:
    return {
        "source_id": "S1",
        "canonical_location": "https://example.test/source",
        "title_or_citation": "Example Source",
        "publisher_or_court": "Example Publisher",
        "date_or_version": "2026-01-01",
        "source_type": "primary",
        "source_role": "direct_answer",
        "coverage_cells": ["core"],
        "distinct_contribution": "Direct evidence",
        "relevant_passage_or_data": "Supported proposition",
        "supported_claim_ids": [],
        "reliability_notes": "Directly opened",
        "verification_status": "direct",
    }


def lane_packet(lane_id: str, stage: str, status: str = "completed") -> dict[str, object]:
    return {
        "lane_id": lane_id,
        "stage": stage,
        "status": status,
        "exit_reason": None,
        "sources": [],
        "claims": [],
        "gaps": [],
        "confidence": "high",
    }


class DocxVerifierTests(unittest.TestCase):
    def test_sync_passes_for_equivalent_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            markdown = root / "report.md"
            docx = root / "report.docx"
            markdown.write_text("# Title\n\nAlpha beta gamma delta.\n", encoding="utf-8")
            make_docx(docx, "Title Alpha beta gamma delta.")
            result = run(DOCX_HELPER, docx, "--markdown", markdown)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual(record["substantive_sync"]["status"], "passed")
            self.assertEqual(record["substantive_sync"]["markdown_coverage"], 1.0)

    def test_sync_rejects_missing_markdown_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            markdown = root / "report.md"
            docx = root / "report.docx"
            markdown.write_text(
                "# Title\n\nAlpha beta gamma delta epsilon zeta eta theta iota kappa.\n",
                encoding="utf-8",
            )
            make_docx(docx, "Title Alpha beta.")
            result = run(DOCX_HELPER, docx, "--markdown", markdown)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing substantive Markdown text", result.stderr)


class ResearchRunTests(unittest.TestCase):
    def initialize(
        self,
        root: Path,
        budgets: dict[str, int] | None = None,
        depth: str = "focused",
    ) -> Path:
        run_dir = root / ".codex-memo" / "runs" / "run-1"
        request = root / "request-input.json"
        request.write_text(
            json.dumps(
                {
                    "question": "What does the evidence show?",
                    "depth": depth,
                    "cutoff": "2026-08-04",
                    "budgets": budgets or {},
                    **({"plan_accepted": True} if depth == "deep" else {}),
                }
            ),
            encoding="utf-8",
        )
        result = run(RUN_HELPER, "init", run_dir, "--request", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        return run_dir

    def write_lanes(self, root: Path, name: str, lanes: list[dict[str, object]]) -> Path:
        path = root / name
        path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
        return path

    def finish_lane(
        self,
        run_dir: Path,
        lane_id: str,
        stage: str,
        claims: list[dict[str, object]] | None = None,
    ) -> None:
        started = run(RUN_HELPER, "lane-start", run_dir, lane_id)
        self.assertEqual(started.returncode, 0, started.stderr)
        packet = run_dir / "packets" / stage / f"{lane_id}.json"
        packet.parent.mkdir(parents=True, exist_ok=True)
        payload = lane_packet(lane_id, stage)
        payload["claims"] = claims or []
        packet.write_text(json.dumps(payload), encoding="utf-8")
        finished = run(
            RUN_HELPER,
            "lane-finish",
            run_dir,
            lane_id,
            "--status",
            "completed",
            "--output",
            packet.relative_to(run_dir),
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)

    def test_init_checkpoint_budget_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.initialize(Path(temporary), {"tool_calls": 1})
            self.assertEqual(
                {path.name for path in run_dir.iterdir()},
                {"request.json", "run-state.json"},
            )
            checkpoint = run(
                RUN_HELPER,
                "checkpoint",
                run_dir,
                "--event",
                "source_added",
                "--usage",
                '{"tool_calls":2}',
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
            self.assertEqual(json.loads(checkpoint.stdout)["status"], "budget_exhausted")
            resumed = run(RUN_HELPER, "resume", run_dir)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout)["state"]["status"], "budget_exhausted")
            validated = run(RUN_HELPER, "validate", run_dir)
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_complete_run_requires_and_accepts_production_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.initialize(Path(temporary))
            (run_dir / "source-ledger.jsonl").write_text(
                json.dumps(source_record()) + "\n", encoding="utf-8"
            )
            (run_dir / "report.md").write_text(
                "# Answer\n\nFindings.\n\n"
                "Topic: Evidence review\n"
                "Date: 2026-08-04\n"
                "By: Codex-gpt-test\n"
                "Production details: tokens unavailable (runtime did not expose exact usage); "
                "elapsed 1 minute; subagents: none\n",
                encoding="utf-8",
            )
            checkpoint = run(
                RUN_HELPER,
                "checkpoint",
                run_dir,
                "--event",
                "audit_complete",
                "--status",
                "complete",
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
            validated = run(RUN_HELPER, "validate", run_dir)
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_complete_run_rejects_missing_production_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.initialize(Path(temporary))
            (run_dir / "source-ledger.jsonl").write_text(
                json.dumps(source_record()) + "\n", encoding="utf-8"
            )
            (run_dir / "report.md").write_text("# Answer\n\nFindings.\n", encoding="utf-8")
            run(
                RUN_HELPER,
                "checkpoint",
                run_dir,
                "--event",
                "audit_complete",
                "--status",
                "complete",
            )
            validated = run(RUN_HELPER, "validate", run_dir)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("required production block", validated.stdout)

    def test_lane_manifest_enforces_barriers_and_resume_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = self.initialize(root, depth="standard")
            lanes = self.write_lanes(
                root,
                "lanes.json",
                [
                    {
                        "lane_id": "discover-core",
                        "stage": "discovery",
                        "task": "Find direct-answer candidates",
                        "role": "research_mechanical",
                        "dependencies": [],
                        "coverage_cells": ["core"],
                    },
                    {
                        "lane_id": "read-core",
                        "stage": "read",
                        "task": "Read the promoted direct-answer source",
                        "role": "research_balanced",
                        "dependencies": ["discover-core"],
                        "coverage_cells": ["core"],
                    },
                ],
            )
            initialized = run(RUN_HELPER, "lanes-init", run_dir, "--lanes", lanes)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            ready = run(RUN_HELPER, "lanes-next", run_dir)
            self.assertEqual(json.loads(ready.stdout)["stage"], "discovery")
            self.finish_lane(run_dir, "discover-core", "discovery")
            ready = run(RUN_HELPER, "lanes-next", run_dir)
            payload = json.loads(ready.stdout)
            self.assertEqual(payload["stage"], "read")
            self.assertEqual(payload["lanes"][0]["lane_id"], "read-core")
            resumed = run(RUN_HELPER, "resume", run_dir)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout)["lane_counts"]["completed"], 1)

    def test_lane_manifest_rejects_inherited_context_and_depth_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = self.initialize(root)
            lanes = self.write_lanes(
                root,
                "bad-lanes.json",
                [
                    {
                        "lane_id": f"lane-{index}",
                        "stage": "discovery",
                        "task": "Search",
                        "role": "research_mechanical",
                        "fresh_context": False if index == 0 else True,
                    }
                    for index in range(3)
                ],
            )
            initialized = run(RUN_HELPER, "lanes-init", run_dir, "--lanes", lanes)
            self.assertNotEqual(initialized.returncode, 0)
            self.assertIn("current allocation 2", initialized.stderr)

            second_root = root / "second"
            second_root.mkdir()
            second_run = self.initialize(second_root)
            inherited = self.write_lanes(
                second_root,
                "inherited.json",
                [
                    {
                        "lane_id": "bad-context",
                        "stage": "discovery",
                        "task": "Search",
                        "role": "research_mechanical",
                        "fresh_context": False,
                    }
                ],
            )
            rejected = run(RUN_HELPER, "lanes-init", second_run, "--lanes", inherited)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("fresh_context=true", rejected.stderr)

    def test_allocation_expansion_and_followups_are_hard_counted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = self.initialize(root, depth="standard")
            discoveries = [
                {
                    "lane_id": f"discover-{number}",
                    "stage": "discovery",
                    "task": f"Discover cell {number}",
                    "role": "research_mechanical",
                }
                for number in range(1, 4)
            ]
            reads = [
                {
                    "lane_id": f"read-{number}",
                    "stage": "read",
                    "task": f"Read source {number}",
                    "role": "research_balanced",
                    "dependencies": [lane["lane_id"] for lane in discoveries],
                }
                for number in range(1, 6)
            ]
            initial = self.write_lanes(root, "initial.json", discoveries + reads)
            self.assertEqual(
                run(RUN_HELPER, "lanes-init", run_dir, "--lanes", initial).returncode, 0
            )
            self.finish_lane(run_dir, "discover-1", "discovery")
            expanded = run(
                RUN_HELPER,
                "budget-expand",
                run_dir,
                "--new-lane-limit",
                "12",
                "--reason",
                "A material claim still lacks independent verification",
                "--evidence-gain",
                "One verifier can resolve the remaining claim-source link",
            )
            self.assertEqual(expanded.returncode, 0, expanded.stderr)
            second_expansion = run(
                RUN_HELPER,
                "budget-expand",
                run_dir,
                "--new-lane-limit",
                "12",
                "--reason",
                "Try again",
                "--evidence-gain",
                "None",
            )
            self.assertNotEqual(second_expansion.returncode, 0)
            self.assertIn("one permitted lane expansion", second_expansion.stderr)

            started = run(RUN_HELPER, "lane-start", run_dir, "discover-2")
            self.assertEqual(started.returncode, 0, started.stderr)
            followup = run(
                RUN_HELPER,
                "lane-followup",
                run_dir,
                "discover-2",
                "--reason",
                "Repair one malformed field",
                "--expected-gain",
                "A registerable packet without additional searching",
            )
            self.assertEqual(followup.returncode, 0, followup.stderr)
            repeated = run(
                RUN_HELPER,
                "lane-followup",
                run_dir,
                "discover-2",
                "--reason",
                "Continue",
                "--expected-gain",
                "More",
            )
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("exhausted its follow-up allowance", repeated.stderr)
            state = json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["usage"]["worker_interactions"], 3)
            self.assertEqual(state["usage"]["followups"], 1)

    def test_deep_initialization_requires_accepted_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "question": "Run a deep investigation",
                        "depth": "deep",
                        "cutoff": "2026-08-04",
                        "budgets": {},
                    }
                ),
                encoding="utf-8",
            )
            result = run(RUN_HELPER, "init", root / "run", "--request", request)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("plan_accepted=true", result.stderr)

    def test_completed_standard_run_requires_verification_waves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = self.initialize(root, depth="standard")
            lanes = self.write_lanes(
                root,
                "lanes.json",
                [
                    {
                        "lane_id": "discover",
                        "stage": "discovery",
                        "task": "Discover candidates",
                        "role": "research_mechanical",
                    },
                    {
                        "lane_id": "read",
                        "stage": "read",
                        "task": "Read promoted source",
                        "role": "research_balanced",
                        "dependencies": ["discover"],
                    },
                ],
            )
            self.assertEqual(
                run(RUN_HELPER, "lanes-init", run_dir, "--lanes", lanes).returncode, 0
            )
            self.finish_lane(run_dir, "discover", "discovery")
            self.finish_lane(run_dir, "read", "read")
            claim = {
                "claim_id": "C1",
                "subquestion": "Core",
                "coverage_cell": "core",
                "importance": "high",
                "evidence_needed": "direct",
                "status": "directly_supported",
                "supporting_source_ids": ["S1"],
                "contrary_source_ids": [],
                "confidence": "high",
            }
            (run_dir / "claim-ledger.jsonl").write_text(
                json.dumps(claim) + "\n", encoding="utf-8"
            )
            source = source_record()
            source["supported_claim_ids"] = ["C1"]
            (run_dir / "source-ledger.jsonl").write_text(
                json.dumps(source) + "\n", encoding="utf-8"
            )
            for name in ("plan.md", "evidence-table.md"):
                (run_dir / name).write_text("content\n", encoding="utf-8")
            (run_dir / "cost-report.json").write_text("{}\n", encoding="utf-8")
            (run_dir / "report.md").write_text(
                "# Answer\n\nFindings.\n\nTopic: Test\nDate: 2026-08-04\n"
                "By: Codex-gpt-test\nProduction details: tokens unavailable "
                "(runtime did not expose exact usage); subagents: 2\n",
                encoding="utf-8",
            )
            run(
                RUN_HELPER,
                "checkpoint",
                run_dir,
                "--event",
                "audit_complete",
                "--status",
                "complete",
            )
            validated = run(RUN_HELPER, "validate", run_dir)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("no verification lane", validated.stdout)
            self.assertIn("no mechanical_audit lane", validated.stdout)

    def test_deep_run_uses_adaptive_quorum_and_contested_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = self.initialize(root, depth="deep")
            lanes: list[dict[str, object]] = [
                {
                    "lane_id": "discover",
                    "stage": "discovery",
                    "task": "Discover candidates",
                    "role": "research_mechanical",
                },
                {
                    "lane_id": "read",
                    "stage": "read",
                    "task": "Read promoted source",
                    "role": "research_balanced",
                    "dependencies": ["discover"],
                },
                {
                    "lane_id": "mechanical",
                    "stage": "mechanical_audit",
                    "task": "Check metadata and ledger structure",
                    "role": "research_mechanical",
                    "dependencies": ["read"],
                },
            ]
            for claim_number in range(1, 6):
                claim_id = f"C{claim_number}"
                for vote in range(1, 3):
                    lanes.append(
                        {
                            "lane_id": f"verify-c{claim_number}-v{vote}",
                            "stage": "verification",
                            "task": f"Independently verify {claim_id}",
                            "role": "research_balanced",
                            "dependencies": ["read"],
                            "claim_ids": [claim_id],
                            "vote_group": claim_id,
                        }
                    )
            lane_file = self.write_lanes(root, "deep-lanes.json", lanes)
            initialized = run(RUN_HELPER, "lanes-init", run_dir, "--lanes", lane_file)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            self.finish_lane(run_dir, "discover", "discovery")
            self.finish_lane(run_dir, "read", "read")
            for claim_number in range(1, 6):
                for vote in range(1, 3):
                    verdict = "supported"
                    if claim_number == 1:
                        verdict = "adverse"
                    elif claim_number == 2 and vote == 2:
                        verdict = "adverse"
                    self.finish_lane(
                        run_dir,
                        f"verify-c{claim_number}-v{vote}",
                        "verification",
                        [{"claim_id": f"C{claim_number}", "verdict": verdict}],
                    )
            self.finish_lane(run_dir, "mechanical", "mechanical_audit")
            claims = []
            for claim_number in range(1, 6):
                claims.append(
                    {
                        "claim_id": f"C{claim_number}",
                        "subquestion": "Core",
                        "coverage_cell": "core",
                        "importance": "high",
                        "evidence_needed": "direct",
                        "status": "directly_supported",
                        "supporting_source_ids": ["S1"],
                        "contrary_source_ids": [],
                        "confidence": "high",
                    }
                )
            (run_dir / "claim-ledger.jsonl").write_text(
                "".join(json.dumps(claim) + "\n" for claim in claims), encoding="utf-8"
            )
            source = source_record()
            source["supported_claim_ids"] = [f"C{number}" for number in range(1, 6)]
            (run_dir / "source-ledger.jsonl").write_text(
                json.dumps(source) + "\n", encoding="utf-8"
            )
            for name in ("plan.md", "evidence-table.md"):
                (run_dir / name).write_text("content\n", encoding="utf-8")
            (run_dir / "cost-report.json").write_text("{}\n", encoding="utf-8")
            (run_dir / "report.md").write_text(
                "# Answer\n\nFindings.\n\nTopic: Test\nDate: 2026-08-04\n"
                "By: Codex-gpt-test\nProduction details: tokens unavailable "
                "(runtime did not expose exact usage); subagents: 18\n",
                encoding="utf-8",
            )
            run(
                RUN_HELPER,
                "checkpoint",
                run_dir,
                "--event",
                "audit_complete",
                "--status",
                "complete",
            )
            validated = run(RUN_HELPER, "validate", run_dir)
            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("requires a third voter", validated.stdout)
            self.assertIn("verification-resolution.json", validated.stdout)

            reopened = run(
                RUN_HELPER,
                "checkpoint",
                run_dir,
                "--event",
                "tie_breaker_needed",
                "--status",
                "audit",
            )
            self.assertEqual(reopened.returncode, 0, reopened.stderr)
            tie_breaker_file = self.write_lanes(
                root,
                "tie-breaker.json",
                [
                    {
                        "lane_id": "verify-c2-v3",
                        "stage": "verification",
                        "task": "Resolve the split votes for C2",
                        "role": "research_balanced",
                        "dependencies": ["read"],
                        "claim_ids": ["C2"],
                        "vote_group": "C2",
                    }
                ],
            )
            added = run(RUN_HELPER, "lanes-add", run_dir, "--lanes", tie_breaker_file)
            self.assertEqual(added.returncode, 0, added.stderr)
            self.finish_lane(
                run_dir,
                "verify-c2-v3",
                "verification",
                [{"claim_id": "C2", "verdict": "supported"}],
            )
            (run_dir / "verification-resolution.json").write_text(
                json.dumps(
                    {
                        "resolutions": [
                            {
                                "claim_id": "C1",
                                "disposition": "narrowed",
                                "basis": "Lead reopened the source and narrowed the proposition.",
                                "source_ids": ["S1"],
                            },
                            {
                                "claim_id": "C2",
                                "disposition": "confirmed_after_lead_review",
                                "basis": "The lead reopened the source after the split and confirmed narrower wording.",
                                "source_ids": ["S1"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            run(
                RUN_HELPER,
                "checkpoint",
                run_dir,
                "--event",
                "audit_complete",
                "--status",
                "complete",
            )
            validated = run(RUN_HELPER, "validate", run_dir)
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)


if __name__ == "__main__":
    unittest.main()
