#!/usr/bin/env python3
"""Extraction layer for the /cite-check skill (design: DESIGN.md).

Parses an article draft and emits, as JSON, everything the verification
pipeline needs to check citations and quotations against real sources:

  * every footnote, keyed by its RENDERED number (the number a reader sees),
    with its FULL text (never truncated — truncation caused the practice run's
    one false "fabricated" verdict), plus a deterministic pre-parse of its
    cross-references (leading "Id.", "supra note N" targets) and the reporter-
    style case citations it contains;
  * every quotation >= MIN_QUOTE_WORDS words in the body, paired with the
    footnote that follows it AND its full surrounding body sentence (the
    framing context — its absence caused the practice run's false "dropped not"
    verdict);
  * every quotation inside a footnote (parentheticals quoting a source).

The hard problem this solves correctly: in Word, footnote XML ids are NOT the
rendered footnote numbers (separators occupy low ids; real notes run offset).
Rendered numbers are assigned by the order footnote reference marks appear in
the body, so we build the id -> rendered-number map from body order.

Input: a .docx file (parsed in memory via zipfile), an already-unzipped .docx
directory, or a markdown / plain-text draft (pandoc-style [^n]: footnotes) as a
fallback. Stdlib only. JSON to stdout (or to an out path if given).

Usage:
    python3 extract_cites.py <draft.docx | unzipped_dir | draft.md> [out.json]
"""
import json
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

# Shared citation-FORM library (Bluebook typeface + short forms + the .docx
# run-formatting reader), same module /proofread uses, so the two skills cannot
# drift apart on these rules. Added 2026-08-10 when the author lifted the format-linter
# scope lock for "obvious stuff". Installed path first, sibling fallback for the
# un-symlinked master copy.
for _p in (os.path.expanduser("~/.claude/skills/legal-research"),
           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "legal-research")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
try:
    import citeform
except ImportError:                                          # degrade, never die
    citeform = None

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MIN_QUOTE_WORDS = 8
FN_PLACEHOLDER = re.compile(r"\[\[FN:(-?\d+)\]\]")
QUOTE_PAT = re.compile(r"[“\"](.+?)[”\"]")  # curly or straight double quotes

# Reporter-citation regex — deliberately loose; the goal is to surface the raw
# cite strings for check_cite.py (CourtListener's lookup does the real parsing),
# not to be an authoritative Bluebook parser. Feed it raw footnote text.
REPORTER = (
    r"U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.\s?(?:2d|3d|4th|Supp\.(?:\s?[23]d)?|App'?x)?|"
    r"Cal\.(?:\s?(?:2d|3d|4th|5th|App\.))?|N\.\s?[EWY]\.\s?(?:2d|3d)?|A\.\s?(?:2d|3d)?|"
    r"So\.\s?(?:2d|3d)?|P\.\s?(?:2d|3d)?|Fed\.\s?Appx\.|B\.\s?R\."
)
# Early-Republic cites carry a parallel NOMINATIVE reporter, in either order:
#   "3 U.S. (3 Dall.) 171"      — official first, nominative parenthetical
#   "4 Wheat. (17 U.S.) 316"    — nominative first, official parenthetical
# Neither matched the plain pattern (the parenthetical sits exactly where the
# page number is expected), so Marbury, Hylton and McCulloch were skipped by the
# existence check entirely — silently, since a cite that never matches is never
# reported as unverified. Found 2026-08-10 while building /proofread's
# short-form check, which had the same blind spot.
CASE_CITE = re.compile(
    r"\b\d{1,4}\s+(?:%s)\s+(?:\([^)]{1,24}\)\s+)?\d{1,4}\b" % REPORTER)
CASE_CITE_INVERTED = re.compile(
    r"\b\d{1,4}\s+[A-Z][\w.'’]{0,12}\.?\s+\((\d{1,4})\s+(%s)\)\s+(\d{1,4})\b" % REPORTER)
_PARALLEL_PAREN = re.compile(r"\s*\([^)]{1,24}\)\s*")


def normalize_case_cite(s):
    """Drop a parallel-reporter parenthetical so the cite is what CourtListener
    actually looks up: "3 U.S. (3 Dall.) 171" -> "3 U.S. 171"."""
    return _clean(_PARALLEL_PAREN.sub(" ", s))


def find_case_cites(text):
    """Reporter cites in `text`, normalized, both parallel-cite orders."""
    out = {normalize_case_cite(m.group(0)) for m in CASE_CITE.finditer(text)}
    out |= {"%s %s %s" % (m.group(1), m.group(2), m.group(3))
            for m in CASE_CITE_INVERTED.finditer(text)}
    return sorted(out)
SUPRA = re.compile(r"supra\s+note[s]?\s+(\d+)", re.IGNORECASE)
# The author name(s) IMMEDIATELY before "supra note N" (Bluebook form:
# "Author, supra note N" / "Author & Author, supra note N") — the party the
# supra is claimed to point at, for the deterministic broken-supra candidate
# check. Kept tight (name adjacent to "supra") to limit false positives; the
# segment/resolve model stage is the authoritative supra checker.
SUPRA_WITH_NAME = re.compile(
    r"([A-Z][A-Za-z'\-]{2,}(?:\s+&\s+[A-Z][A-Za-z'\-]{2,}|\s+[A-Z][A-Za-z'\-]{2,}){0,2}),?\s+"
    r"supra\s+note[s]?\s+(\d+)"
)


def runs_text(el, include_deleted=False):
    """Concatenate w:t text under el, skipping tracked-deletion runs unless
    asked; footnote reference marks become [[FN:id]] placeholders so body order
    and quote->footnote pairing survive the flattening."""
    out = []
    for node in el.iter():
        if node.tag == W + "delText" and not include_deleted:
            continue
        if node.tag in (W + "t", W + "delText"):
            out.append(node.text or "")
        elif node.tag == W + "footnoteReference":
            out.append("[[FN:%s]]" % node.get(W + "id"))
        elif node.tag == W + "tab":
            out.append(" ")
    return "".join(out)


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


# ---- sentence segmentation (framing context for body quotes) ----------------
# Legal prose is dense with period-bearing abbreviations that must NOT end a
# sentence. Protect them, split, then restore.
_ABBR = [
    "U.S.", "U. S.", "S. Ct.", "L. Ed.", "F.2d", "F.3d", "F. Supp.", "e.g.", "i.e.",
    "cf.", "id.", "Id.", "No.", "Nos.", "art.", "arts.", "ch.", "pp.", "para.",
    "sec.", "Rev.", "L.J.", "L. Rev.", "J.L.", "Ass'n", "Corp.", "Co.", "Inc.",
    "Ltd.", "Bros.", "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Jr.", "Sr.", "St.",
    "Ct.", "Cir.", "Dist.", "Dep't", "Comm'n", "Vol.", "Nat'l", "Int'l", "Univ.",
    "ed.", "eds.", "vs.", "v.",
]
_INITIAL = re.compile(r"\b([A-Z])\.")  # single-letter initials, e.g. "A. Scalia"
_SENT_SPLIT = re.compile(r"(?<=[.!?])[\)\"”]?\s+(?=[\"“\[A-Z0-9])")


def sentence_spans(text):
    """Return (start, end) spans of sentences in text, abbreviation-aware."""
    protected = text
    for a in _ABBR:
        protected = protected.replace(a, a.replace(".", "\x00"))
    protected = _INITIAL.sub(lambda m: m.group(1) + "\x00", protected)
    spans = []
    start = 0
    for m in _SENT_SPLIT.finditer(protected):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(s, e) for (s, e) in spans if text[s:e].strip()]


def surrounding_sentence(para, qstart, qend):
    """The sentence(s) of `para` overlapping the quote span [qstart, qend),
    with [[FN:id]] placeholders stripped. Captures the draft's own framing verb
    (e.g. "has encouraged state courts to '...'") that lives in the same
    sentence as the quote."""
    spans = sentence_spans(para)
    hit = [(s, e) for (s, e) in spans if s < qend and e > qstart]
    if not hit:
        s, e = max(0, qstart - 240), min(len(para), qend + 120)
    else:
        s, e = hit[0][0], hit[-1][1]
    return _clean(FN_PLACEHOLDER.sub("", para[s:e]))


# ---- footnote cross-reference pre-parse -------------------------------------
def _surname(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


# Bluebook introductory signals that can sit in front of an author name and must
# not be mistaken for it when checking a supra target.
_SIGNALS = {"see", "cf", "but", "accord", "compare", "contra", "eg", "also",
            "and", "e.g", "id", "in", "of"}


def _name_key(name):
    """Leading author surname of a 'supra' antecedent, signals stripped."""
    toks = re.split(r"\s+", name.split("&")[0].strip())
    while toks and _surname(toks[0]) in _SIGNALS:
        toks.pop(0)
    return _surname(toks[0]) if toks else ""


def parse_refs(text):
    """Deterministic cross-reference pre-parse of one footnote's text: whether
    it opens with 'Id.', and each 'supra note N' with the name it claims."""
    body = re.sub(r"^\s*\.?\s*", "", text)  # strip Word's leading ". "
    leading_id = bool(re.match(r"(?:See\s+)?Id\.", body, re.IGNORECASE))
    supra = []
    for m in SUPRA_WITH_NAME.finditer(text):
        supra.append({"name": _clean(m.group(1)), "note": int(m.group(2))})
    # supra refs with no capturable name (bare "supra note N")
    named = {(s["note"]) for s in supra}
    for m in SUPRA.finditer(text):
        n = int(m.group(1))
        if n not in named:
            supra.append({"name": "", "note": n})
            named.add(n)
    return {"leading_id": leading_id, "supra": supra,
            "cases": find_case_cites(text)}


# ---- .docx parsing ----------------------------------------------------------
def _load_xml(source, member):
    """Read an XML member from a .docx (zip) or an unzipped directory."""
    if isinstance(source, zipfile.ZipFile):
        with source.open(member) as f:
            return ET.parse(f).getroot()
    return ET.parse(source + "/" + member).getroot()


def parse_footnotes_xml(root):
    """{xml_id: full_text} for every real footnote (separators skipped)."""
    notes = {}
    for fn in root.findall(W + "footnote"):
        if fn.get(W + "type") in ("separator", "continuationSeparator"):
            continue
        fid = fn.get(W + "id")
        text = " ".join(runs_text(p) for p in fn.findall(W + "p"))
        notes[fid] = _clean(text)
    return notes


def parse_body_xml(root):
    """Body paragraphs (flattened, with [[FN:id]] marks) and the ORDER of
    footnote reference ids as they appear in the body — the source of truth for
    rendered footnote numbering."""
    paras = []
    order = []
    has_ins = has_del = False
    for p in root.iter(W + "p"):
        if p.find(".//" + W + "ins") is not None:
            has_ins = True
        if p.find(".//" + W + "del") is not None:
            has_del = True
        t = _clean(runs_text(p))
        if t:
            paras.append(t)
        for ref in p.iter(W + "footnoteReference"):
            order.append(ref.get(W + "id"))
    return paras, order, has_ins, has_del


def build_number_map(order):
    """id -> rendered number (1-based), from first appearance in body order."""
    id2num, n = {}, 0
    for fid in order:
        if fid not in id2num:
            n += 1
            id2num[fid] = n
    return id2num


# ---- markdown / plain-text fallback -----------------------------------------
MD_FN_DEF = re.compile(r"^\s*\[\^([0-9A-Za-z]+)\]:\s*(.*)$")
MD_FN_REF = re.compile(r"\[\^([0-9A-Za-z]+)\]")


def parse_markdown(path):
    """Pandoc-style footnotes: [^id] inline refs, [^id]: definition lines.
    Rendered numbering follows inline-reference order in the body."""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    defs, body_lines = {}, []
    cur = None
    for ln in lines:
        m = MD_FN_DEF.match(ln)
        if m:
            cur = m.group(1)
            defs[cur] = m.group(2).strip()
        elif cur and (ln.startswith("    ") or ln.startswith("\t")):
            defs[cur] += " " + ln.strip()  # continuation line
        else:
            cur = None
            body_lines.append(ln.rstrip("\n"))
    body = "\n".join(body_lines)
    order = [m.group(1) for m in MD_FN_REF.finditer(body)]
    # rewrite refs to the [[FN:id]] placeholder convention, then paragraph-split
    body = MD_FN_REF.sub(lambda m: "[[FN:%s]]" % m.group(1), body)
    paras = [_clean(p) for p in re.split(r"\n\s*\n", body) if _clean(p)]
    notes = {k: _clean(v) for k, v in defs.items()}
    return notes, paras, order, False, False


# ---- quote extraction -------------------------------------------------------
def find_body_quotes(paras, id2num):
    """Quotations >= MIN_QUOTE_WORDS words, each with the rendered number of the
    footnote that follows and the full surrounding body sentence."""
    quotes = []
    for i, para in enumerate(paras):
        for m in QUOTE_PAT.finditer(para):
            raw = m.group(1)
            clean_q = _clean(FN_PLACEHOLDER.sub("", raw))
            if len(clean_q.split()) < MIN_QUOTE_WORDS:
                continue
            tail = FN_PLACEHOLDER.search(para[m.start():])
            fid = tail.group(1) if tail else None
            quotes.append({
                "para": i,
                "quote": clean_q,
                "sentence": surrounding_sentence(para, m.start(), m.end()),
                "footnote": id2num.get(fid) if fid else None,
                "footnote_xml_id": fid,
            })
    return quotes


def find_footnote_quotes(notes_by_num):
    quotes = []
    for num, text in notes_by_num.items():
        for m in QUOTE_PAT.finditer(text):
            q = _clean(m.group(1))
            if len(q.split()) >= MIN_QUOTE_WORDS:
                quotes.append({"footnote": num, "quote": q})
    return quotes


# ---- Bluebook FORM layer (typeface + short forms) ---------------------------
# Scope-lock lifted by the user 2026-08-10 ("undo the lock insofar as it's stopping
# you from checking obvious stuff"). These run off the SAME shared module
# /proofread uses, so the two skills can never disagree about a rule.
#
# Deliberately additive: this does NOT touch the existing text-extraction path.
# Formatting spans are computed in a second pass and accepted only when the text
# they were built from matches the text the validated parser already produced —
# a footnote that fails that check simply gets no typeface analysis rather than
# risking misaligned offsets against a pipeline that took three runs to calibrate.
def form_layer(src, notes_by_id, notes_by_num, paras, id2num, out_path):
    empty = {"available": False, "findings": [], "conventions": [],
             "case_name_candidates": [], "case_name_counts": {},
             "fulltext_fmt": None, "aligned": 0, "unaligned": 0}
    if citeform is None:
        return empty
    # short forms need no formatting at all — they work on any input, including
    # the markdown fallback path
    findings = list(citeform.short_form_lint(notes_by_num))
    if src.lower().endswith((".md", ".markdown", ".txt")):
        empty["findings"] = findings
        return empty

    try:
        if src.lower().endswith(".docx"):
            zf = zipfile.ZipFile(src)
            fn_root, body_root, ssrc = (_load_xml(zf, "word/footnotes.xml"),
                                        _load_xml(zf, "word/document.xml"), zf)
        else:
            fn_root, body_root, ssrc = (_load_xml(src, "word/footnotes.xml"),
                                        _load_xml(src, "word/document.xml"), src)
        styles = citeform.parse_styles(_load_xml(ssrc, "word/styles.xml"))
    except (KeyError, OSError, ET.ParseError, zipfile.BadZipFile):
        empty["findings"] = findings
        return empty

    def pstyle(p):
        ppr = p.find(W + "pPr")
        st = ppr.find(W + "pStyle") if ppr is not None else None
        return st.get(W + "val") if st is not None else ""

    aligned = unaligned = 0
    note_spans, note_marked = {}, {}
    for fn in fn_root.findall(W + "footnote"):
        if fn.get(W + "type") in ("separator", "continuationSeparator"):
            continue
        fid = fn.get(W + "id")
        spans = []
        for i, p in enumerate(fn.findall(W + "p")):
            if i:
                spans.append((" ", frozenset()))
            spans += citeform.runs_spans(p, styles, pstyle(p))
        text, sp = citeform.clean_spans(spans)
        if text != notes_by_id.get(fid):
            unaligned += 1
            continue
        aligned += 1
        note_spans[fid] = sp
        note_marked[fid] = citeform.render_marked(text, sp)

    para_spans, para_marked, pdisplay = {}, {}, {}
    idx = 0
    for p in body_root.iter(W + "p"):
        text, sp = citeform.clean_spans(citeform.runs_spans(p, styles, pstyle(p)))
        if not text:
            continue
        if idx < len(paras) and text == paras[idx]:
            para_spans[idx] = sp
            para_marked[idx] = citeform.render_marked(text, sp)
            if citeform.prop_ratio(sp, 0, len(text), "caps") >= 0.8:
                pdisplay[idx] = "ALL CAPS"
        idx += 1

    # re-key by RENDERED footnote number, using the authoritative body-order map
    num2id = {n: f for f, n in id2num.items()}
    nspans = {n: note_spans[f] for n, f in num2id.items() if f in note_spans}

    for num in sorted(nspans):
        findings += citeform.typeface_lint(
            notes_by_num[num], nspans[num], {"where": "footnote", "note": num}, True)
    for i in sorted(para_spans):
        if i in pdisplay:
            continue
        findings += citeform.typeface_lint(
            paras[i], para_spans[i], {"where": "body", "para": i}, False)

    pseudo = [{"id": i, "text": paras[i], "heading": None} for i in sorted(para_spans)]
    cands, conventions, counts = citeform.case_name_typeface(
        pseudo, {n: notes_by_num[n] for n in nspans}, para_spans, nspans)

    fmt_path = os.path.join(os.path.dirname(os.path.abspath(out_path or ".")),
                            "fulltext_fmt.txt")
    lines = []
    for i in sorted(para_marked):
        lines.append("[¶%d] %s%s" % (i, "(displays ALL CAPS) " if i in pdisplay else "",
                                     para_marked[i]))
    lines += ["", "===== FOOTNOTES ====="]
    for num in sorted(num2id):
        if num2id[num] in note_marked:
            lines.append("[n.%d] %s" % (num, note_marked[num2id[num]]))
    try:
        with open(fmt_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(lines))
    except OSError:
        fmt_path = None

    return {"available": True, "findings": findings, "conventions": conventions,
            "case_name_candidates": cands, "case_name_counts": counts,
            "fulltext_fmt": fmt_path, "aligned": aligned, "unaligned": unaligned,
            "markup": "<i>italic</i>, <sc>small caps</sc>, <caps>prints all caps</caps>",
            "all_caps_paragraphs": sorted(pdisplay)}


def main(argv):
    if not argv:
        print("usage: extract_cites.py <draft.docx|dir|draft.md> [out.json]",
              file=sys.stderr)
        return 2
    src = argv[0]
    out_path = argv[1] if len(argv) > 1 else None

    if src.lower().endswith((".md", ".markdown", ".txt")):
        notes_by_id, paras, order, has_ins, has_del = parse_markdown(src)
        # markdown ids ARE the rendered labels; number by body order
        id2num = build_number_map(order)
    else:
        if src.lower().endswith(".docx"):
            zf = zipfile.ZipFile(src)
            fn_root = _load_xml(zf, "word/footnotes.xml")
            body_root = _load_xml(zf, "word/document.xml")
        else:  # unzipped directory
            fn_root = _load_xml(src, "word/footnotes.xml")
            body_root = _load_xml(src, "word/document.xml")
        notes_by_id = parse_footnotes_xml(fn_root)
        paras, order, has_ins, has_del = parse_body_xml(body_root)
        id2num = build_number_map(order)

    # Re-key footnotes by rendered number; keep the xml id for traceability.
    notes = {}
    for fid, text in notes_by_id.items():
        num = id2num.get(fid)
        if num is None:
            continue  # footnote defined but never referenced in the body
        refs = parse_refs(text)
        notes[str(num)] = {
            "number": num,
            "xml_id": fid,
            "text": text,
            "leading_id": refs["leading_id"],
            "supra": refs["supra"],
            "case_cites": refs["cases"],
        }
    notes_by_num = {int(k): v["text"] for k, v in notes.items()}

    body_quotes = find_body_quotes(paras, id2num)
    footnote_quotes = find_footnote_quotes(notes_by_num)

    # Deterministic broken-supra pass: a "Name, supra note N" whose target note
    # N does not mention Name is a renumbering break (the classic post-edit
    # error). Report candidates; the report stage confirms.
    supra_problems = []
    for k, v in notes.items():
        for s in v["supra"]:
            tgt = notes_by_num.get(s["note"], "")
            if not s["name"]:
                continue
            key = _name_key(s["name"])
            if key and key not in _surname(tgt):
                supra_problems.append({
                    "footnote": v["number"],
                    "claims": s["name"],
                    "supra_note": s["note"],
                    "target_has_name": False,
                    "target_excerpt": tgt[:160],
                })

    form = form_layer(src, notes_by_id, notes_by_num, paras, id2num, out_path)

    data = {
        "source": src,
        "form_checks": form,
        "footnote_count": len(notes),
        "body_quote_count": len(body_quotes),
        "footnote_quote_count": len(footnote_quotes),
        "unique_case_cites": sorted({c for v in notes.values() for c in v["case_cites"]}),
        "tracked_insertions": has_ins,
        "tracked_deletions": has_del,
        "supra_problem_candidates": supra_problems,
        "footnotes": notes,
        "body_quotes": body_quotes,
        "footnote_quotes": footnote_quotes,
    }
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(payload)
    summary = {k: data[k] for k in (
        "footnote_count", "body_quote_count", "footnote_quote_count",
        "tracked_insertions", "tracked_deletions")}
    summary["unique_case_cite_count"] = len(data["unique_case_cites"])
    summary["supra_problem_candidates"] = len(supra_problems)
    summary["form_findings"] = len(form["findings"])
    summary["form_short_form"] = sum(
        1 for f in form["findings"] if f["rule"] == "cite-short-form")
    summary["form_typeface"] = sum(
        1 for f in form["findings"] if f["rule"].startswith("fmt-"))
    summary["formatting_available"] = form["available"]
    summary["case_name_candidates"] = len(form["case_name_candidates"])
    if form["available"] and form["unaligned"]:
        summary["formatting_unaligned_footnotes"] = form["unaligned"]
    print(json.dumps(summary, indent=2))
    if not out_path:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
