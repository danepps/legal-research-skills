"""Raw Word symbol-spacing inventory; kept identical in the two Codex skills.

Ported from legal-research/citeform.py. Do not use normalized extraction text.
The skills install independently, so this module has no sibling-skill imports.
"""
import re

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SKIP_SUBTREES = (W + "del", W + "moveFrom")
ISSUE = "space after § and ¶"
TEXT_LIMITATION = "Space after § and ¶ was not checked: this check requires a .docx file's raw Word characters."


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


SYMBOL_SPACE = re.compile(r"([§¶]+)(\s+)(?=\S)")
_NONBREAKING = frozenset("\u00a0\u202f\u2007")   # no-break, narrow no-break, figure
_NOTE_CALL = "\x00"                                # a note reference in the stream


def _symbol_stream(el, state, out):
    """Append (char-run, in_field) pairs for one element. `state` carries the open
    complex fields across paragraphs: a Zotero bibliography spans several."""
    for child in el:
        tag = child.tag
        if tag in _SKIP_SUBTREES:
            continue
        if tag == W + "fldSimple":
            state["simple"] += 1
            _symbol_stream(child, state, out)
            state["simple"] -= 1
            continue
        if tag == W + "fldChar":
            kind = child.get(W + "fldCharType")
            if kind == "begin":
                state["stack"].append(False)         # False until the result starts
            elif kind == "separate" and state["stack"]:
                state["stack"][-1] = True
            elif kind == "end" and state["stack"]:
                state["stack"].pop()
            continue
        in_field = bool(state["simple"] or any(state["stack"]))
        if tag == W + "t":
            out.append((child.text or "", in_field))
        elif tag in (W + "tab", W + "br", W + "cr"):
            out.append((" ", in_field))
        elif tag == W + "noBreakHyphen":
            out.append(("-", in_field))
        elif tag in (W + "footnoteReference", W + "endnoteReference"):
            out.append((_NOTE_CALL, in_field))
        else:
            _symbol_stream(child, state, out)


def symbol_space_state():
    return {"stack": [], "simple": 0}


def symbol_space_hits(paragraphs, state=None):
    """Every § or ¶ (or run of them) that is followed by white space and then more
    text, in document order. `paragraphs` are the w:p elements of ONE passage (a
    body paragraph, or all the paragraphs of a note). Each hit is
      {"symbol", "nonbreaking": bool, "in_field": bool, "context"}
    where nonbreaking is True only when the whole gap is non-breaking characters,
    in_field means the text is a Word field's displayed result (a Zotero citation,
    a cross-reference, a table of contents) and context is a short excerpt with
    white space collapsed, as it appears in the plain-text views."""
    state = state if state is not None else symbol_space_state()
    pieces = []
    for i, p in enumerate(paragraphs):
        if i:
            pieces.append((" ", False))
        _symbol_stream(p, state, pieces)
    raw = "".join(t for t, _ in pieces)
    flags = []
    for t, f in pieces:
        flags.extend([f] * len(t))
    hits = []
    for m in SYMBOL_SPACE.finditer(raw):
        gap = m.group(2)
        s = max(raw.rfind(_NOTE_CALL, 0, m.start()) + 1, m.start() - 30)
        if s and raw[s - 1] != _NOTE_CALL:           # start the excerpt on a whole word
            while s < m.start() and not raw[s - 1].isspace():
                s += 1
        e = m.end()
        while e < len(raw) and not raw[e].isspace() and raw[e] != _NOTE_CALL and e - m.end() < 24:
            e += 1
        hits.append({"symbol": m.group(1),
                     "nonbreaking": all(c in _NONBREAKING for c in gap),
                     "in_field": any(flags[m.start(1):m.end(2)]),
                     # a note's text opens with ". " after its number: not part of the excerpt
                     "context": re.sub(r"^[.\s]+", "", _clean(raw[s:e]))})
    return hits


def symbol_space_convention(located, examples=3, listed=20):
    """Roll the hits up for a report. `located` is [(label, hit)], label being a
    reader-facing place ("note 12") or "" for body text. Returns (summary, row):
    the summary always, the convention row only when some symbol is followed by an
    ordinary space. `examples` in the summary are the first `listed` outside
    fields (the ones an author can change while the citations are still linked);
    the list is capped because the session retypes this block into workflow args."""
    located = list(located)
    bad = [(lab, h) for lab, h in located if not h["nonbreaking"]]
    loose = [(lab, h) for lab, h in bad if not h["in_field"]]
    summary = {"total": len(located),
               "nonbreaking": len(located) - len(bad),
               "ordinary": len(loose),
               "ordinary_in_fields": len(bad) - len(loose),
               "examples": [{"location": lab, "find": h["context"]}
                            for lab, h in loose[:listed]]}
    if not bad:
        return summary, None
    shown = (loose or bad)[:examples]
    eg = "; ".join("%s`%s`" % ((lab + " ") if lab else "", h["context"]) for lab, h in shown)
    good = len(located) - len(bad)
    parts = []
    if loose:
        parts.append("%d followed by an ordinary space, so a line can end on the symbol"
                     % len(loose))
    if len(bad) > len(loose):
        parts.append("%d%s inside Zotero citations or other Word fields"
                     % (len(bad) - len(loose), " more" if loose else " with an ordinary space,"))
    # The table's first column is the draft's commoner form, whichever that is.
    if len(bad) >= good:
        dominant = "ordinary space (%d of %d)" % (len(bad), len(located))
        parts.insert(0, "non-breaking space after %d" % good)
    else:
        dominant = "non-breaking space (%d of %d)" % (good, len(located))
    rec = ("Put a non-breaking space after every § and ¶. In Word that is one Replace All "
           "per symbol: find the symbol followed by a space, replace with the symbol "
           "followed by ^s (Word's code for a non-breaking space).")
    if len(bad) > len(loose):
        rec += (" Replace All also changes the text shown inside Zotero citations, where "
                "a typed fix is wiped on refresh or flagged as a hand-modified citation, "
                "so in a draft that is still linked to Zotero do it after the fields are "
                "unlinked (the editors' copy).")
    row = {"issue": "space after § and ¶",
           "dominant": dominant,
           "minority": "%s (for example: %s)" % ("; ".join(parts), eg),
           "recommendation": rec}
    return summary, row


def visible_nodes(element):
    if element is None or element.tag in _SKIP_SUBTREES:
        return
    yield element
    for child in element:
        yield from visible_nodes(child)


def footnote_labels(document, settings=None):
    """Reader-facing labels for the side inventory only; never change block text."""
    number = 1
    for root in (settings, document):
        if root is not None:
            for props in root.iter(W + "footnotePr"):
                start = props.find(W + "numStart")
                if start is not None:
                    number = int(start.get(W + "val", "1"))
    labels = {}
    nodes = list(visible_nodes(document))
    for index, node in enumerate(nodes):
        if node.tag != W + "footnoteReference" or node.get(W + "id") in labels:
            continue
        if node.get(W + "customMarkFollows", "").lower() in {"1", "true", "on"}:
            following = next((n for n in nodes[index + 1:] if n.tag in {W + "t", W + "p", W + "footnoteReference"}), None)
            mark = (following.text or "").strip().split() if following is not None and following.tag == W + "t" else []
            label = "note " + (mark[0] if mark else "with custom mark")
        else:
            label = "note %s" % number
            number += 1
        labels[node.get(W + "id")] = label
    return labels


def collect_symbol_spacing(document, footnotes=None, labels=None, endnotes=None, end_labels=None):
    """Body/table paragraphs and notes; field state is separate for each XML part.

    A body paragraph is one passage; all paragraphs of a note are one passage.
    Headers/footers are outside the reference implementation's coverage.
    """
    located = []
    state = symbol_space_state()
    for paragraph in visible_nodes(document):
        if paragraph.tag == W + "p":
            located.extend(("", hit) for hit in symbol_space_hits([paragraph], state))
    for root, tag, places in ((footnotes, "footnote", labels or {}),
                              (endnotes, "endnote", end_labels or {})):
        state = symbol_space_state()
        for note in root if root is not None else []:
            if note.tag != W + tag or note.get(W + "type") in {"separator", "continuationSeparator", "continuationNotice"}:
                continue
            raw_id = note.get(W + "id", "")
            if raw_id in {"-1", "0"}:
                continue
            if tag == "endnote" and raw_id not in places:
                continue
            place = places.get(raw_id, "unreferenced " + tag)
            paragraphs = [p for p in visible_nodes(note) if p.tag == W + "p"]
            located.extend((place, hit) for hit in symbol_space_hits(paragraphs, state))
    summary, row = symbol_space_convention(located)
    summary["status"] = "checked"
    summary["scope"] = "body, tables, footnotes" + (", referenced endnotes" if endnotes is not None else "")
    data = {"symbol_spacing": summary, "conventions": [row] if row else []}
    if row:
        row["report_markdown"] = symbol_spacing_report(data)
    return data


def skipped_symbol_spacing():
    return {"symbol_spacing": {"status": "not_applicable", "limitation": TEXT_LIMITATION}, "conventions": []}


def symbol_spacing_report(data):
    summary = data.get("symbol_spacing", {})
    if summary.get("status") != "checked" or not (summary.get("ordinary", 0) + summary.get("ordinary_in_fields", 0)):
        return ""
    row = next(row for row in data["conventions"] if row.get("issue") == ISSUE)
    return ("**Space after § and ¶ (typography, not a Bluebook rule).** "
            "Total symbol runs: {total}; non-breaking: {nonbreaking}; "
            "ordinary outside fields: {ordinary}; ordinary inside fields: {ordinary_in_fields}. "
            "{detail}. {recommendation}").format(
                detail=row["minority"][:1].upper() + row["minority"][1:], **summary, **row)


def validate_symbol_spacing(data, report=None):
    """Accept legacy inventories; gate one deterministic note without model audits."""
    if "symbol_spacing" not in data:
        return []
    summary = data["symbol_spacing"]
    if not isinstance(summary, dict):
        return ["symbol_spacing must be an object"]
    rows = [row for row in data.get("conventions", []) if isinstance(row, dict) and row.get("issue") == ISSUE]
    if summary.get("status") == "not_applicable":
        return [] if summary.get("limitation") == TEXT_LIMITATION and not rows else ["invalid skipped symbol_spacing check"]
    keys = ("total", "nonbreaking", "ordinary", "ordinary_in_fields")
    if summary.get("status") != "checked" or any(type(summary.get(key)) is not int or summary[key] < 0 for key in keys):
        return ["invalid symbol_spacing counts or status"]
    if summary["total"] != sum(summary[key] for key in keys[1:]):
        return ["symbol_spacing counts do not reconcile"]
    expected = int(bool(summary["ordinary"] + summary["ordinary_in_fields"]))
    if len(rows) != expected:
        return ["symbol_spacing requires exactly one convention when ordinary gaps exist, otherwise none"]
    if not expected:
        return []
    try:
        note = symbol_spacing_report(data)
    except (KeyError, TypeError, ValueError):
        return ["invalid symbol_spacing convention"]
    if rows[0].get("report_markdown") != note:
        return ["symbol_spacing report_markdown is stale"]
    if report is not None and _clean(report).count(_clean(note)) != 1:
        return ["report.md must include the symbol_spacing report_markdown exactly once"]
    return []
