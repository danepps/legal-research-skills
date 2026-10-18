#!/usr/bin/env python3
"""Extraction + deterministic-lint layer for the /proofread skill.

Parses an article draft and emits everything the proofreading pipeline needs:

  * body paragraphs with stable ids, heading detection (Word style first,
    numbered-label pattern fallback), and footnote positions rendered inline
    as [FN#n] using the RENDERED footnote number (id->number mapping built
    from body order, same technique as cite-check's extract_cites.py);
  * footnotes keyed by rendered number;
  * proof CHUNKS — self-contained JSON files (paragraphs + the footnotes they
    reference) sized for one proofreading agent each;
  * fulltext.txt — the whole draft flattened, for the whole-document
    consistency agents;
  * deterministic LINT findings (doubled words, punctuation-before-footnote-
    marker, mixed straight/curly quotes, unbalanced quotes/parens, high-
    confidence typo list, note cross-reference bound/direction violations,
    heading-sequence gaps and lone subdivisions);
  * CONSISTENCY DATA for the model agents to adjudicate (hyphenation variant
    counts, British/American spelling counts, defined terms and their usage,
    Part/Section cross-references + the heading list, serial-comma and
    em-dash and double-space stats);
  * a FORMATTING layer (.docx only, added 2026-08-10): run properties w:i /
    w:smallCaps / w:caps resolved through character styles AND paragraph styles,
    yielding a tagged parallel text (<i>…</i>, <sc>…</sc>, <caps>…</caps>), a
    typeface lint (signals/Id./supra not italicized, "note N" wrongly
    italicized, case-name italicization against Bluebook R. 2.1(a) and against
    the draft's own dominant practice), and an all-caps flag on headings so no
    downstream stage second-guesses the word-level capitalization of a header
    that Word renders in caps.

The chunk payloads the per-chunk proofers see remain PLAIN TEXT — typeface is
adjudicated by its own whole-document stage against fulltext_fmt.txt. Indentation
and block-quote layout are still lost, so no check may depend on them. Stdlib
only.

Usage:
    python3 extract_proof.py <draft.docx | dir | draft.md> <outdir> [--chunk-words N]

Writes <outdir>/proof.json, <outdir>/fulltext.txt, <outdir>/chunks/chunk-NN.json
and prints a summary JSON to stdout.
"""
import hashlib
import json
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

# Shared citation-FORM library (typeface + short forms + the .docx run-formatting
# reader) lives with the other cross-skill machinery in legal-research/, so
# /cite-check runs the identical checks. Sibling skill directory first (the plugin
# layout), then a plain ~/.claude/skills install.
for _p in (os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "legal-research"),
           os.path.expanduser("~/.claude/skills/legal-research")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
from citeform import (                                       # noqa: E402
    W, FN_PLACEHOLDER, _clean, _ctx, _load_xml,
    parse_styles, runs_spans, clean_spans, shift_spans, render_marked,
    prop_ratio, CAPTION_CITE, _caption_key,
    short_form_lint, typeface_lint, case_name_typeface,
)

# Per-agent passage size. Proofreading recall degrades as the passage grows —
# a proofer skims what it should crawl. ~1800 words (body + attached footnotes)
# keeps each agent at a genuinely careful read; deep mode passes 1200.
DEFAULT_CHUNK_WORDS = 1800


def _para_style(p):
    ppr = p.find(W + "pPr")
    if ppr is None:
        return ""
    st = ppr.find(W + "pStyle")
    return st.get(W + "val") if st is not None else ""


# Heading label pattern fallback (used only when the document has NO HeadingN
# styles): "I.", "A.", "1." leading a short line. Word's own Heading styles are
# authoritative when present — their labels come from auto-numbering, so we
# compute them from order instead of parsing text.
HEAD_PAT = re.compile(r"^(?:[IVXLC]+|[A-Z]|\d+)\s*\.\s+\S")
TITLE_WORDS = {"introduction", "conclusion", "abstract", "appendix"}
# Unnumbered level-1 heading styles seen in the wild.
UNNUMBERED_H1 = {"introconclusion", "heading1nonumbering"}


def style_heading_level(style):
    m = re.match(r"heading\s?(\d)", (style or "").lower())
    if m:
        return int(m.group(1))
    if (style or "").lower() in UNNUMBERED_H1:
        return 1
    return None


def pattern_heading(text, last_l1, last_l2):
    """(level, val, label) or None — for documents without Heading styles.
    Single letters in IVXLC are ambiguous (roman I vs letter I); disambiguate
    by whichever reading CONTINUES the running sequence at its level."""
    words = text.split()
    if len(words) <= 4 and text.rstrip(".").lower() in TITLE_WORDS:
        return (1, None, None)
    if len(words) > 14 or not HEAD_PAT.match(text):
        return None
    lab = words[0].rstrip(".")
    if re.fullmatch(r"\d+", lab):
        return (3, int(lab), lab)
    is_roman = bool(re.fullmatch(r"[IVXLC]+", lab))
    is_letter = len(lab) == 1 and lab.isalpha() and lab.isupper()
    if is_roman and is_letter:  # I, V, X, L, C
        rv, lv = roman_val(lab), ord(lab) - 64
        if rv == last_l1 + 1:
            return (1, rv, lab)
        if lv == last_l2 + 1:
            return (2, lv, lab)
        return (1, rv, lab) if lab == "I" else (2, lv, lab)
    if is_roman:
        return (1, roman_val(lab), lab)
    if is_letter:
        return (2, ord(lab) - 64, lab)
    return None


ROMAN_NUM = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
             "XI", "XII", "XIII", "XIV", "XV"]


def to_roman(n):
    return ROMAN_NUM[n] if 0 < n < len(ROMAN_NUM) else str(n)


def parse_docx(src):
    if src.lower().endswith(".docx"):
        zf = zipfile.ZipFile(src)
        fn_root = _load_xml(zf, "word/footnotes.xml")
        body_root = _load_xml(zf, "word/document.xml")
        styles_src = zf
    else:
        fn_root = _load_xml(src, "word/footnotes.xml")
        body_root = _load_xml(src, "word/document.xml")
        styles_src = src
    try:
        styles = parse_styles(_load_xml(styles_src, "word/styles.xml"))
    except (KeyError, OSError, ET.ParseError):
        styles = {}

    notes_by_id = {}
    for fn in fn_root.findall(W + "footnote"):
        if fn.get(W + "type") in ("separator", "continuationSeparator"):
            continue
        spans = []
        for i, p in enumerate(fn.findall(W + "p")):
            if i:
                spans.append((" ", frozenset()))
            spans += runs_spans(p, styles, _para_style(p))
        text, sp = clean_spans(spans)
        notes_by_id[fn.get(W + "id")] = {"text": text, "spans": sp}

    paras, order = [], []
    has_ins = has_del = False
    for p in body_root.iter(W + "p"):
        if p.find(".//" + W + "ins") is not None:
            has_ins = True
        if p.find(".//" + W + "del") is not None:
            has_del = True
        style = _para_style(p)
        t, sp = clean_spans(runs_spans(p, styles, style))
        for ref in p.iter(W + "footnoteReference"):
            order.append(ref.get(W + "id"))
        if t:
            paras.append({"text": t, "style": style, "spans": sp})
    return notes_by_id, paras, order, has_ins, has_del, True


# ---- markdown / plain-text fallback ------------------------------------------
MD_FN_DEF = re.compile(r"^\s*\[\^([0-9A-Za-z]+)\]:\s*(.*)$")
MD_FN_REF = re.compile(r"\[\^([0-9A-Za-z]+)\]")


def parse_markdown(path):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    defs, body_lines, cur = {}, [], None
    for ln in lines:
        m = MD_FN_DEF.match(ln)
        if m:
            cur = m.group(1)
            defs[cur] = m.group(2).strip()
        elif cur and (ln.startswith("    ") or ln.startswith("\t")):
            defs[cur] += " " + ln.strip()
        else:
            cur = None
            body_lines.append(ln.rstrip("\n"))
    body = "\n".join(body_lines)
    order = [m.group(1) for m in MD_FN_REF.finditer(body)]
    body = MD_FN_REF.sub(lambda m: "[[FN:%s]]" % m.group(1), body)
    paras = []
    for p in re.split(r"\n\s*\n", body):
        t = _clean(p)
        if not t:
            continue
        style = ""
        mh = re.match(r"^(#{1,4})\s+(.*)$", t)
        if mh:
            style = "Heading%d" % len(mh.group(1))
            t = mh.group(2)
        paras.append({"text": t, "style": style, "spans": []})
    # No formatting layer on the markdown path: `*emphasis*` markers are left in
    # the text verbatim (the author's Cmd+F string contains them), so typeface
    # checks are skipped rather than guessed at.
    notes = {k: {"text": _clean(v), "spans": []} for k, v in defs.items()}
    return notes, paras, order, False, False, False


def build_number_map(order):
    id2num, n = {}, 0
    for fid in order:
        if fid not in id2num:
            n += 1
            id2num[fid] = n
    return id2num


# ---- lint: deterministic near-certain checks ----------------------------------
DOUBLED = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.IGNORECASE)
DOUBLED_OK = {"had", "that", "is"}  # "had had", "that that" are grammatical
FN_BEFORE_PUNCT = re.compile(r"(\[FN#\d+\])\s*([.,;:])")
NO_SPACE_AFTER_COMMA = re.compile(r"[A-Za-z],[A-Za-z]")
SPACE_BEFORE_PUNCT = re.compile(r"[A-Za-z]\s+[,;]")
ET_AL = re.compile(r"\bet\.\s?al\b")
TYPO_PATTERNS = [
    (re.compile(r"\bpubic\b", re.IGNORECASE), 'probably "public"'),
    (re.compile(r"\buntied states\b", re.IGNORECASE), 'probably "United States"'),
    (re.compile(r"\bstatue of limitations\b", re.IGNORECASE), 'probably "statute of limitations"'),
    (re.compile(r"\btrail court\b", re.IGNORECASE), 'probably "trial court"'),
    (re.compile(r"\bcasual (?:connection|link|chain|relationship|nexus)\b", re.IGNORECASE),
     'probably "causal"'),
    (re.compile(r"\bin tact\b", re.IGNORECASE), 'probably "intact"'),
]


def lint_text(text, loc):
    """Run the per-passage lint rules over one rendered passage. `loc` is a
    dict like {"where":"body","para":12} or {"where":"footnote","note":88}."""
    out = []

    def add(rule, m, problem, fix, severity="error"):
        out.append({
            "rule": rule, "location": loc,
            "find": _ctx(text, m.start(), m.end()),
            "exact": m.group(0),
            "problem": problem, "fix": fix, "severity": severity,
        })

    for m in DOUBLED.finditer(text):
        if m.group(1).lower() in DOUBLED_OK:
            continue
        add("doubled-word", m, "repeated word: %r" % m.group(0),
            "delete one %r" % m.group(1), "likely")
    for m in FN_BEFORE_PUNCT.finditer(text):
        add("footnote-before-punctuation", m,
            "footnote call %s precedes the punctuation mark" % m.group(1),
            "move the footnote call after the %r" % m.group(2))
    for m in NO_SPACE_AFTER_COMMA.finditer(text):
        add("no-space-after-comma", m, "missing space after comma",
            "insert a space", "likely")
    for m in SPACE_BEFORE_PUNCT.finditer(text):
        add("space-before-punctuation", m,
            "stray space before %r" % m.group(0)[-1], "delete the space", "likely")
    for m in ET_AL.finditer(text):
        add("et-al", m, '"et." is wrong — "et" is a complete Latin word',
            'use "et al."')
    for pat, note in TYPO_PATTERNS:
        for m in pat.finditer(text):
            add("known-typo", m, "%r — %s" % (m.group(0), note),
                "fix the typo", "likely")
    # unfilled placeholder: a bare _ / __ where a number or reference belongs
    for m in re.finditer(r"(?<![\w])_{1,3}(?![\w])", text):
        add("placeholder", m,
            "unfilled placeholder ('%s') — a reference or page number was never supplied"
            % m.group(0), "fill in the intended reference", "error")
    # unbalanced curly quotes / parens within this passage
    if text.count("“") != text.count("”"):
        out.append({"rule": "unbalanced-quotes", "location": loc,
                    "find": _ctx(text, 0, min(len(text), 80)),
                    "exact": "", "severity": "likely",
                    "problem": "unbalanced curly quotation marks in this passage (%d open, %d close)"
                               % (text.count("“"), text.count("”")),
                    "fix": "find the unpaired mark"})
    if abs(text.count("(") - text.count(")")) > 0:
        out.append({"rule": "unbalanced-parens", "location": loc,
                    "find": _ctx(text, 0, min(len(text), 80)),
                    "exact": "", "severity": "likely",
                    "problem": "unbalanced parentheses in this passage (%d open, %d close)"
                               % (text.count("("), text.count(")")),
                    "fix": "find the unpaired parenthesis"})
    return out


# ---- cross-references ----------------------------------------------------------
NOTE_REF = re.compile(r"\b(supra|infra)\s+notes?\s+(\d+)(?:\s*[–—-]\s*(\d+))?",
                      re.IGNORECASE)
PART_REF = re.compile(
    r"\b(supra|infra)?\s*(Part|Section)s?\s+([IVXLC]+(?:\.[A-Z](?:\.\d+)?)?)\b")


def note_ref_findings(text, loc, current_note, footnote_count):
    """Bound/direction violations for 'supra/infra note N' — deterministic."""
    out = []
    for m in NOTE_REF.finditer(text):
        kind = m.group(1).lower()
        lo = int(m.group(2))
        hi = int(m.group(3)) if m.group(3) else lo
        problems = []
        if hi > footnote_count or lo < 1:
            problems.append("target note %d does not exist (draft has %d footnotes)"
                            % (max(lo, hi), footnote_count))
        if m.group(3) and lo >= hi:
            problems.append("range runs backwards")
        if current_note is not None:
            if kind == "supra" and lo >= current_note:
                problems.append("'supra' points forward (note %d, cited from note %d)"
                                % (lo, current_note))
            if kind == "infra" and hi <= current_note:
                problems.append("'infra' points backward (note %d, cited from note %d)"
                                % (hi, current_note))
        for p in problems:
            out.append({"rule": "note-cross-reference", "location": loc,
                        "find": _ctx(text, m.start(), m.end()),
                        "exact": m.group(0), "problem": p,
                        "fix": "re-check the note number (classic renumbering break)",
                        "severity": "error"})
    return out


def collect_part_refs(text, loc):
    out = []
    for m in PART_REF.finditer(text):
        out.append({"direction": (m.group(1) or "").lower() or None,
                    "label": m.group(3), "ref": _clean(m.group(0)),
                    "context": _ctx(text, m.start(), m.end()), "location": loc})
    return out


# ---- citation mechanics (footnote typography — NOT Bluebook substance) -----------
# Added 2026-07-14 after the Codex-memo comparison: mechanical typography inside
# citation strings (doubled periods, § spacing, signal commas, terminal
# punctuation, placeholders) is regexable and belongs to this skill's internal
# pass; signal ORDER, typefaces, and short-form correctness stay out of scope.
CITE_MECH_RULES = [
    (re.compile(r"\bId\.\."), "cite-id-doubled-period",
     '"Id.." has a doubled period', 'use "Id."', "likely"),
    (re.compile(r"§\s+§"), "cite-section-symbol",
     "doubled section symbol with a space (§ §)", "use §§ (or a single §)", "likely"),
    (re.compile(r"(?<!§)§(?=\d)"), "cite-section-spacing",
     "missing space between § and the section number", "§ N", "likely"),
    (re.compile(r"\bU\.\s+S\.(?=\s|\d)"), "cite-us-spacing",
     '"U. S." has an internal space (inconsistent with "U.S." elsewhere)',
     'use "U.S." (unless inside a quotation from an old reporter)', "likely"),
    (re.compile(r"\bSee e\.g\.,"), "cite-signal-comma",
     'signal missing the comma after "See"', 'use "See, e.g.,"', "likely"),
    (re.compile(r"\bBut see,\s+(?=[A-Z\d])"), "cite-signal-comma",
     '"But see" should not be followed by a comma', 'use "But see"', "likely"),
    (re.compile(r"\bsupra note\s+at\b"), "cite-supra-noref",
     '"supra note at" — the note number is missing', "supply the note number", "error"),
    (re.compile(r"\b[Ss]ee\s+also\s+generally\b"), "cite-signal-mix",
     '"see also generally" mixes two signals', 'use "see also" or "see generally"', "likely"),
    (re.compile(r"\((?:citing|quoting)\s+Id\."), "cite-id-capitalization",
     'capitalized "Id." mid-citation inside a parenthetical', 'use lowercase "id."', "likely"),
]


def cite_mechanics_lint(text, loc):
    out = []
    for pat, rule, problem, fix, sev in CITE_MECH_RULES:
        for m in pat.finditer(text):
            out.append({"rule": rule, "location": loc,
                        "find": _ctx(text, m.start(), m.end()),
                        "exact": m.group(0), "problem": problem,
                        "fix": fix, "severity": sev})
    return out


def terminal_punct_finding(text, loc):
    """A footnote should end with . ? or ! (a closing curly quote may follow)."""
    t = text.rstrip()
    while t and t[-1] in "”\"'’":
        t = t[:-1].rstrip()
    if t and t[-1] not in ".?!":
        return [{"rule": "cite-terminal-punct", "location": loc,
                 "find": "…" + text[-70:], "exact": t[-1],
                 "problem": "footnote does not end with terminal punctuation (ends %r)" % t[-12:],
                 "fix": "add the final period", "severity": "likely"}]
    return []


# ---- internal citation consistency (no external sources needed) ------------------
# Same-cite pincite arithmetic: "97 Harv. L. Rev. 1513, 517" — a pincite below
# the cite's own first page is impossible.
PIN_ARITH = re.compile(
    r"\b(\d{1,4})\s+((?:[A-Z][\w.'’&]*\.?\s+){1,6}?)(\d{2,5}),\s+(\d{1,5})\b")


def pincite_lint(text, loc):
    out = []
    for m in PIN_ARITH.finditer(text):
        reporter, first, pin = m.group(2), int(m.group(3)), int(m.group(4))
        if "." not in reporter:  # require a reporter/journal abbreviation
            continue
        # year-shaped pincite: "596 U.S. 845, 2017 (2022)" — a pin in the
        # calendar-year range sitting implausibly far past the first page is
        # almost always a pasted year, not a page (2026-07-14 Codex-2 lesson;
        # Stat. pages legitimately run huge, so skip Statutes at Large)
        if (1900 <= pin <= 2035 and pin - first > 150
                and "Stat" not in reporter):
            out.append({"rule": "pincite-arithmetic", "location": loc,
                        "find": _ctx(text, m.start(), m.end()), "exact": m.group(0),
                        "problem": "pincite %d is %d pages past the first page %d and looks like a pasted YEAR, not a page"
                                   % (pin, pin - first, first),
                        "fix": "re-check the pincite (a year may have been pasted in its place)",
                        "severity": "likely"})
            continue
        if pin >= first or pin == 0:
            continue
        # "at 350" forms and n.6 pins never match (digits only); ranges keep lo
        out.append({"rule": "pincite-arithmetic", "location": loc,
                    "find": _ctx(text, m.start(), m.end()), "exact": m.group(0),
                    "problem": "pincite %d is below the citation's own first page %d — impossible"
                               % (pin, first),
                    "fix": "re-check the pincite (transposition or missing digit)",
                    "severity": "likely"})
    return out


def caption_consistency(notes):
    """Same case caption + reporter cited with different volume/first-page in
    different footnotes (e.g., Jardines as both 509 U.S. 1 and 569 U.S. 1)."""
    seen = {}
    for num in sorted(notes):
        for m in CAPTION_CITE.finditer(notes[num]):
            cap = _caption_key(m.group(1))
            rep = re.sub(r"\s", "", m.group(3))
            seen.setdefault((cap, rep), {}).setdefault(
                (m.group(2), m.group(4)), []).append((num, m.group(0)))
    out = []
    for (cap, rep), variants in seen.items():
        if len(variants) < 2:
            continue
        detail = "; ".join("n.%d: %r" % (locs[0][0], vf)
                           for (v, f), locs in variants.items() for vf in [locs[0][1]])
        first_note, first_cite = min(l for locs in variants.values() for l in locs)
        out.append({"rule": "case-cite-inconsistency",
                    "location": {"where": "footnote", "note": first_note},
                    "find": first_cite, "exact": first_cite,
                    "problem": "the same case is cited with different volume/first-page across footnotes: %s"
                               % detail,
                    "fix": "reconcile to the correct citation", "severity": "likely"})
    return out


_YEAR_PAREN = re.compile(r"\([^)]*\b(1[6-9]\d\d|20[0-3]\d)\b[^)]*\)")

# U.S. Reports volume ↔ decision-year sanity. Publication pace varies, so
# interpolate between anchor volumes and allow ±3 years; volumes below 100
# (nominative-reporter era) are skipped. Catches "585 U.S. 296 (2013)" —
# Carpenter with Jardines's year left behind (2026-07-14 Codex-2 lesson) —
# with no external source.
_US_VOL_ANCHORS = [(100, 1879), (200, 1906), (300, 1937), (400, 1971),
                   (500, 1991), (550, 2007), (600, 2023), (620, 2030)]
_US_VOL_YEAR = re.compile(
    r"\b(\d{3})\s+U\.\s?S\.\s+(?:__|\d{1,4})(?:,\s+(?:__|\d{1,4})(?:[–—-]\d{1,4})?)?"
    r"(?:\s+&\s+nn?\.\s?\d+(?:[–—-]\d+)?)?\s*\((1[89]\d\d|20[0-3]\d)\)")


def _expected_us_year(vol):
    for (v1, y1), (v2, y2) in zip(_US_VOL_ANCHORS, _US_VOL_ANCHORS[1:]):
        if v1 <= vol <= v2:
            return y1 + (vol - v1) * (y2 - y1) / (v2 - v1)
    return None


def us_volume_year_lint(text, loc):
    out = []
    for m in _US_VOL_YEAR.finditer(text):
        vol, year = int(m.group(1)), int(m.group(2))
        exp = _expected_us_year(vol)
        if exp is None or abs(year - exp) <= 3:
            continue
        out.append({"rule": "us-volume-year", "location": loc,
                    "find": _ctx(text, m.start(), m.end()), "exact": m.group(0),
                    "problem": "volume %d of U.S. Reports and year (%d) don't fit (volume %d decisions are from roughly %d) — one of them is wrong"
                               % (vol, year, vol, round(exp)),
                    "fix": "re-check the volume and the year against the reporter",
                    "severity": "likely"})
    return out


def missing_year_lint(notes):
    """A FULL case citation (caption + reporter + first page) whose trailing
    parentheticals contain no decision year — "Markham v. Allen, 326 U.S. 490,
    493–94 (describing …)" (2026-07-14 Codex-2 lesson). Conservative: any
    4-digit year anywhere in the citation's tail (before the next cite at ';')
    counts, and slip-op/placeholder forms are skipped."""
    out = []
    for num in sorted(notes):
        t = notes[num]
        for m in CAPTION_CITE.finditer(t):
            tail = t[m.end():m.end() + 120].split(";")[0]
            if _YEAR_PAREN.search(tail):
                continue
            if "__" in tail or "slip op" in tail or "_ " in tail:
                continue
            out.append({"rule": "cite-missing-year",
                        "location": {"where": "footnote", "note": num},
                        "find": _ctx(t, m.start(), min(len(t), m.end() + 40)),
                        "exact": m.group(0),
                        "problem": "full case citation with no decision year in its parentheticals",
                        "fix": "add the year parenthetical (verify the year against the reporter)",
                        "severity": "likely"})
    return out


# "Author, supra note N" whose target note doesn't contain that author — the
# wrong-target / misspelled-name class (ported from cite-check's extractor).
_SIGNALS = {"see", "cf", "but", "accord", "compare", "contra", "eg", "also",
            "and", "e.g", "id", "in", "of", "generally"}
SUPRA_NAME = re.compile(
    r"([A-Z][A-Za-z'’\-]{2,}(?:\s+&\s+[A-Z][A-Za-z'’\-]{2,}|\s+[A-Z][A-Za-z'’\-]{2,}){0,2}),?\s+"
    r"supra\s+note[s]?\s+(\d+)")


def _surname(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


_WORD = re.compile(r"[a-z0-9]+")


def duplicate_passage_lint(paras, k=12, window=6, cap=8):
    """A ≥k-word passage repeated nearly verbatim in a nearby body paragraph —
    the duplicated-quotation / botched-move class of editing residue (the
    2026-07-14 draft quoted the same two-part Nelson passage in consecutive
    paragraphs; every reader missed it, a shingle scan can't). Window-limited:
    an intentional re-quote of the Introduction 100 paragraphs later is fine;
    the same block quote twice within a page is residue. Verify adjudicates."""
    plist = [p for p in paras if not p["heading"] and not p.get("toc")]
    seen, out = {}, []
    flagged = set()
    for idx, p in enumerate(plist):
        toks = [(mm.group(0), mm.start(), mm.end())
                for mm in _WORD.finditer(p["text"].lower())]
        for i in range(0, max(0, len(toks) - k + 1)):
            sh = " ".join(t[0] for t in toks[i:i + k])
            if sh in seen:
                pidx, ppid = seen[sh]
                pair = (ppid, p["id"])
                if idx != pidx and idx - pidx <= window and pair not in flagged:
                    flagged.add(pair)
                    excerpt = p["text"][toks[i][1]:toks[i + k - 1][2]]
                    out.append({"rule": "duplicated-passage",
                                "location": {"where": "body", "para": p["id"]},
                                "find": excerpt, "exact": excerpt,
                                "problem": "¶%s repeats a %d+-word passage from nearby ¶%s nearly verbatim — duplicated quotation or editing residue"
                                           % (p["id"], k, ppid),
                                "fix": "read both paragraphs and consolidate if unintended",
                                "severity": "likely"})
                    if len(out) >= cap:
                        return out
            else:
                seen[sh] = (idx, p["id"])
    return out


def supra_name_lint(notes):
    out = []
    for num in sorted(notes):
        for m in SUPRA_NAME.finditer(notes[num]):
            toks = re.split(r"\s+", m.group(1).split("&")[0].strip())
            while toks and _surname(toks[0]) in _SIGNALS:
                toks.pop(0)
            key = _surname(toks[0]) if toks else ""
            tgt_num = int(m.group(2))
            tgt = notes.get(tgt_num, "")
            if not key or len(key) < 4:
                continue
            loc = {"where": "footnote", "note": num}
            tgt_squash = _surname(tgt)
            # per-token squash so O'Brien/D'Onfro match themselves as one word
            tgt_words = {_surname(w) for w in tgt.split()}
            if key not in tgt_squash:
                out.append({"rule": "supra-target-name", "location": loc,
                            "find": _ctx(notes[num], m.start(), m.end()),
                            "exact": m.group(0),
                            "problem": "%r — note %d does not mention %s (wrong note number, classic renumbering break)"
                                       % (m.group(0), tgt_num, toks[0]),
                            "fix": "point the supra at the note that actually cites this author",
                            "severity": "error"})
            elif key not in tgt_words:
                out.append({"rule": "supra-name-spelling", "location": loc,
                            "find": _ctx(notes[num], m.start(), m.end()),
                            "exact": m.group(0),
                            "problem": "author spelled %r here but differently in target note %d — spelling variants of the same name"
                                       % (toks[0], tgt_num),
                            "fix": "make the spellings match (check which is right)",
                            "severity": "likely"})
    return out


# ---- heading structure ----------------------------------------------------------
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_val(s):
    total, prev = 0, 0
    for ch in reversed(s):
        v = ROMAN.get(ch, 0)
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def heading_structure_findings(labeled):
    """Sequence gaps (pattern-labeled docs only — Word auto-numbering can't
    gap) + lone subdivisions (an 'A.' with no 'B.' — the law-review outline
    rule). `labeled`: [{para,text,level,val,label,word_numbered}]."""
    out = []
    seq = [h for h in labeled if h.get("val") is not None]
    for lvl in (1, 2, 3):
        groups, cur = [], []
        for h in seq:
            if h["level"] < lvl:
                if cur:
                    groups.append(cur)
                cur = []
            elif h["level"] == lvl:
                cur.append(h)
        if cur:
            groups.append(cur)
        for g in groups:
            if not any(h.get("word_numbered") for h in g):
                for i, h in enumerate(g):
                    if h["val"] != i + 1:
                        out.append({"rule": "heading-sequence",
                                    "location": {"where": "body", "para": h["para"]},
                                    "find": h["text"][:80], "exact": h["label"] or "",
                                    "problem": "heading %r breaks the sequence (expected label #%d at this level)"
                                               % (h["text"][:60], i + 1),
                                    "fix": "renumber the headings in this group",
                                    "severity": "likely"})
                        break  # one finding per group; the rest cascade
            if lvl > 1 and len(g) == 1:
                h = g[0]
                out.append({"rule": "lone-subdivision",
                            "location": {"where": "body", "para": h["para"]},
                            "find": h["text"][:80], "exact": h["label"] or "",
                            "problem": "subdivision %r has no sibling — an outline never has an A without a B"
                                       % (h["text"][:60]),
                            "fix": "fold the content into the parent or split it into two siblings",
                            "severity": "likely"})
    return out


# ---- consistency data ------------------------------------------------------------
BRIT_AM = [
    ("judgement", "judgment"), ("acknowledgement", "acknowledgment"),
    ("defence", "defense"), ("offence", "offense"), ("labour", "labor"),
    ("colour", "color"), ("favour", "favor"), ("behaviour", "behavior"),
    ("analyse", "analyze"), ("centre", "center"), ("travelled", "traveled"),
    ("modelled", "modeled"), ("focussed", "focused"), ("organise", "organize"),
]
HYPH_TOKEN = re.compile(r"\b([a-z]{3,})-([a-z]{3,})\b")
DEFINED_TERM = re.compile(
    r"\((?:hereinafter(?:\s+referred\s+to\s+as)?\s+)?[“\"']"
    r"((?:the\s+)?[A-Z][A-Za-z0-9 .&’']{1,45}?)[”\"']\)")


def word_count_ci(full, w):
    return len(re.findall(r"\b%s\b" % re.escape(w), full, re.IGNORECASE))


def consistency_data(full_lower, full, locate):
    """Variant counts + defined terms. `locate(word)` returns up to 6 locations."""
    hyph = {}
    for m in HYPH_TOKEN.finditer(full_lower):
        a, b = m.group(1), m.group(2)
        key = a + "-" + b
        if key in hyph:
            continue
        closed = len(re.findall(r"\b%s%s\b" % (a, b), full_lower))
        open_ = len(re.findall(r"\b%s %s\b" % (a, b), full_lower))
        hyphc = len(re.findall(r"\b%s-%s\b" % (a, b), full_lower))
        if closed:  # hyphen/closed conflict is the real inconsistency signal
            hyph[key] = {"hyphenated": hyphc, "closed": closed, "open": open_,
                         "closed_form": a + b,
                         "locations": {"hyphenated": locate(a + "-" + b),
                                       "closed": locate(a + b)}}
    spelling = []
    for br, am in BRIT_AM:
        nb = len(re.findall(r"\b%s" % br, full_lower))
        na = len(re.findall(r"\b%s" % am, full_lower))
        if nb:
            spelling.append({"british": br, "american": am,
                             "british_count": nb, "american_count": na,
                             "british_locations": locate(br)})
    terms = []
    seen = set()
    for m in DEFINED_TERM.finditer(full):
        t = _clean(m.group(1))
        if t.lower() in seen or len(t.split()) > 6:
            continue
        seen.add(t.lower())
        core = re.sub(r"^the\s+", "", t, flags=re.IGNORECASE)
        terms.append({"term": t, "defined_at": _ctx(full, m.start(), m.end(), 60),
                      "later_uses": max(0, word_count_ci(full, core) - 1)})
    stats = {
        "double_spaces": len(re.findall(r"[^\s]  [^\s]", full)),
        "straight_double_quotes": full.count('"'),
        "curly_double_quotes": full.count("“") + full.count("”"),
        "straight_apostrophes": len(re.findall(r"[A-Za-z]'[A-Za-z]", full)),
        "curly_apostrophes": len(re.findall(r"[A-Za-z]’[A-Za-z]", full)),
        "emdash_spaced": len(re.findall(r"\s—\s", full)),
        "emdash_closed": len(re.findall(r"[A-Za-z]—[A-Za-z]", full)),
        "serial_comma_with": len(re.findall(r"\b\w+, \w+(?: \w+){0,2}, (?:and|or)\b", full)),
        "serial_comma_without": len(re.findall(r"\b\w+, \w+(?: \w+){0,2} (?:and|or) \w", full)),
    }
    return {"hyphenation_variants": hyph, "spelling_variants": spelling,
            "defined_terms": terms, "stats": stats}


# ---- main -----------------------------------------------------------------------
def main(argv):
    if len(argv) < 2:
        print("usage: extract_proof.py <draft.docx|dir|draft.md> <outdir> [--chunk-words N]",
              file=sys.stderr)
        return 2
    src, outdir = argv[0], argv[1]
    chunk_words = DEFAULT_CHUNK_WORDS
    if "--chunk-words" in argv:
        chunk_words = int(argv[argv.index("--chunk-words") + 1])
    os.makedirs(os.path.join(outdir, "chunks"), exist_ok=True)

    if src.lower().endswith((".md", ".markdown", ".txt")):
        notes_by_id, raw_paras, order, has_ins, has_del, fmt_ok = parse_markdown(src)
    else:
        notes_by_id, raw_paras, order, has_ins, has_del, fmt_ok = parse_docx(src)
    id2num = build_number_map(order)
    footnote_count = len(id2num)

    # rendered paragraphs: [[FN:id]] -> [FN#num]
    def render(t):
        return FN_PLACEHOLDER.sub(
            lambda m: "[FN#%s]" % id2num.get(m.group(1), "?"), t)

    has_style_headings = any(
        re.match(r"heading\s?\d", (p["style"] or "").lower()) for p in raw_paras)
    paras, labeled_headings, toc_entries = [], [], []
    para_spans = {}             # paragraph id -> formatting spans (rendered offsets)
    counters = [0, 0, 0, 0, 0]  # numbering counters, levels 1..4
    last_l1 = last_l2 = 0       # pattern-mode disambiguation state
    for i, p in enumerate(raw_paras):
        text = render(p["text"])
        style = (p["style"] or "").lower()
        spans = shift_spans(p["text"], p.get("spans") or [], id2num)
        para_spans[i] = spans
        entry = {"id": i, "text": text, "heading": None,
                 "words": len(text.split())}
        # Word renders these in caps/italics regardless of the stored letters —
        # the stored text of an all-caps header is often lowercase or randomly
        # cased, and nothing downstream may judge its capitalization.
        if prop_ratio(spans, 0, len(text), "caps") >= 0.8:
            entry["display"] = "ALL CAPS"
        elif prop_ratio(spans, 0, len(text), "smallCaps") >= 0.8:
            entry["display"] = "SMALL CAPS"
        if style.startswith("toc"):
            entry["toc"] = True
            toc_entries.append({"para": i, "text": text})
            paras.append(entry)
            continue
        lvl = val = lab = None
        word_numbered = False
        if has_style_headings:
            lvl = style_heading_level(p["style"])
            if lvl and re.match(r"heading\s?\d", style):  # auto-numbered
                counters[lvl] += 1
                for d in range(lvl + 1, 5):
                    counters[d] = 0
                val, word_numbered = counters[lvl], True
                parts = [to_roman(counters[1])]
                if lvl >= 2:
                    parts.append(chr(64 + counters[2]))
                if lvl >= 3:
                    parts.append(str(counters[3]))
                lab = ".".join(parts[:lvl])
        else:
            ph = pattern_heading(text, last_l1, last_l2)
            if ph:
                lvl, val, lab = ph
                if lvl == 1 and val is not None:
                    last_l1, last_l2 = val, 0
                elif lvl == 2 and val is not None:
                    last_l2 = val
        if lvl:
            entry["heading"] = lvl
            labeled_headings.append({"para": i, "level": lvl, "text": text,
                                     "label": lab, "val": val,
                                     "word_numbered": word_numbered,
                                     "display": entry.get("display")})
        paras.append(entry)

    notes, note_spans = {}, {}
    for fid, rec in notes_by_id.items():
        num = id2num.get(fid)
        if num is None:
            continue
        notes[num] = render(rec["text"])
        note_spans[num] = shift_spans(rec["text"], rec.get("spans") or [], id2num)

    # ---- lint + cross-refs ----
    lint, part_refs = [], []
    for p in paras:
        if p["heading"] or p.get("toc"):
            continue
        loc = {"where": "body", "para": p["id"]}
        lint += lint_text(p["text"], loc)
        lint += note_ref_findings(p["text"], loc, None, footnote_count)
        part_refs += collect_part_refs(p["text"], loc)
    for num in sorted(notes):
        loc = {"where": "footnote", "note": num}
        lint += lint_text(notes[num], loc)
        lint += note_ref_findings(notes[num], loc, num, footnote_count)
        part_refs += collect_part_refs(notes[num], loc)
        lint += cite_mechanics_lint(notes[num], loc)
        lint += terminal_punct_finding(notes[num], loc)
        lint += pincite_lint(notes[num], loc)
        lint += us_volume_year_lint(notes[num], loc)
    lint += caption_consistency(notes)
    lint += supra_name_lint(notes)
    lint += missing_year_lint(notes)
    lint += duplicate_passage_lint(paras)
    lint += short_form_lint(notes)

    # ---- typeface (only when the formatting layer is real) ----
    fmt_conventions, case_inventory, case_counts = [], [], {}
    if fmt_ok:
        for p in paras:
            if p["heading"] or p.get("toc"):
                continue
            lint += typeface_lint(p["text"], para_spans.get(p["id"], []),
                                  {"where": "body", "para": p["id"]}, False)
        for num in sorted(notes):
            lint += typeface_lint(notes[num], note_spans.get(num, []),
                                  {"where": "footnote", "note": num}, True)
        case_inventory, fmt_conventions, case_counts = case_name_typeface(
            paras, notes, para_spans, note_spans)
    # page-range dash style: flag hyphen ranges only when en-dash clearly
    # dominates the draft's own footnotes (a convention, not an absolute)
    all_notes = " ".join(notes.values())
    endash_ranges = len(re.findall(r"\d–\d", all_notes))
    hyphen_ranges = re.findall(r"\b\d{2,4}-\d{1,4}\b", all_notes)
    if endash_ranges >= 3 * max(1, len(hyphen_ranges)) and hyphen_ranges:
        flagged = 0
        for num in sorted(notes):
            for m in re.finditer(r"\b\d{2,4}-\d{1,4}\b", notes[num]):
                # skip docket/statute-section numbers and URLs, which legitimately hyphenate
                before = notes[num][:m.start()]
                if re.search(r"(?:Nos?\.|§|[Dd]ocket)\s*$", before) or before.endswith(("/", "=", "-")):
                    continue
                lint.append({"rule": "cite-range-hyphen",
                             "location": {"where": "footnote", "note": num},
                             "find": _ctx(notes[num], m.start(), m.end()),
                             "exact": m.group(0),
                             "problem": "page range uses a hyphen; the draft's convention is an en dash (%d en-dash ranges vs %d hyphens)"
                                        % (endash_ranges, len(hyphen_ranges)),
                             "fix": "use an en dash (–)", "severity": "likely"})
                flagged += 1
                if flagged >= 12:
                    break
            if flagged >= 12:
                break
    lint += heading_structure_findings(labeled_headings)

    # Part/Section refs pointing at labels the draft doesn't have. Only when we
    # trust the label map (Word auto-numbering); "likely" because a ref can
    # legitimately point into ANOTHER work ("Smith, supra, Part II").
    label_set = {h["label"] for h in labeled_headings if h.get("label")}
    if label_set and any(h.get("word_numbered") for h in labeled_headings):
        for r in part_refs:
            if r["label"] not in label_set:
                lint.append({"rule": "part-cross-reference", "location": r["location"],
                             "find": r["context"], "exact": r["ref"],
                             "problem": "%r — the draft's headings include no label %s (draft labels: %s)"
                                        % (r["ref"], r["label"],
                                           ", ".join(sorted(label_set))),
                             "fix": "re-check the Part/Section number (or it may cite another work's Part)",
                             "severity": "likely"})

    # ---- fulltext for the consistency agents ----
    lines = []
    for p in paras:
        if p.get("toc"):
            prefix = "[TOC] "
        elif p["heading"]:
            prefix = "#" * p["heading"] + " "
        else:
            prefix = "[¶%d] " % p["id"]
        lines.append(prefix + p["text"])
    lines.append("")
    lines.append("===== FOOTNOTES =====")
    for num in sorted(notes):
        lines.append("[n.%d] %s" % (num, notes[num]))
    fulltext = "\n\n".join(lines)
    with open(os.path.join(outdir, "fulltext.txt"), "w", encoding="utf-8") as f:
        f.write(fulltext)

    # ---- the same document with typeface markup, for the formatting stage ----
    # Identical line structure to fulltext.txt so the verify agents can Grep the
    # same "^\[n\.45\]" patterns; strip the tags and you get fulltext.txt back.
    if fmt_ok:
        flines = []
        for p in paras:
            marked = render_marked(p["text"], para_spans.get(p["id"], []))
            if p.get("toc"):
                prefix = "[TOC] "
            elif p["heading"]:
                prefix = "#" * p["heading"] + " "
            else:
                prefix = "[¶%d] " % p["id"]
            if p.get("display"):
                prefix += "(displays %s) " % p["display"]
            flines.append(prefix + marked)
        flines += ["", "===== FOOTNOTES ====="]
        for num in sorted(notes):
            flines.append("[n.%d] %s"
                          % (num, render_marked(notes[num], note_spans.get(num, []))))
        with open(os.path.join(outdir, "fulltext_fmt.txt"), "w", encoding="utf-8") as f:
            f.write("\n\n".join(flines))

    # ---- consistency data ----
    def locate(word):
        pat = re.compile(r"\b%s\b" % re.escape(word), re.IGNORECASE)
        hits = []
        for p in paras:
            if pat.search(p["text"]):
                hits.append("¶%d" % p["id"])
            if len(hits) >= 6:
                return hits
        for num in sorted(notes):
            if pat.search(notes[num]):
                hits.append("n.%d" % num)
            if len(hits) >= 6:
                break
        return hits
    cons = consistency_data(fulltext.lower(), fulltext, locate)

    # ---- chunks: contiguous paragraphs + the footnotes they reference ----
    chunks, cur, cur_words = [], [], 0
    fn_of_para = {}
    for i, p in enumerate(raw_paras):
        fn_of_para[i] = [id2num[fid] for fid in FN_PLACEHOLDER.findall(p["text"])
                         if fid in id2num]
    for p in paras:
        if p.get("toc"):
            continue  # Word regenerates the TOC; don't proofread it
        note_words = sum(len(notes[n].split()) for n in fn_of_para[p["id"]] if n in notes)
        if cur and cur_words + p["words"] + note_words > chunk_words:
            chunks.append(cur)
            cur, cur_words = [], 0
        cur.append(p["id"])
        cur_words += p["words"] + note_words
    if cur:
        chunks.append(cur)

    chunk_files = []
    for ci, ids in enumerate(chunks):
        cnotes = sorted({n for pid in ids for n in fn_of_para[pid] if n in notes})
        payload = {
            "chunk_id": ci,
            "paragraphs": [paras[pid] for pid in ids],
            "footnotes": [{"number": n, "text": notes[n]} for n in cnotes],
            "word_count": sum(paras[pid]["words"] for pid in ids)
                          + sum(len(notes[n].split()) for n in cnotes),
        }
        path = os.path.join(outdir, "chunks", "chunk-%02d.json" % ci)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        chunk_files.append(path)

    try:
        with open(src, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
    except (IsADirectoryError, OSError):
        sha256 = None
    data = {
        "source": src,
        "sha256": sha256,
        "note_para": {str(n): min(p for p, ns in fn_of_para.items() if n in ns)
                      for n in notes if any(n in ns for ns in fn_of_para.values())},
        "paragraph_count": len(paras),
        "footnote_count": footnote_count,
        "word_count": sum(p["words"] for p in paras)
                      + sum(len(t.split()) for t in notes.values()),
        "tracked_insertions": has_ins,
        "tracked_deletions": has_del,
        "headings": labeled_headings,
        "toc_entries": toc_entries,
        "chunk_files": chunk_files,
        "lint_findings": lint,
        "part_refs": part_refs,
        "consistency": cons,
        "formatting": {
            "available": bool(fmt_ok),
            "fulltext_fmt": os.path.join(outdir, "fulltext_fmt.txt") if fmt_ok else None,
            "markup": "<i>italic</i>, <sc>small caps</sc>, <caps>rendered all caps</caps>",
            "display_headings": [
                {"para": h["para"], "text": h["text"], "display": h["display"]}
                for h in labeled_headings if h.get("display")],
            "conventions": fmt_conventions,
            "case_name_counts": case_counts,
            "case_name_candidates": case_inventory,
            "italic_runs": sum(1 for sp in list(para_spans.values()) + list(note_spans.values())
                               for s in sp if "i" in s[2]),
            "small_caps_runs": sum(1 for sp in list(para_spans.values()) + list(note_spans.values())
                                   for s in sp if "smallCaps" in s[2]),
        },
    }
    with open(os.path.join(outdir, "proof.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    cite_mech = sum(1 for f in lint if f["rule"].startswith(("cite-", "pincite", "case-cite", "supra-")))
    print(json.dumps({
        "sha256": (sha256 or "")[:16],
        "cite_mechanics_findings": cite_mech,
        "short_form_findings": sum(1 for f in lint if f["rule"] == "cite-short-form"),
        "formatting_available": bool(fmt_ok),
        "typeface_findings": sum(1 for f in lint if f["rule"].startswith("fmt-")),
        "typeface_conventions": len(fmt_conventions),
        "all_caps_headings": sum(1 for h in labeled_headings if h.get("display")),
        "paragraph_count": data["paragraph_count"],
        "footnote_count": footnote_count,
        "word_count": data["word_count"],
        "chunk_count": len(chunk_files),
        "lint_finding_count": len(lint),
        "part_ref_count": len(part_refs),
        "hyphenation_variant_count": len(cons["hyphenation_variants"]),
        "spelling_variant_count": len(cons["spelling_variants"]),
        "defined_term_count": len(cons["defined_terms"]),
        "tracked_insertions": has_ins,
        "tracked_deletions": has_del,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
