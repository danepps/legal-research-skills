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


def run(arguments: list[str], text: str = SOURCE) -> tuple[int, dict]:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source.txt"
        source.write_text(text, encoding="utf-8")
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
        ["The witness resigned the contract after the call."],
        "The witness re-signed the contract after the call.",
    )
    assert code == 1 and report["results"][0]["status"] == "not_found"
    for source, quote in (
        ("The limita-\ntions period begins today.", "The limitations period begins today."),
        ("The well-\nsettled rule applies here.", "The well-settled rule applies here."),
        ("The limita\u00adtions period begins today.", "The limitations period begins today."),
    ):
        code, report = run([quote], source)
        assert code == 0 and report["results"][0]["status"] == "normalized"

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

    # The same quoted passage may appear in the syllabus and opinion, or twice
    # in the opinion. A correct later-page pinpoint must remain verifiable.
    marked = "<<pg. 979>> Zeta eta theta. <<pg. 980>> Zeta eta theta."
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
        assert "multiple_matches" in row["warnings"]
        assert len(row["source_sha256"]) == 64

    # Token boundaries (2026-11-14): substring search accepted quotations that
    # began or ended inside a source word or number as verbatim.
    def status_of(source: str, quote: str) -> dict:
        return run([quote], source)[1]["results"][0]

    for source, quote in (
        ("It is ineligible for copyright protection.", "eligible for copyright protection"),
        (
            "It was unreasonable to exclude county and state nursing home facilities.",
            "reasonable to exclude county and state nursing home facilities",
        ),
        ("They must pay more than $400,000 now.", "pay more than $400,"),
        ("They must pay more than $400,000 now.", "pay more than $400"),
        ("The fee rose to $3.5 million last year.", "The fee rose to $3"),
        ("They must pay more than $400,000 now.", "000 now"),
        ("The agency acted reasonably in this case.", "The agency acted reason"),
        ("under section 1983 of the Act", "under section 198"),
        ("liability under Rule 10b-5 is strict", "liability under Rule 10"),
        ("The defendant can't be retried here.", "The defendant can"),
        ("It reviewed the court’s findings.", "reviewed the court"),
        ("That is non-binding precedent in this circuit.", "binding precedent in this circuit"),
        ("the decision-making process was flawed", "the decision"),
        ("The work is in-\neligible for copyright protection.", "eligible for copyright protection"),
        ("The work is in-\n\feligible for copyright protection.", "eligible for copyright protection"),
        ("The work is in\u00adeligible for copyright protection.", "eligible for copyright protection"),
        ("Their naïveté was plain.", "veté was plain"),
        ("The x\u0302 term governs here.", "The x"),
        ("It was made under N.J.S.A. 47:1A-11 of the Act.", "made under N.J.S.A. 47:1A-1"),
        (
            "The rule is un\u00ad\nnecessary because the amendment covers it.",
            "necessary because the amendment covers it",
        ),
        (
            "We hold the rule is un\u00ad\nnecessary because the amendment covers it.",
            "We hold the rule is un",
        ),
    ):
        result = status_of(source, quote)
        assert result["status"] == "not_found", (source, quote, result)
        assert "partial_token_match" in result["warnings"], (source, quote, result)
        assert result["partial_token_match"], (source, quote, result)
    result = status_of("It is ineligible for copyright protection.", "eligible for copyright protection")
    assert "ineligible" in result["partial_token_match"]

    for source, quote, expected in (
        ("eligible for copyright protection", "eligible for copyright protection", "verbatim"),
        ("They must pay more than $400,000 now.", "pay more than $400,000", "verbatim"),
        ("In 2020, 15 states acted.", "In 2020", "verbatim"),
        ("It was eligible. The rest follows.", "It was eligible", "verbatim"),
        ("That is non-binding precedent.", "non-binding precedent", "verbatim"),
        ("The plaintiff knows—or should know—of it.", "or should know", "verbatim"),
        ("The plaintiff knows--or should know--of it.", "or should know", "verbatim"),
        ("the pre- and post-trial motions", "and post-trial motions", "verbatim"),
        ("See id. at 516-17 for the rule.", "See id. at 516", "verbatim"),
        ("It reviewed the court's findings.", "the court's findings", "verbatim"),
        ("the 'reasonable' test applies", "reasonable", "verbatim"),
        ("The work is in-\neligible for protection.", "ineligible for protection", "normalized"),
    ):
        result = status_of(source, quote)
        assert result["status"] == expected and not result["warnings"], (source, quote, result)

    # A genuine occurrence after a partial one is the match and the only count.
    result = status_of(
        "It is ineligible for protection here. Later it became eligible for protection again.",
        "eligible for protection",
    )
    assert result["status"] == "verbatim" and result["occurrences"] == 1
    assert result["match_excerpt"] == "eligible for protection"

    # Page selection and occurrence counting ignore partial hits on other pages.
    paged = (
        "<<pg. 10>> It is ineligible for protection. It is eligible for protection.\n"
        "<<pg. 15>> Again, eligible for protection. And ineligible for protection."
    )
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / "paged.txt"
        source_path.write_text(paged, encoding="utf-8")
        items = Path(directory) / "items.json"
        rows = [
            {"quote": "eligible for protection", "pincite": "15"},
            {"quote": "ineligible for protection", "pincite": "15"},
        ]
        items.write_text(json.dumps(rows), encoding="utf-8")
        process = subprocess.run(
            [sys.executable, str(SCRIPT), str(source_path), "--json", str(items)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        first, second = json.loads(process.stdout)["results"]
        assert first["status"] == "verbatim" and first["occurrences"] == 2
        assert first["page"] == 15 and first["pincite_ok"] is True
        assert second["status"] == "verbatim" and second["occurrences"] == 2
        assert second["page"] == 15 and second["pincite_ok"] is True

    # Folded typography and marked alterations follow the same rule.
    result = status_of(
        "The work is “in\u00adeligible” for copy\u00adright protection.",
        "eligible' for copyright protection",
    )
    assert result["status"] == "not_found"
    result = status_of(
        "The statute is clearly ineligible for protection under the Act.",
        "The statute is . . . eligible for protection",
    )
    assert result["status"] == "not_found"
    result = status_of(
        "The statute is clearly eligible for protection under the Act.",
        "The statute is . . . eligible for protection",
    )
    assert result["status"] == "altered"
    result = status_of(
        "The court said the statute was unreasonable to apply.",
        "[T]he statute was . . . reasonable to apply",
    )
    assert result["status"] == "not_found"
    result = status_of(
        "Yesterday the court held that the claim fails.", "[T]he court held that the claim fails"
    )
    assert result["status"] == "altered"
    result = status_of(
        "It said the agency was reasonable in its views.", "the agency [is] reasonable in its view"
    )
    assert result["status"] == "not_found"

    # Review of 2026-11-14: source edges, bracket endings, a quoted hyphen.
    for source, quote in (
        ("The rule applies under section 1983.", "The rule applies under section 1983"),
        ("It called this 'reasonable'", "reasonable"),
        ("These are the plaintiffs'", "These are the plaintiffs"),
        ("eligible for protection, it said.", "eligible for protection"),
        ("'eligible for protection', it said.", "eligible for protection"),
        ("The rule applies under section 1983", "The rule applies under section 1983"),
        ("the pre- and post-trial motions", "the pre-"),
    ):
        result = status_of(source, quote)
        assert result["status"] == "verbatim" and not result["warnings"], (source, quote, result)
    for source, quote in (
        ("The work is non-binding precedent.", "The work is non-"),
        ("The work is in-\neligible for protection.", "The work is in-"),
        ("The work is non-binding precedent.", "-binding precedent"),
    ):
        result = status_of(source, quote)
        assert result["status"] == "not_found", (source, quote, result)
        assert "partial_token_match" in result["warnings"], (source, quote, result)
    # A bracket's longer expansion is tried when the shorter one ends inside a word.
    result = status_of("The old mayor may issue an order.", "The [official] may")
    assert result["status"] == "altered", result
    assert result["match_excerpt"] == "The old mayor may", result
    assert result["bracket_map"] == [{"draft": "[official]", "source_normalized": "old mayor"}], result
    assert result["alteration_reviewed"] is False
    result = status_of("The old mayor issued an order.", "The [official] may")
    assert result["status"] == "not_found", result
    result = status_of(
        "The old mayor may issue an order, and the old mayor may not.",
        "The [official] may . . . the [official] may not",
    )
    assert result["status"] == "altered", result

    # Issue #2: soft hyphens at a line end and bracketed star-page markers.
    soft = "The rule is un\u00ad\nnecessary because the amendment already covers it."
    result = status_of(soft, "is unnecessary because the amendment already covers it")
    assert result["status"] == "normalized" and not result["warnings"], result
    assert status_of(soft, "is un necessary because the amendment")["status"] == "not_found"
    assert status_of(soft, "necessary because the amendment")["status"] == "not_found"
    # Re-flowed text turns the line break after a soft hyphen into a space.
    result = status_of(
        "The rule is un\u00ad necessary because it is covered.", "is unnecessary because it is covered"
    )
    assert result["status"] == "normalized", result
    result = status_of(
        "The rule is unnecessary because it is covered.", "is un\u00ad necessary because it is covered"
    )
    assert result["status"] == "normalized", result
    marked_source = "the court held that the [*516] statute applies here."
    result = status_of(marked_source, "the court held that the statute applies here.")
    assert result["status"] == "verbatim" and not result["warnings"], result
    result = status_of(
        "the court held that the [**12] statute applies here.",
        "the court held that the statute applies here",
    )
    assert result["status"] == "verbatim", result
    for source in (
        "the court held that the *516 statute applies here.",  # may be a footnote asterisk
        "the court [sic] held that the statute applies here.",  # other bracketed text
    ):
        result = status_of(source, "the court held that the statute applies here")
        assert result["status"] == "not_found", (source, result)
    paged_source = (
        "Syllabus text. [*515] The court first held one thing. It then held that the [*516] "
        "statute applies here. [*517] Finally it remanded the case."
    )
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / "bracketed.txt"
        source_path.write_text(paged_source, encoding="utf-8")
        items = Path(directory) / "items.json"
        items.write_text(
            json.dumps(
                [
                    {"quote": "It then held that the statute applies here", "pincite": "515-16"},
                    {"quote": "Finally it remanded the case", "pincite": "516"},
                ]
            ),
            encoding="utf-8",
        )
        process = subprocess.run(
            [sys.executable, str(SCRIPT), str(source_path), "--json", str(items)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        report = json.loads(process.stdout)
        first, second = report["results"]
        assert report["pagination_basis"] == "star_marker_sequence", report["pagination_basis"]
        assert first["status"] == "verbatim" and first["page"] == 515 and first["page_end"] == 516
        assert first["pincite_ok"] is True
        assert second["status"] == "verbatim" and second["page"] == 517
        assert second["pincite_ok"] is False
    gap = "the statute is in-\n[*516]\neligible for protection here."
    result = status_of(gap, "the statute is ineligible for protection here")
    assert result["status"] == "normalized", result
    assert status_of(gap, "eligible for protection here")["status"] == "not_found"

    # A bracket-only quotation against an empty file used to raise IndexError.
    assert status_of("\f ", "[T]")["status"] == "not_found"

    # Flattened footnote calls are accepted, flagged for a reader.
    for source, quote in (
        ("The work receives copyright protection12 under the statute.", "receives copyright protection"),
        ("The Act was passed in 1871.45 The Court later read it broadly.", "The Act was passed in 1871."),
        ("Under section 1983,45 plaintiffs may sue.", "Under section 1983"),
    ):
        result = status_of(source, quote)
        assert result["status"] == "verbatim", (source, quote, result)
        assert "match_abuts_digits" in result["warnings"] and result["requires_judgment"] is True

    print("verify_quotes tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
