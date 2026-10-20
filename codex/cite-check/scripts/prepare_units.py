#!/usr/bin/env python3
"""Build deterministic quote/context packets for cite-check resolution."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from extract_cites import cross_reference_metadata


ANTECEDENT_DEPTH = 3
US_PINCITE = re.compile(r"\b(\d+)\s+U\.\s?S\.\s+(\d+),\s*(\d+)")


def syllabus_hint(text: str) -> bool:
    return any(match.group(2) == match.group(3) for match in US_PINCITE.finditer(text))


def preceding_notes(notes: dict[int, dict], number: int, depth: int = ANTECEDENT_DEPTH) -> dict[str, str]:
    result: dict[str, str] = {}
    cursor = number - 1
    following_id = True
    while cursor >= 1 and (len(result) < depth or following_id):
        row = notes.get(cursor)
        if row and str(row.get("text", "")).strip(". "):
            result[str(cursor)] = str(row["text"])
            text = str(row["text"])
            internal = bool(re.fullmatch(r"\s*(?:see\s+)?(?:infra|supra)\s+(?:part|section|§)\s+[^.;]+[.;]?\s*", text, re.IGNORECASE))
            following_id = internal or bool(cross_reference_metadata(text)["leading_id"])
        cursor -= 1
    return result


def supra_targets(notes: dict[int, dict], home: dict, antecedents: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    source_rows = [home] + [notes[int(number)] for number in antecedents if int(number) in notes]
    seen = set()
    while source_rows:
        row = source_rows.pop(0)
        for redirect in row.get("supra", []):
            target_number = int(redirect["note"])
            if target_number in seen:
                continue
            seen.add(target_number)
            target = notes.get(target_number)
            if target:
                result[str(target_number)] = str(target.get("text", ""))
                source_rows.append(target)
                if target.get("leading_id"):
                    for number, text in preceding_notes(notes, target_number).items():
                        result[number] = text
                        source_rows.append(notes[int(number)])
    return result


def build_prepared_units(data: dict, footnotes: set[int] | None = None) -> list[dict]:
    notes = {row["number"]: row for row in data.get("footnotes", []) if isinstance(row.get("number"), int)}
    by_id = {row.get("note_id"): row for row in data.get("footnotes", []) if row.get("note_id")}
    units: list[dict] = []

    def add(row: dict, location: str) -> None:
        number = row.get("primary_supporting_footnote") if location == "body" else row.get("footnote_number")
        number = int(number) if isinstance(number, int) or str(number).isdigit() else None
        note_id = row.get("primary_supporting_note_id") if location == "body" else row.get("note_id")
        home = by_id.get(note_id, notes.get(number, {}))
        antecedents = preceding_notes(notes, number) if number else {}
        if footnotes is not None and number not in footnotes:
            return
        units.append(
            {
                "prepared_unit_id": f"P{len(units) + 1}",
                "location": location,
                "footnote_number": number,
                "note_id": home.get("note_id"),
                "paragraph_number": row.get("paragraph_number"),
                "quote": row.get("quote", ""),
                "body_context": row.get("body_context", "") if location == "body" else "",
                "full_footnote": home.get("text", row.get("full_footnote", "")),
                "leading_id": bool(home.get("leading_id", False)),
                "antecedents": antecedents,
                "supra_targets": supra_targets(notes, home, antecedents) if home else {},
                "syllabus_hint": syllabus_hint(str(home.get("text", ""))),
                "primary_inferred_from_paragraph": row.get("primary_inferred_from_paragraph", False),
                "block_quote": row.get("block_quote", False),
            }
        )

    for row in data.get("body_quotes", []):
        add(row, "body")
    for row in data.get("footnote_quotes", []):
        add(row, "footnote")
    return units


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--footnotes", nargs="+", help="Footnote numbers or inclusive ranges, e.g. 1 5-8")
    args = parser.parse_args()
    data = json.loads(args.extraction.read_text(encoding="utf-8"))
    wanted: set[int] | None = None
    if args.footnotes:
        wanted = set()
        for token in args.footnotes:
            if "-" in token:
                lower, upper = (int(value) for value in token.split("-", 1))
                if lower > upper:
                    parser.error(f"invalid descending footnote range: {token}")
                wanted.update(range(lower, upper + 1))
            else:
                wanted.add(int(token))
    units = build_prepared_units(data, wanted)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in units)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(json.dumps({"prepared_unit_count": len(units)}))
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
