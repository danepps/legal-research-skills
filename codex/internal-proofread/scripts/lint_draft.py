#!/usr/bin/env python3
"""Build a document symbol index and emit deterministic proofreading candidates."""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

from common import excerpt_around, normalize_space, read_json, stable_id, write_json, write_jsonl


XREF_RE = re.compile(
    r"\b(Parts?|Sections?|Appendix|Appendices|Tables?|Figures?)\s+"
    r"([A-Z0-9IVXLC]+(?:\.[A-Z0-9]+)*(?:\s*(?:,|and|&)\s*[A-Z0-9IVXLC]+(?:\.[A-Z0-9]+)*)*)",
    re.I,
)
XREF_LABEL_RE = re.compile(r"[A-Z0-9IVXLC]+(?:\.[A-Z0-9]+)*", re.I)
NOTE_XREF_RE = re.compile(r"\b(supra|infra)\s+notes?\s+(\d+)\b", re.I)
HEADING_LABEL_RE = re.compile(r"^(?:(Part|Section|Appendix)\s+)([A-Z0-9IVXLC]+(?:\.[A-Z0-9]+)*)\b", re.I)
CAPTION_RE = re.compile(r"^(Table|Figure)\s+([A-Z0-9IVXLC]+(?:\.[A-Z0-9]+)*)\b", re.I)
TOC_ENTRY_RE = re.compile(r"^([IVXLC]+|[A-Z]|\d+)\.\s+(.+?)\s+\d+\s*$")
TOC_STYLE_RE = re.compile(r"toc\s+(\d+)", re.I)
DEFINED_TERM_PATTERNS = (
    re.compile(r"[“\"]([^”\"]{1,60})[”\"]\s+(?:means|refers to|shall mean)\b", re.I),
    re.compile(r"(?:hereinafter|referred to as)\s+(?:the\s+)?[“\"]([^”\"]{1,60})[”\"]", re.I),
)
DIRECTIONAL_STYLE_PAIRS = {
    frozenset(("toward", "towards")), frozenset(("backward", "backwards")),
    frozenset(("forward", "forwards")), frozenset(("afterward", "afterwards")),
}
MIXED_SIGNAL_RE = re.compile(r"\bsee\s+also\s+generally\b", re.I)
US_SPACING_RE = re.compile(r"\bU\.\s+S\.")
DOUBLE_ID_PERIOD_RE = re.compile(r"\bId\.\.", re.I)
REPORTER_PLACEHOLDER_RE = re.compile(r"\b\d{1,3}\s+U\.\s*S\.\s+_+\s+\((?:17|18|19|20)\d{2}\)")
SLIP_PIN_PLACEHOLDER_RE = re.compile(r"\bat\s+_+\s+\(slip\s+op\.?(?:\s+at)?\s+\d+", re.I)
YEAR_SHAPED_US_PINCITE_RE = re.compile(
    r"\b\d{1,3}\s+U\.\s*S\.\s+\d{1,4},\s+((?:17|18|19|20)\d{2})\s+\((?:17|18|19|20)\d{2}\)"
)
CASE_CITE_RE = re.compile(
    r"\b(?P<case>[A-Z][^,.;:()]{1,100}?\s+v\.\s+[A-Z][^,.;:()]{1,100}?),\s+"
    r"(?P<volume>\d{1,3})\s+U\.\s*S\.\s+(?P<page>\d{1,4}|_+)"
    r"(?:,\s+(?P<pincite>\d{1,4}(?:[–-]\d{1,4})?))?\s+"
    r"\((?P<parenthetical>[^)]*?(?P<year>(?:17|18|19|20)\d{2}))\)"
)
CENTURY_RE = re.compile(
    r"\b(?P<ordinal>seventeenth|eighteenth|nineteenth|twentieth|twenty-first|twenty first)\s+centur(?:y|ies)\b",
    re.I,
)
CENTURY_NUMBERS = {
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "twenty-first": 21,
    "twenty first": 21,
}


def finding(document: dict, rule_id: str, category: str, block: dict, start: int, end: int,
            message: str, suggestion: str, confidence: float, severity: str = "warning",
            impact: str = "medium", detection: str = "exact") -> dict:
    text = str(block.get("text", ""))
    finding_id = stable_id(document.get("input_sha256"), rule_id, block.get("block_id"), start, end, text[start:end])
    return {
        "finding_id": finding_id,
        "source_sha256": document.get("input_sha256"),
        "origin": "static",
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "impact": impact,
        "confidence": confidence,
        "detection": detection,
        "location": {
            "story": block.get("story"),
            "block_id": block.get("block_id"),
            "char_start": start,
            "char_end": end,
            "heading_path": block.get("heading_path", []),
        },
        "excerpt": excerpt_around(text, start, end),
        "message": message,
        "suggestion": suggestion,
        "status": "candidate",
    }


def target_key(kind: str, label: str) -> str:
    return f"{kind.lower()}:{label.upper().rstrip('.')}"


def canonical_xref_kind(kind: str) -> str:
    lowered = kind.lower()
    if lowered.startswith("part"):
        return "Part"
    if lowered.startswith("section"):
        return "Section"
    if lowered.startswith("append"):
        return "Appendix"
    if lowered.startswith("table"):
        return "Table"
    return "Figure"


def normalized_heading(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def heading_case(text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z’'-]*", text)
    if not words:
        return "uncased"
    letters = "".join(words)
    if letters.isupper():
        return "all_caps"
    if any(len(word) >= 3 and word.isupper() for word in words):
        return "hybrid_caps"
    small_words = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "of", "on", "or", "over", "the", "to", "upon", "v", "via", "after"}
    title_like = True
    for index, word in enumerate(words):
        bare = word.strip("’'-")
        if not bare:
            continue
        if index and bare.casefold() in small_words:
            continue
        if not bare[0].isupper():
            title_like = False
            break
    return "title_case" if title_like else "mixed_case"


def toc_heading_index(blocks: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    body_by_title: dict[str, list[dict]] = defaultdict(list)
    for block in blocks:
        if block.get("kind") == "heading":
            body_by_title[normalized_heading(str(block.get("text", "")))].append(block)
    stack: dict[int, str] = {}
    by_body_id: dict[str, dict] = {}
    entries: list[dict] = []
    for block in blocks:
        style_match = TOC_STYLE_RE.fullmatch(str(block.get("style_name", "")).strip())
        entry_match = TOC_ENTRY_RE.match(str(block.get("text", "")).strip())
        if not style_match or not entry_match:
            continue
        level = int(style_match.group(1))
        local_label, title = entry_match.groups()
        stack[level] = local_label.upper()
        for deeper in [value for value in stack if value > level]:
            stack.pop(deeper, None)
        full_label = ".".join(stack[value] for value in sorted(stack) if value <= level)
        candidates = body_by_title.get(normalized_heading(title), [])
        target = candidates[0] if candidates else None
        item = {
            "toc_block_id": block.get("block_id"),
            "level": level,
            "local_label": local_label.upper(),
            "label": full_label,
            "title": title,
            "target_block_id": target.get("block_id") if target else None,
        }
        entries.append(item)
        if target:
            by_body_id[str(target.get("block_id"))] = item
    return by_body_id, entries


def one_edit_apart(left: str, right: str) -> bool:
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    index = mismatches = 0
    for char in right:
        if index < len(left) and left[index] == char:
            index += 1
        else:
            mismatches += 1
            if mismatches > 1:
                return False
    return True


def repeated_long_spans(blocks: list[dict], window: int = 18) -> list[dict]:
    """Return one representative exact word-sequence match per block pair."""
    shingles: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for block in blocks:
        if not block.get("reviewable", True):
            continue
        text = str(block.get("text", ""))
        tokens = list(re.finditer(r"\b[A-Za-z0-9][A-Za-z0-9’'-]*\b", text))
        lowered = [token.group(0).casefold() for token in tokens]
        for index in range(0, max(0, len(tokens) - window + 1)):
            key = tuple(lowered[index:index + window])
            shingles[key].append({
                "block_id": str(block.get("block_id")),
                "char_start": tokens[index].start(),
                "char_end": tokens[index + window - 1].end(),
                "excerpt": text[tokens[index].start():tokens[index + window - 1].end()],
            })
    by_pair: dict[tuple[str, str], dict] = {}
    for occurrences in shingles.values():
        distinct = {row["block_id"] for row in occurrences}
        if len(distinct) < 2:
            continue
        for left_index, left in enumerate(occurrences):
            for right in occurrences[left_index + 1:]:
                if left["block_id"] == right["block_id"]:
                    continue
                pair = tuple(sorted((left["block_id"], right["block_id"])))
                by_pair.setdefault(pair, {
                    "kind": "repeated_long_span",
                    "window_words": window,
                    "first": left,
                    "second": right,
                })
    return sorted(by_pair.values(), key=lambda row: (row["first"]["block_id"], row["second"]["block_id"]))


def serial_comma_inventory(blocks: list[dict]) -> list[dict]:
    """Generate a broad, deterministic set for contextual serial-comma review."""
    candidates: list[dict] = []
    for block in blocks:
        if block.get("story") != "body" or block.get("kind") != "paragraph" or not block.get("reviewable", True):
            continue
        text = str(block.get("text", ""))
        for sentence_match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", text):
            sentence = sentence_match.group(0)
            if "," not in sentence:
                continue
            for coordinator in re.finditer(r"(?<!,)(?<!;)\s+(and|or)\s+", sentence, re.I):
                left = sentence[:coordinator.start()]
                right = sentence[coordinator.end():]
                if "," not in left or not re.search(r"\b[A-Za-z][A-Za-z’'-]*\b", right):
                    continue
                start = sentence_match.start() + coordinator.start(1)
                end = sentence_match.start() + coordinator.end(1)
                candidates.append({
                    "block_id": block.get("block_id"),
                    "char_start": start,
                    "char_end": end,
                    "coordinator": coordinator.group(1),
                    "sentence": normalize_space(sentence),
                    "excerpt": excerpt_around(text, start, end),
                })
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--symbols", required=True, type=Path)
    args = parser.parse_args()
    document = read_json(args.document)
    blocks = list(document.get("blocks", []))
    notes = list(document.get("notes", []))
    all_blocks = blocks + notes
    findings: list[dict] = []
    headings: list[dict] = []
    captions: list[dict] = []
    crossrefs: list[dict] = []
    definitions: list[dict] = []
    targets: dict[str, list[str]] = defaultdict(list)
    case_citations: dict[str, list[dict]] = defaultdict(list)

    # OOXML footnote IDs are storage identifiers, not displayed note numbers.
    # Build the displayed-number map from first reference order in the body.
    referenced_note_ids: list[str] = []
    seen_note_ids: set[str] = set()
    for block in blocks:
        for note_id in block.get("footnote_ids", []):
            raw_id = str(note_id)
            if raw_id not in seen_note_ids:
                seen_note_ids.add(raw_id)
                referenced_note_ids.append(raw_id)
    display_to_raw = {str(index): raw_id for index, raw_id in enumerate(referenced_note_ids, 1)}
    raw_to_display = {raw_id: int(display) for display, raw_id in display_to_raw.items()}

    toc_by_heading, toc_entries = toc_heading_index(blocks)

    for block in blocks:
        text = str(block.get("text", ""))
        special_heading = (
            str(block.get("style_name", "")).casefold() == "intro/conclusion"
            and 0 < len(text.split()) <= 12
        )
        if block.get("kind") == "heading" or special_heading:
            item = {
                "block_id": block.get("block_id"),
                "text": text,
                "heading_level": block.get("heading_level") or 1,
                "case_profile": heading_case(text),
                "structural_only": bool(special_heading and block.get("kind") != "heading"),
            }
            toc_item = toc_by_heading.get(str(block.get("block_id")))
            match = HEADING_LABEL_RE.match(text)
            if toc_item and block.get("kind") == "heading":
                label = str(toc_item["label"])
                item.update({"kind": "Section", "label": label, "toc_block_id": toc_item["toc_block_id"]})
                targets[target_key("Section", label)].append(str(block.get("block_id")))
                if int(toc_item["level"]) == 1:
                    targets[target_key("Part", label)].append(str(block.get("block_id")))
            elif match and block.get("kind") == "heading":
                kind = match.group(1) or "Section"
                label = match.group(2)
                item.update({"kind": kind, "label": label})
                targets[target_key(kind, label)].append(str(block.get("block_id")))
            headings.append(item)
        caption = CAPTION_RE.match(text)
        if caption:
            kind, label = caption.groups()
            captions.append({"block_id": block.get("block_id"), "kind": kind, "label": label, "text": text})
            targets[target_key(kind, label)].append(str(block.get("block_id")))
        for bookmark in block.get("bookmarks", []):
            targets[f"bookmark:{bookmark}"] .append(str(block.get("block_id")))

    # Surface defects and candidate omissions.
    duplicate_text: dict[str, list[dict]] = defaultdict(list)
    safe_duplicate_words = {"had", "that"}
    for block in all_blocks:
        text = str(block.get("text", ""))
        if not text or not block.get("reviewable", True):
            continue
        normalized = normalize_space(text).casefold()
        if len(normalized.split()) >= 8:
            duplicate_text[normalized].append(block)
        for match in re.finditer(r"\b([A-Za-z][A-Za-z’'-]*)\s+\1\b", text, flags=re.I):
            token = match.group(1).casefold()
            confidence = 0.7 if token in safe_duplicate_words else 0.97
            findings.append(finding(document, "text.adjacent_duplicate", "duplication", block, match.start(), match.end(),
                                    f"Adjacent repetition of “{match.group(1)}” may be accidental.",
                                    f"Review whether one occurrence of “{match.group(1)}” should be removed.",
                                    confidence, impact="high" if confidence > 0.9 else "medium",
                                    detection="heuristic" if confidence < 0.9 else "exact"))
        for match in re.finditer(r"\s+([,;:!?])", text):
            findings.append(finding(document, "text.space_before_punctuation", "punctuation", block, match.start(), match.end(),
                                    "Whitespace appears immediately before punctuation.",
                                    f"Remove the space before “{match.group(1)}” if unintended.", 0.98, severity="error", impact="low"))
        for match in re.finditer(r"([,;:!?])\1+", text):
            findings.append(finding(document, "text.repeated_punctuation", "punctuation", block, match.start(), match.end(),
                                    "Punctuation mark is repeated.", "Review and retain only the intended punctuation.", 0.97,
                                    severity="error", impact="low"))
        for match in MIXED_SIGNAL_RE.finditer(text):
            findings.append(finding(
                document, "citation.mixed_signal", "footnote", block, match.start(), match.end(),
                "The phrase combines the distinct citation signals 'see also' and 'see generally'.",
                "Use either 'see also' or 'see generally,' according to the intended relationship.",
                0.99, severity="error", impact="low",
            ))
        for match in US_SPACING_RE.finditer(text):
            findings.append(finding(
                document, "citation.us_reporter_spacing", "footnote", block, match.start(), match.end(),
                "The reporter abbreviation contains an internal space.",
                "Normalize the abbreviation to 'U.S.' if that is the draft's citation convention.",
                0.98, impact="low",
            ))
        for match in DOUBLE_ID_PERIOD_RE.finditer(text):
            findings.append(finding(
                document, "citation.id_double_period", "footnote", block, match.start(), match.end(),
                "'Id.' is followed by a second period.", "Remove the extra period.",
                0.99, severity="error", impact="low",
            ))
        for rule_id, pattern in (
            ("citation.reporter_page_placeholder", REPORTER_PLACEHOLDER_RE),
            ("citation.slip_pincite_placeholder", SLIP_PIN_PLACEHOLDER_RE),
        ):
            for match in pattern.finditer(text):
                findings.append(finding(
                    document, rule_id, "footnote", block, match.start(), match.end(),
                    "This citation contains a pending-pagination placeholder.",
                    "Classify as a pre-publication check when official pagination is not yet available; replace it when pagination issues.",
                    0.99, severity="warning", impact="low",
                ))
        for match in YEAR_SHAPED_US_PINCITE_RE.finditer(text):
            findings.append(finding(
                document, "citation.us_year_shaped_pincite", "footnote", block,
                match.start(1), match.end(1),
                "A four-digit year-shaped value appears in the U.S. Reports pincite position.",
                "Verify and replace the pincite; a year is not a plausible U.S. Reports page.",
                0.995, severity="error", impact="high",
            ))
        for match in CASE_CITE_RE.finditer(text):
            case_name = normalize_space(match.group("case"))
            case_name = re.sub(r"^(?:(?:But\s+)?(?:see|cf\.|accord)|compare)\s+", "", case_name, flags=re.I)
            normalized_case = re.sub(r"[^a-z0-9]+", " ", case_name.casefold()).strip()
            case_citations[normalized_case].append({
                "case_name": case_name,
                "volume": match.group("volume"),
                "page": match.group("page"),
                "year": match.group("year"),
                "pincite": match.group("pincite"),
                "block_id": block.get("block_id"),
                "excerpt": excerpt_around(text, match.start(), match.end()),
            })
        for opener, closer, label in (("(", ")", "parenthesis"), ("[", "]", "bracket"), ("{", "}", "brace")):
            if text.count(opener) != text.count(closer):
                findings.append(finding(document, f"delimiter.unbalanced_{label}", "delimiter", block, 0, len(text),
                                        f"This block has unbalanced {label} delimiters.",
                                        "Check whether a delimiter is missing or intentionally continues into another block.",
                                        0.74, detection="heuristic"))
        stripped = text.rstrip()
        omission = re.search(r"\b(a|an|the|to|of|and|or|but)\s*[.!?]$", stripped, flags=re.I)
        if omission:
            findings.append(finding(document, "text.dangling_function_word", "possible_omission", block,
                                    omission.start(), omission.end(), "The sentence ends with a function word, suggesting omitted text.",
                                    "Review the full sentence for text lost during editing.", 0.86, impact="high", detection="heuristic"))
        curly_open = text.count("“")
        curly_close = text.count("”")
        if curly_open != curly_close and block.get("kind") not in {"block_quote"}:
            findings.append(finding(document, "delimiter.unbalanced_curly_quote", "delimiter", block, 0, len(text),
                                    "Opening and closing curly quotation marks are unbalanced in this block.",
                                    "Check quote boundaries; a quotation may intentionally span paragraphs.", 0.68,
                                    detection="heuristic"))

        if block.get("story") == "footnote" and stripped and stripped[-1] not in ".!?…":
            findings.append(finding(
                document, "footnote.missing_terminal_punctuation", "footnote", block,
                max(0, len(stripped) - min(24, len(stripped))), len(stripped),
                "The footnote does not end with terminal punctuation.",
                "Add the appropriate terminal punctuation unless the note intentionally continues elsewhere.",
                0.96, severity="error", impact="low", detection="exact",
            ))

        for match in re.finditer(r"\bthat\s+The\b", text):
            findings.append(finding(
                document, "text.authorial_capitalized_article", "typo", block,
                match.start() + len("that "), match.end(),
                "The article 'The' is capitalized in sentence-internal authorial prose after 'that'.",
                "Change 'The' to 'the' unless it begins a supplied quotation or formal title.",
                0.96, severity="error", impact="low",
            ))

        for pattern in DEFINED_TERM_PATTERNS:
            for match in pattern.finditer(text):
                term = normalize_space(match.group(1))
                definitions.append({
                    "term": term,
                    "block_id": block.get("block_id"),
                    "char_start": match.start(1),
                    "char_end": match.end(1),
                    "excerpt": excerpt_around(text, match.start(1), match.end(1)),
                })

    for copies in duplicate_text.values():
        if len(copies) < 2:
            continue
        first = copies[0]
        for later in copies[1:]:
            findings.append(finding(document, "text.duplicate_block", "duplication", later, 0, len(str(later.get("text", ""))),
                                    f"This block duplicates {first.get('block_id')} exactly after whitespace normalization.",
                                    "Confirm whether the later block was pasted accidentally.", 0.99, severity="error", impact="high"))

    case_citation_variants = []
    for normalized_case, occurrences in case_citations.items():
        core_variants = {
            (item["volume"], item["page"], item["year"])
            for item in occurrences
        }
        if len(occurrences) >= 2 and len(core_variants) > 1:
            case_citation_variants.append({
                "normalized_case": normalized_case,
                "variants": [
                    {"volume": volume, "page": page, "year": year}
                    for volume, page, year in sorted(core_variants)
                ],
                "occurrences": occurrences,
            })
    long_duplicate_spans = repeated_long_spans(blocks)
    serial_comma_candidates = serial_comma_inventory(blocks)

    # Internal references.
    block_order = {str(block.get("block_id")): index for index, block in enumerate(all_blocks, 1)}
    for block in all_blocks:
        text = str(block.get("text", ""))
        for match in XREF_RE.finditer(text):
            raw_kind, label_group = match.groups()
            kind = canonical_xref_kind(raw_kind)
            label_offset = match.start(2)
            for label_match in XREF_LABEL_RE.finditer(label_group):
                label = label_match.group(0)
                if kind == "Section" and label.isdigit() and len(label) >= 3:
                    continue
                start = label_offset + label_match.start()
                end = label_offset + label_match.end()
                key = target_key(kind, label)
                refs = targets.get(key, [])
                item = {
                    "block_id": block.get("block_id"), "kind": kind, "label": label,
                    "char_start": start, "char_end": end,
                    "excerpt": excerpt_around(text, start, end), "targets": refs,
                    "source_text": match.group(0),
                }
                crossrefs.append(item)
                if not refs:
                    findings.append(finding(
                        document, "xref.missing_target", "xref", block, start, end,
                        f"No internal target was indexed for {kind} {label}.",
                        "Confirm the intended internal reference or create the missing target.", 0.98,
                        severity="error", impact="high",
                    ))
        for match in NOTE_XREF_RE.finditer(text):
            direction, number = match.groups()
            raw_target = display_to_raw.get(number)
            refs = [f"FN{raw_target}"] if raw_target is not None else []
            crossrefs.append({"block_id": block.get("block_id"), "kind": "note", "label": number,
                              "direction": direction.lower(), "char_start": match.start(), "char_end": match.end(),
                              "excerpt": excerpt_around(text, match.start(), match.end()), "targets": refs})
            if raw_target is None:
                findings.append(finding(document, "xref.missing_note", "xref", block, match.start(), match.end(),
                                        f"Referenced note {number} was not extracted.", "Confirm the note number.", 0.99,
                                        severity="error", impact="high"))
            elif block.get("story") == "footnote":
                current = raw_to_display.get(str(block.get("note_id")))
                target = int(number)
                if current is None:
                    continue
                wrong = (direction.lower() == "supra" and target >= current) or (direction.lower() == "infra" and target <= current)
                if wrong:
                    findings.append(finding(document, "xref.note_direction", "xref", block, match.start(), match.end(),
                                            f"“{direction} note {number}” points in the opposite direction.",
                                            "Confirm whether supra/infra or the note number should change.", 0.98,
                                            severity="error", impact="high"))

    # Duplicate targets and defined-term variants.
    for key, block_ids in targets.items():
        if len(block_ids) > 1 and not key.startswith("bookmark:"):
            for block_id in block_ids[1:]:
                block = next(item for item in blocks if item.get("block_id") == block_id)
                findings.append(finding(document, "structure.duplicate_label", "numbering", block, 0, min(len(str(block.get("text", ""))), 40),
                                        f"The indexed label {key} appears more than once.",
                                        "Confirm whether one heading or caption is misnumbered.", 0.96, severity="error", impact="high"))

    term_variants: list[dict] = []
    for definition in definitions:
        term = str(definition["term"])
        occurrences = []
        for block in all_blocks:
            text = str(block.get("text", ""))
            for match in re.finditer(re.escape(term), text, flags=re.I):
                occurrences.append({"variant": match.group(0), "block_id": block.get("block_id"),
                                    "excerpt": excerpt_around(text, match.start(), match.end())})
        variants = sorted({item["variant"] for item in occurrences})
        if len(variants) > 1:
            term_variants.append({"term": term, "variants": variants, "occurrences": occurrences})

    # Hyphenation variants are candidate-level consistency signals.
    words: dict[str, list[dict]] = defaultdict(list)
    for block in all_blocks:
        text = str(block.get("text", ""))
        for match in re.finditer(r"\b[A-Za-z]{3,}(?:-[A-Za-z]{2,})+\b|\b[A-Za-z]{5,}\b", text):
            form = match.group(0)
            words[form.replace("-", "").casefold()].append({
                "variant": form, "block_id": block.get("block_id"),
                "excerpt": excerpt_around(text, match.start(), match.end()),
            })
    hyphen_variants = []
    for key, occurrences in words.items():
        variants = sorted({item["variant"] for item in occurrences})
        if any("-" in value for value in variants) and any("-" not in value for value in variants):
            hyphen_variants.append({"normalized": key, "variants": variants, "occurrences": occurrences})

    # Compare open and hyphenated multiword compounds (for example,
    # "private law" and "private-law"). The ordinary token inventory above
    # cannot see this class because the open form is two tokens.
    hyphenated_compounds: dict[str, dict] = {}
    for block in all_blocks:
        text = str(block.get("text", ""))
        for match in re.finditer(r"\b([A-Za-z]{3,})-([A-Za-z]{2,})\b", text):
            left, right = match.group(1), match.group(2)
            normalized = f"{left.casefold()} {right.casefold()}"
            item = hyphenated_compounds.setdefault(
                normalized,
                {"normalized": normalized, "open": [], "hyphenated": []},
            )
            item["hyphenated"].append({
                "variant": match.group(0), "block_id": block.get("block_id"),
                "excerpt": excerpt_around(text, match.start(), match.end()),
            })
    for normalized, item in hyphenated_compounds.items():
        open_expression = re.escape(normalized).replace(r"\ ", r"\s+")
        open_pattern = re.compile(rf"\b{open_expression}\b", re.I)
        for block in all_blocks:
            text = str(block.get("text", ""))
            for match in open_pattern.finditer(text):
                item["open"].append({
                    "variant": match.group(0), "block_id": block.get("block_id"),
                    "excerpt": excerpt_around(text, match.start(), match.end()),
                })
    open_hyphen_variants = []
    for item in hyphenated_compounds.values():
        if item["open"] and item["hyphenated"] and len(item["open"]) + len(item["hyphenated"]) >= 3:
            open_hyphen_variants.append({
                "kind": "open_hyphenated",
                "normalized": item["normalized"],
                "counts": {"open": len(item["open"]), "hyphenated": len(item["hyphenated"])},
                "occurrences": item["open"][:12] + item["hyphenated"][:12],
            })

    # Broader lexical and semantic-consistency signals for the dedicated consistency lane.
    word_occurrences: dict[str, list[dict]] = defaultdict(list)
    bigram_occurrences: dict[str, list[dict]] = defaultdict(list)
    trigram_occurrences: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    name_pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)
    semantic_residue: list[dict] = []
    residue_stop = {
        "about", "after", "again", "because", "before", "being", "could", "first", "other",
        "should", "their", "there", "these", "those", "through", "under", "which", "while", "would",
    }
    for block in all_blocks:
        if not block.get("reviewable", True):
            continue
        text = str(block.get("text", ""))
        tokens = list(re.finditer(r"\b[A-Za-z][A-Za-z’'-]*\b", text))
        lowered = [match.group(0).casefold() for match in tokens]
        for match, form in zip(tokens, lowered):
            if len(form) >= 3:
                word_occurrences[form].append({
                    "block_id": block.get("block_id"), "char_start": match.start(), "char_end": match.end(),
                    "excerpt": excerpt_around(text, match.start(), match.end()),
                })
        for index in range(len(tokens) - 1):
            fused = lowered[index] + lowered[index + 1]
            if len(lowered[index]) < 3 or len(lowered[index + 1]) < 3:
                continue
            bigram_occurrences[fused].append({
                "variant": f"{tokens[index].group(0)} {tokens[index + 1].group(0)}",
                "block_id": block.get("block_id"), "char_start": tokens[index].start(),
                "char_end": tokens[index + 1].end(),
                "excerpt": excerpt_around(text, tokens[index].start(), tokens[index + 1].end()),
            })
        for index in range(len(tokens) - 2):
            trigram = tuple(lowered[index:index + 3])
            if all(len(value) >= 3 for value in trigram):
                trigram_occurrences[trigram].append({
                    "variant": " ".join(match.group(0) for match in tokens[index:index + 3]),
                    "block_id": block.get("block_id"), "char_start": tokens[index].start(),
                    "char_end": tokens[index + 2].end(),
                    "excerpt": excerpt_around(text, tokens[index].start(), tokens[index + 2].end()),
                })
        for match in re.finditer(r"\b([A-Z][a-z]{2,})\s+(?:and|&)\s+([A-Z][a-z]{2,})\b", text):
            pair = (match.group(1), match.group(2))
            name_pairs[pair].append({
                "variant": match.group(0), "block_id": block.get("block_id"),
                "char_start": match.start(), "char_end": match.end(),
                "excerpt": excerpt_around(text, match.start(), match.end()),
            })
        positions: dict[str, list[int]] = defaultdict(list)
        for index, form in enumerate(lowered):
            if len(form) >= 5 and form not in residue_stop:
                positions[form].append(index)
        for form, indexes in positions.items():
            for left, right in zip(indexes, indexes[1:]):
                between = text[tokens[left].end():tokens[right].start()]
                if 3 <= right - left <= 12 and not re.search(r"[.!?;:]", between):
                    semantic_residue.append({
                        "kind": "nonadjacent_repetition", "token": form,
                        "block_id": block.get("block_id"),
                        "char_start": tokens[left].start(), "char_end": tokens[right].end(),
                        "excerpt": excerpt_around(text, tokens[left].start(), tokens[right].end()),
                    })
        temporal = list(re.finditer(r"\b(?:today|now|currently|presently)\b", text, re.I))
        for left, right in zip(temporal, temporal[1:]):
            if right.start() - left.end() <= 30:
                semantic_residue.append({
                    "kind": "nearby_temporal_redundancy", "block_id": block.get("block_id"),
                    "char_start": left.start(), "char_end": right.end(),
                    "excerpt": excerpt_around(text, left.start(), right.end()),
                })

    lexical_variants: list[dict] = []
    for fused, open_occurrences in bigram_occurrences.items():
        fused_occurrences = word_occurrences.get(fused, [])
        if fused_occurrences and len(open_occurrences) + len(fused_occurrences) >= 3:
            lexical_variants.append({
                "kind": "open_fused", "normalized": fused,
                "variants": sorted({item.get("variant", fused) for item in open_occurrences} | {fused}),
                "counts": {"open": len(open_occurrences), "fused": len(fused_occurrences)},
                "occurrences": open_occurrences[:5] + [dict(item, variant=fused) for item in fused_occurrences[:5]],
            })

    spelling_candidates: dict[str, set[str]] = defaultdict(set)
    for form in word_occurrences:
        if len(form) < 6 or not form.isalpha():
            continue
        spelling_candidates[form].add(form)
        for index in range(len(form)):
            spelling_candidates[form[:index] + form[index + 1:]].add(form)
    seen_pairs: set[tuple[str, str]] = set()
    for forms in spelling_candidates.values():
        for left in sorted(forms):
            for right in sorted(forms):
                pair = tuple(sorted((left, right)))
                if left == right or pair in seen_pairs or not one_edit_apart(left, right):
                    continue
                if left[:3] != right[:3]:
                    continue
                seen_pairs.add(pair)
                left_count, right_count = len(word_occurrences[left]), len(word_occurrences[right])
                combined = left_count + right_count
                directional_pair = frozenset((left, right)) in DIRECTIONAL_STYLE_PAIRS
                if len(left) != len(right) and not directional_pair:
                    continue
                if (combined < 3 and not directional_pair) or min(left_count, right_count) > 3 or max(left_count, right_count) > 20:
                    continue
                lexical_variants.append({
                    "kind": "near_spelling", "variants": [left, right],
                    "counts": {left: left_count, right: right_count},
                    "occurrences": [dict(item, variant=left) for item in word_occurrences[left][:5]]
                    + [dict(item, variant=right) for item in word_occurrences[right][:5]],
                })

    permutation_groups: dict[tuple[str, str, str], list[tuple[tuple[str, str, str], list[dict]]]] = defaultdict(list)
    for trigram, occurrences in trigram_occurrences.items():
        permutation_groups[tuple(sorted(trigram))].append((trigram, occurrences))
    term_permutations = []
    for grouped in permutation_groups.values():
        if len(grouped) < 2 or max(len(occurrences) for _, occurrences in grouped) < 4:
            continue
        term_permutations.append({
            "variants": {" ".join(trigram): len(occurrences) for trigram, occurrences in grouped},
            "occurrences": [item for _, occurrences in grouped for item in occurrences[:5]],
        })

    name_order_variants = []
    for pair, occurrences in name_pairs.items():
        reverse = (pair[1], pair[0])
        if pair < reverse and reverse in name_pairs:
            name_order_variants.append({
                "variants": {f"{pair[0]} and {pair[1]}": len(occurrences),
                             f"{reverse[0]} and {reverse[1]}": len(name_pairs[reverse])},
                "occurrences": occurrences[:5] + name_pairs[reverse][:5],
            })

    note_by_raw = {str(note.get("note_id")): note for note in notes}
    body_note_numeric_links = []
    century_note_links = []
    trigger_re = re.compile(
        r"\b(?:published|adopted|enacted|issued|decided|ratified|revised)\b[^.!?]{0,40}\b((?:17|18|19|20)\d{2})\b",
        re.I,
    )
    for block in blocks:
        text = str(block.get("text", ""))
        if not block.get("footnote_ids"):
            continue
        linked_notes = [note_by_raw[value] for value in map(str, block.get("footnote_ids", [])) if value in note_by_raw]
        note_years = sorted({year for note in linked_notes for year in re.findall(r"\b(?:17|18|19|20)\d{2}\b", str(note.get("text", "")))})
        body_matches = list(trigger_re.finditer(text))
        for match in body_matches:
            if note_years and match.group(1) not in note_years:
                body_note_numeric_links.append({
                    "block_id": block.get("block_id"), "body_excerpt": excerpt_around(text, match.start(), match.end()),
                    "body_value": match.group(1), "linked_notes": [
                        {"block_id": note.get("block_id"), "text": note.get("text")} for note in linked_notes
                    ],
                    "note_values": note_years,
                })
        century_matches = list(CENTURY_RE.finditer(text))
        if not century_matches or not linked_notes:
            continue
        cited_centuries = sorted({(int(year) - 1) // 100 + 1 for year in note_years})
        for match in century_matches:
            ordinal = match.group("ordinal").casefold()
            body_century = CENTURY_NUMBERS[ordinal]
            if cited_centuries and body_century not in cited_centuries:
                century_note_links.append({
                    "block_id": block.get("block_id"),
                    "body_excerpt": excerpt_around(text, match.start(), match.end()),
                    "body_century": body_century,
                    "linked_note_centuries": cited_centuries,
                    "linked_notes": [
                        {"block_id": note.get("block_id"), "text": note.get("text")} for note in linked_notes
                    ],
                })

    symbols = {
        "schema_version": 1,
        "source_sha256": document.get("input_sha256"),
        "headings": headings,
        "captions": captions,
        "notes": [
            {
                "raw_note_id": note.get("note_id"),
                "display_number": raw_to_display.get(str(note.get("note_id"))),
                "block_id": note.get("block_id"),
                "order": note.get("order"),
            }
            for note in notes
        ],
        "display_note_to_block": {
            display: f"FN{raw_id}" for display, raw_id in display_to_raw.items()
        },
        "bookmarks": document.get("bookmarks", []),
        "fields": document.get("fields", []),
        "cross_references": crossrefs,
        "defined_terms": definitions,
        "defined_term_variants": term_variants,
        "hyphenation_variants": hyphen_variants,
        "open_hyphen_variants": open_hyphen_variants,
        "lexical_variants": lexical_variants,
        "term_permutations": term_permutations,
        "name_order_variants": name_order_variants,
        "semantic_residue_candidates": semantic_residue,
        "body_note_numeric_links": body_note_numeric_links,
        "century_note_links": century_note_links,
        "case_citation_variants": case_citation_variants,
        "long_duplicate_spans": long_duplicate_spans,
        "serial_comma_candidates": serial_comma_candidates,
        "toc_entries": toc_entries,
        "target_index": dict(sorted(targets.items())),
        "block_order": block_order,
    }
    findings.sort(key=lambda row: (block_order.get(str(row.get("location", {}).get("block_id")), 10**9), int(row.get("location", {}).get("char_start", 0)), row["finding_id"]))
    write_json(args.symbols, symbols)
    write_jsonl(args.findings, findings)
    print(f"wrote {len(findings)} static candidates and {len(crossrefs)} cross-reference records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
