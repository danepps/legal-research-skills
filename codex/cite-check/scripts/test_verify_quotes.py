#!/usr/bin/env python3
"""Self-tests for verify_quotes.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_quotes.py")
SOURCE = (
    "It is a settled principle that “the limitations period does not begin\n"
    "to run until the plaintiff knows — or reasonably should know — of the\n"
    "injury that forms the basis of the claim.” The well-\n"
    "settled rule reflects ﬁdelity to fairness.\n"
    "\f"
    "The court held that equitable tolling is reserved for extraordinary\n"
    "circumstances beyond the litigant's control, and mere excusable neglect\n"
    "will not suffice.\n"
)


def run(arguments: list[str]) -> tuple[int, dict]:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source.txt"
        source.write_text(SOURCE, encoding="utf-8")
        process = subprocess.run(
            [sys.executable, str(SCRIPT), str(source), *arguments],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return process.returncode, json.loads(process.stdout)


def main() -> int:
    code, report = run(["the injury that forms the basis of the claim"])
    assert code == 0 and report["results"][0]["status"] == "verbatim"

    code, report = run(
        ['"the limitations period does not begin to run until the plaintiff knows--or reasonably should know']
    )
    assert code == 0 and report["results"][0]["status"] == "normalized"

    code, report = run(["the limitations period does not begin . . . of the claim"])
    assert code == 0 and report["results"][0]["status"] == "altered"
    assert report["results"][0]["alteration_reviewed"] is False

    code, report = run(
        [
            "equitable tolling is reserved for circumstances beyond the "
            "litigant's control, and mere excusable neglect will suffice"
        ]
    )
    result = report["results"][0]
    assert code == 1 and result["status"] == "not_found"
    assert "extraordinary" in result["word_diff"]["source_only"]
    assert "not" in result["word_diff"]["source_only"]

    code, report = run(
        ["equitable tolling is reserved for extraordinary circumstances", "--first-page", "461"]
    )
    result = report["results"][0]
    assert code == 0 and result["page"] == 462
    assert "printed_page_depends_on_asserted_first_page" not in result["warnings"]

    marked = "<<pg. 979>> Alpha beta gamma. <<pg. 980>> Zeta eta theta."
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "marked.txt"
        source.write_text(marked, encoding="utf-8")
        items = Path(directory) / "items.json"
        items.write_text(
            json.dumps(
                [
                    {
                        "prepared_unit_id": "P1",
                        "unit_id": "U1",
                        "source_id": "S1",
                        "quote": "Zeta eta theta",
                        "pincite": "980",
                    }
                ]
            ),
            encoding="utf-8",
        )
        output = Path(directory) / "quote-checks.jsonl"
        process = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(source),
                "--json",
                str(items),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert process.returncode == 0
        row = json.loads(output.read_text(encoding="utf-8"))
        assert row["status"] == "verbatim"
        assert row["page"] == 980 and row["pincite_ok"] is True
        assert len(row["source_sha256"]) == 64

    print("verify_quotes tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
