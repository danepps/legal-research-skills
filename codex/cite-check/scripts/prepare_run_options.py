#!/usr/bin/env python3
"""Preview cite-check work and prepare resolved choices for init_run.py --options.

Local extraction only: no agents, network calls, source downloads, or guessed prices.
The lead maps explicit user instructions or picker answers to flags. Pending
questions are not consent; --defaults explicitly resolves only unspecified choices.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_cites import extract_document, sha256
from prepare_units import build_prepared_units
from prepare_support_units import build_support_units
from library_options import library_options, validate_library_access

SAMPLE_NOTES = 10
FULL_TEXT = {"primary_full_text", "authoritative_reproduction", "repository_full_text", "local_library_full_text"}


def parse_footnotes(tokens: list[str], available: set[int]) -> list[int]:
    selected = set()
    for token in tokens:
        bounds = token.replace("–", "-").split("-")
        if len(bounds) not in (1, 2) or any(not b.isdigit() for b in bounds):
            raise ValueError(f"invalid footnote number/range: {token}")
        lo, hi = int(bounds[0]), int(bounds[-1])
        if lo < 1 or hi < lo or hi - lo > len(available):
            raise ValueError(f"invalid footnote range: {token}")
        selected.update(range(lo, hi + 1))
    if not selected or not selected.issubset(available):
        raise ValueError("selected footnotes must be nonempty and present in the draft")
    return sorted(selected)


def read_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path.name} must contain JSON objects")
    return rows


def source_estimate(extraction: dict, selected: list[int] | None, support: str,
                    inventory: Path | None) -> dict:
    unknown = {"status": "unknown", "full_text_sources": None, "cached_sources": None,
               "uncached_sources": None}
    if inventory is None:
        return dict(unknown, reason="Source identities and cache availability have not been resolved.")
    try:
        manifest = json.loads((inventory / "run-manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("inventory manifest must be a JSON object")
        if manifest.get("draft_sha256") != extraction["input_sha256"]:
            return dict(unknown, reason="The inventory belongs to a different draft snapshot.")
        covered = manifest.get("selected_footnotes")
        if covered is not None and (selected is None or not set(selected).issubset(covered)):
            return dict(unknown, reason="The inventory does not cover the selected scope.")
        if manifest.get("status") not in {"complete", "complete_with_limits"}:
            return dict(unknown, reason="The inventory is not fully reconciled yet.")
        units = read_rows(inventory / "citation-units.jsonl")
        checks = read_rows(inventory / "quote-checks.jsonl")
        sources = read_rows(inventory / "source-ledger.jsonl")
        chosen = [u for u in units if selected is None or u.get("footnote_number") in selected]
        if any(not u.get("source_id") for u in chosen):
            return dict(unknown, reason="Some citation units have no resolved source identity.")
        chosen_ids = {u["unit_id"] for u in chosen}
        # IDs can change with selected notes or extraction thresholds. Match
        # quotation content and location, not the regenerated P1/P2 sequence.
        def quote_key(row):
            return tuple(row.get(k) for k in ("location", "footnote_number", "note_id", "paragraph_number", "quote"))
        expected_quotes = {quote_key(p) for p in build_prepared_units(
            extraction, set(selected) if selected is not None else None)}
        linked_ids = {q.get("prepared_unit_id") for q in checks if q.get("unit_id") in chosen_ids}
        linked_quotes = {quote_key(p) for p in read_rows(inventory / "prepared-units.jsonl")
                         if p.get("prepared_unit_id") in linked_ids}
        if not expected_quotes.issubset(linked_quotes):
            return dict(unknown, reason="Quotation-to-source links are incomplete.")
        quote_units = {q["unit_id"] for q in checks if q.get("unit_id") in chosen_ids}
        # Ordinary pincite verification also needs full text, even with the
        # dedicated proposition-support pass disabled.
        wanted = {u["source_id"] for u in chosen if u["unit_id"] in quote_units or u.get("pincite")}
        if support != "off":
            support_rows = build_support_units(extraction, units, checks, support)
            wanted.update(u["source_id"] for u in support_rows
                          if u["unit_id"] in chosen_ids and u.get("unread_reason") != "out_of_scope")
        by_id = {s["source_id"]: s for s in sources}
        if len(by_id) != len(sources) or not wanted.issubset(by_id):
            return dict(unknown, reason="Source records are missing or duplicated.")
        cached = 0
        for sid in wanted:
            source = by_id[sid]
            if source.get("status") != "retrieved" or source.get("verification_basis") not in FULL_TEXT:
                continue
            path = Path(source.get("source_path") or "")
            if not path.is_absolute():
                path = inventory / path
            if path.is_file() and source.get("source_sha256") == sha256(path):
                cached += 1
        return {"status": "resolved_inventory", "inventory_path": str(inventory.resolve()),
                "full_text_sources": len(wanted),
                "cached_sources": cached, "uncached_sources": len(wanted) - cached,
                "reason": "Unique sources for quotations, recorded pincites and selected proposition support; cached means matching full-text files in this inventory. Identity/history searches, additional discovered quotations and independent audits add work."}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(unknown, reason=f"Inventory could not be used: {exc}")


def prepare_options(extraction: dict, *, coverage: str | None = None, depth: str | None = None,
                    support: str | None = None, footnotes: list[str] | None = None,
                    ask: bool = False, defaults: bool = False, inventory: Path | None = None,
                    min_quote_words: int = 8, libraries: list[dict] | None = None,
                    library: str | None = None, no_zotero: bool = False) -> dict:
    numbers = sorted(n["number"] for n in extraction.get("footnotes", [])
                     if isinstance(n.get("number"), int))
    if coverage not in {None, "all", "sample"} or depth not in {None, "standard", "deep"} or support not in {None, "off", "pincited", "all"}:
        raise ValueError("invalid picker choice")
    if footnotes is not None and coverage is not None:
        raise ValueError("choose a coverage preset or explicit footnotes, not both")
    if coverage == "sample" and not numbers:
        raise ValueError("the numbered-footnote sample is unavailable for this draft")
    selected = parse_footnotes(footnotes, set(numbers)) if footnotes is not None else (
        numbers[:SAMPLE_NOTES] if coverage == "sample" else None)
    chosen = {"coverage": "selected" if footnotes is not None else coverage or "all",
              "depth": depth or "standard", "support": support or "off", "footnotes": selected}
    prepared = build_prepared_units(extraction, set(selected) if selected is not None else None)
    counts = {"draft_footnotes": len(extraction.get("footnotes", [])), "numbered_footnotes": len(numbers),
              "selected_footnotes": len(selected) if selected is not None else len(extraction.get("footnotes", [])),
              "prepared_quotes": len(prepared), "includes_body_citations": selected is None,
              "includes_custom_marked_notes": selected is None}
    estimate = source_estimate(extraction, selected, chosen["support"], inventory)
    explicit = [name for name, value in (("coverage", coverage if footnotes is None else "selected"),
                                         ("depth", depth), ("support", support)) if value is not None]
    # A UI trigger, not a cost guarantee or a spending cap. Explicit scope plus
    # default settings can bypass the dialog with --defaults.
    sizable = counts["selected_footnotes"] >= 30 or len(prepared) >= 20 or (estimate["uncached_sources"] or 0) >= 10
    questions = []
    if (ask or sizable) and not defaults:
        if "coverage" not in explicit and len(numbers) > SAMPLE_NOTES:
            questions.append({"id": "coverage", "title": "How much of the draft should I check?",
                              "options": [{"label": "Whole draft", "value": "all", "description": f"All {counts['draft_footnotes']} notes and citations in the body."},
                                          {"label": f"First {SAMPLE_NOTES} numbered notes", "value": "sample",
                                           "description": f"A smaller test covering notes {', '.join(map(str, numbers[:SAMPLE_NOTES]))}; the rest stays unchecked."}]})
        if "depth" not in explicit:
            questions.append({"id": "depth", "title": "How much independent review should I include?",
                              "options": [{"label": "Standard", "value": "standard", "description": "Check citations and quotations, with required audits of adverse findings."},
                                          {"label": "Deep", "value": "deep", "description": "Also independently review load-bearing checks; proposition support is a separate choice."}]})
        if "support" not in explicit:
            questions.append({"id": "support", "title": "Should I also read unquoted citations for proposition support?",
                              "options": [{"label": "Off", "value": "off", "description": "Keep the dedicated proposition-support pass off."},
                                          {"label": "Pincited citations", "value": "pincited", "description": "Read unquoted cites with a page, section, URL or relevant parenthetical; adds source work."},
                                          {"label": "All citations", "value": "all", "description": "Also read bare whole-work citations; the broadest and most costly coverage."}]})
    access, library_question = library_options(libraries, library=library, no_zotero=no_zotero, defaults=defaults)
    if library_question:
        questions.append(library_question)
    blockers = extraction.get("blocking_issues", [])
    if blockers:
        questions = []
    return {"schema_version": 1, "draft_sha256": extraction["input_sha256"],
            "status": "blocked" if blockers else "needs_choice" if questions else "ready",
            "selection": chosen, "explicit_fields": explicit,
            "resolution": "defaults" if defaults else "choices_or_small_run_defaults",
            "min_quote_words": min_quote_words, "counts": counts, "sources": estimate,
            "library_access": access,
            "questions": questions, "blocking_issues": blockers,
            "budget_basis": "Coverage and source-work counts, not a dollar estimate or a hard token cap. Deep review adds audits; support is enabled only by an explicit choice."}


def resolved_selection(plan: dict, draft_hash: str) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("run options must be a JSON object")
    if plan.get("schema_version") != 1 or plan.get("status") != "ready" or plan.get("questions") or plan.get("blocking_issues"):
        raise ValueError("run options must be resolved and unblocked before initialization")
    if plan.get("draft_sha256") != draft_hash:
        raise ValueError("draft changed since the options preview; regenerate the preview")
    if "library_access" in plan:
        validate_library_access(plan["library_access"])
    value = plan.get("selection") or {}
    if not isinstance(value, dict):
        raise ValueError("run selection must be a JSON object")
    if (value.get("coverage") not in {"all", "sample", "selected"}
            or value.get("depth") not in {"standard", "deep"}
            or value.get("support") not in {"off", "pincited", "all"}):
        raise ValueError("invalid resolved choices")
    if value["support"] != "off" and "support" not in plan.get("explicit_fields", []):
        raise ValueError("proposition support requires an explicit choice")
    if value["depth"] == "deep" and "depth" not in plan.get("explicit_fields", []):
        raise ValueError("deep review requires an explicit choice")
    notes = value.get("footnotes")
    if value["coverage"] == "all":
        if notes is not None:
            raise ValueError("whole-draft coverage must not contain a footnote restriction")
    elif not isinstance(notes, list) or not notes or any(type(n) is not int or n < 1 for n in notes):
        raise ValueError("focused coverage requires nonempty numbered footnotes")
    elif notes != sorted(set(notes)) or "coverage" not in plan.get("explicit_fields", []):
        raise ValueError("focused coverage requires an explicit, unique footnote selection")
    minimum = plan.get("min_quote_words")
    if type(minimum) is not int or minimum < 1:
        raise ValueError("invalid quotation threshold")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage", choices=("all", "sample"))
    parser.add_argument("--depth", choices=("standard", "deep"))
    parser.add_argument("--support", choices=("off", "pincited", "all"))
    parser.add_argument("--footnotes", nargs="+")
    parser.add_argument("--inventory", type=Path, help="optional reconciled run for this exact draft")
    parser.add_argument("--libraries", type=Path, help="public library inventory from the current runtime; never raw config")
    library_choice = parser.add_mutually_exclusive_group()
    library_choice.add_argument("--library", help="observed library id, name or unambiguous description")
    library_choice.add_argument("--no-zotero", action="store_true", help="use supplied files and web sources this run")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--ask", action="store_true", help="offer any unsettled choices even on a short draft")
    choice.add_argument("--defaults", action="store_true", help="resolve unspecified choices to whole draft, standard, support off")
    parser.add_argument("--min-quote-words", type=int, default=8)
    args = parser.parse_args()
    try:
        if args.output.resolve() == args.draft.resolve():
            raise ValueError("output must not overwrite the draft")
        if args.libraries and args.output.resolve() == args.libraries.resolve():
            raise ValueError("output must not overwrite the library inventory")
        if args.min_quote_words < 1:
            raise ValueError("quotation threshold must be positive")
        data = extract_document(args.draft, args.min_quote_words)
        plan = prepare_options(data, coverage=args.coverage, depth=args.depth, support=args.support,
                               footnotes=args.footnotes, ask=args.ask, defaults=args.defaults,
                               inventory=args.inventory, min_quote_words=args.min_quote_words,
                               libraries=json.loads(args.libraries.read_text(encoding="utf-8")) if args.libraries else None,
                               library=args.library, no_zotero=args.no_zotero)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 1 if plan["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
