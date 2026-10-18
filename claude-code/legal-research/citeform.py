#!/usr/bin/env python3
"""Shared citation-FORM library for /proofread and /cite-check.

Everything here is decidable from the draft alone — no external source, no
network. That is the line it sits on: `/cite-check` verifies citations against
real sources, `/proofread` reads the prose, and both of them need these checks,
so the code lives once, here, next to the other shared machinery
(`check_cite.py`, `fetch_page.py`, `md2docx.py`).

Two layers:

  * a .docx RUN-FORMATTING reader — `w:i` / `w:smallCaps` / `w:caps` resolved
    through character styles AND paragraph styles, with `w:basedOn` inheritance,
    producing a tagged parallel text (<i>…</i>, <sc>…</sc>, <caps>…</caps>)
    whose span offsets survive whitespace collapse and footnote-marker rewriting;
  * the FORM checks built on it — Bluebook typeface (R. 2.1(a)) and short forms
    (R. 10.9 for cases, R. 4.2 for secondary sources).

The rules as applied, with worked examples, are in
`bluebook-typeface-and-short-forms.md` next to this file.

Calibrated 2026-08-10 against two real drafts; see /proofread's NOTES.md for the
false-positive classes that shaped each rule. Stdlib only, importable from any
skill:

    sys.path.insert(0, os.path.expanduser("~/.claude/skills/legal-research"))
    import citeform
"""
import re
import zipfile
from xml.etree import ElementTree as ET
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FN_PLACEHOLDER = re.compile(r"\[\[FN:(-?\d+)\]\]")

def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def _ctx(text, start, end, pad=45):
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    frag = text[s:e]
    if s > 0:
        frag = "…" + frag
    if e < len(text):
        frag = frag + "…"
    return frag

# ---- .docx parsing (same approach as cite-check/extract_cites.py) ------------
# Text extraction goes through runs_spans() + clean_spans() below rather than a
# plain w:t walk, so the plain text and the formatted view are produced from one
# pass and share offsets by construction.
def _load_xml(source, member):
    if isinstance(source, zipfile.ZipFile):
        with source.open(member) as f:
            return ET.parse(f).getroot()
    return ET.parse(source + "/" + member).getroot()

# ---- run-level formatting (.docx only) ---------------------------------------
# Word carries italics / small caps / all-caps as run properties that may be set
# on the run itself (w:rPr), on a character style the run names (w:rStyle), or on
# the PARAGRAPH's style. Resolving all three is what makes typeface checkable —
# and it is the only way to know that a Part header stored as the mixed-case text
# "understanding temporalism" actually prints as ALL CAPS because the Heading1
# style carries <w:caps/>. Without it, proofers waste findings second-guessing
# the capitalization of words the reader never sees in that case.
FMT_PROPS = ("i", "smallCaps", "caps")
_FMT_TAG = {"i": "i", "smallCaps": "sc", "caps": "caps"}
TAG_RE = re.compile(r"</?(?:i|sc|caps)>")


def strip_tags(s):
    return TAG_RE.sub("", s or "")


def _toggle(rpr, name):
    """Word toggle property: <w:i/> = on, <w:i w:val="0"/> = off, absent = inherit."""
    if rpr is None:
        return None
    el = rpr.find(W + name)
    if el is None:
        return None
    v = el.get(W + "val")
    return True if v is None else v not in ("0", "false", "off")


def parse_styles(root):
    """{styleId: {prop: bool|None}} with w:basedOn inheritance resolved."""
    raw = {}
    for st in root.findall(W + "style"):
        sid = st.get(W + "styleId")
        if not sid:
            continue
        based = st.find(W + "basedOn")
        raw[sid] = (based.get(W + "val") if based is not None else None,
                    {p: _toggle(st.find(W + "rPr"), p) for p in FMT_PROPS})
    out = {}

    def resolve(sid, seen):
        if sid in out:
            return out[sid]
        if sid not in raw or sid in seen:
            return {p: None for p in FMT_PROPS}
        base_id, own = raw[sid]
        props = dict(resolve(base_id, seen | {sid})) if base_id else \
            {p: None for p in FMT_PROPS}
        for p, v in own.items():
            if v is not None:
                props[p] = v
        out[sid] = props
        return props

    for sid in list(raw):
        resolve(sid, set())
    return out


def runs_spans(el, styles, para_style):
    """[(text, frozenset(active props))] in document order — same text stream as
    runs_text() (tracked deletions skipped, footnote refs as [[FN:id]])."""
    base = styles.get(para_style or "", {}) if styles else {}
    cur = frozenset(p for p in FMT_PROPS if base.get(p))
    spans = []
    for node in el.iter():
        if node.tag == W + "r":
            props = {p: base.get(p) for p in FMT_PROPS}
            rpr = node.find(W + "rPr")
            if rpr is not None:
                rs = rpr.find(W + "rStyle")
                if rs is not None:
                    cs = styles.get(rs.get(W + "val"), {})
                    for p in FMT_PROPS:
                        if cs.get(p) is not None:
                            props[p] = cs[p]
                for p in FMT_PROPS:
                    v = _toggle(rpr, p)
                    if v is not None:
                        props[p] = v
            cur = frozenset(p for p in FMT_PROPS if props.get(p))
        elif node.tag == W + "delText":
            continue
        elif node.tag == W + "t":
            spans.append((node.text or "", cur))
        elif node.tag == W + "footnoteReference":
            spans.append(("[[FN:%s]]" % node.get(W + "id"), frozenset()))
        elif node.tag == W + "tab":
            spans.append((" ", frozenset()))
    return spans


def clean_spans(spans):
    """Collapse whitespace exactly as _clean() does and return
    (clean_text, [(start, end, props)]) with offsets into clean_text. Offsets are
    computed through the collapse rather than by re-matching, so the formatted
    view and the plain view can never drift apart."""
    raw = "".join(t for t, _ in spans)
    keep, idx, prev_space = [], {}, True
    for i, ch in enumerate(raw):
        if ch.isspace():
            if not prev_space:
                keep.append(" ")
                prev_space = True
            idx[i] = max(0, len(keep) - 1)
        else:
            keep.append(ch)
            idx[i] = len(keep) - 1
            prev_space = False
    while keep and keep[-1] == " ":
        keep.pop()
    clean = "".join(keep)
    out, pos = [], 0
    for t, props in spans:
        s, e = pos, pos + len(t)
        pos = e
        if not props or not t.strip():
            continue
        first = next((j for j in range(s, e) if not raw[j].isspace()), None)
        last = next((j for j in range(e - 1, s - 1, -1) if not raw[j].isspace()), None)
        if first is None or last is None:
            continue
        a, b = min(idx[first], len(clean)), min(idx[last] + 1, len(clean))
        if b > a:
            out.append((a, b, props))
    merged = []
    for a, b, props in out:
        if merged and merged[-1][2] == props and a <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b), props)
        else:
            merged.append((a, b, props))
    return clean, merged


def shift_spans(text, spans, id2num):
    """Re-base span offsets after [[FN:id]] placeholders are rendered [FN#n].
    Placeholder runs never carry formatting, so no span straddles an edit."""
    edits = [(m.start(), m.end(), len("[FN#%s]" % id2num.get(m.group(1), "?")))
             for m in FN_PLACEHOLDER.finditer(text)]
    if not edits:
        return spans

    def mv(pos):
        d = 0
        for s, e, nl in edits:
            if e <= pos:
                d += nl - (e - s)
        return pos + d
    return [(mv(a), mv(b), p) for a, b, p in spans]


def render_marked(clean, spans):
    """The passage with <i>/<sc>/<caps> tags inserted at span boundaries."""
    if not spans:
        return clean
    pieces, pos = [], 0
    for a, b, props in spans:
        if a < pos:
            continue
        tags = [_FMT_TAG[p] for p in FMT_PROPS if p in props]
        pieces.append(clean[pos:a])
        pieces.append("".join("<%s>" % t for t in tags))
        pieces.append(clean[a:b])
        pieces.append("".join("</%s>" % t for t in reversed(tags)))
        pos = b
    pieces.append(clean[pos:])
    return "".join(pieces)


def prop_ratio(spans, start, end, prop):
    """Fraction of characters in [start, end) carrying `prop`."""
    if end <= start:
        return 0.0
    hit = 0
    for a, b, props in spans:
        if prop in props:
            hit += max(0, min(b, end) - max(a, start))
    return hit / float(end - start)

CAPTION_CITE = re.compile(
    r"([A-Z][\w.'’]*(?:\s(?:[A-Z&][\w.'’]*|of|the|ex|rel\.)){0,6}\sv\.\s"
    r"[A-Z][\w.'’]*(?:\s(?:[A-Z&][\w.'’]*|of|the)){0,5}),\s+"
    r"(\d{1,4})\s+(U\.\s?S\.|S\.\s?Ct\.|F\.(?:\s?(?:2d|3d|4th))?|F\.\s?Supp\.(?:\s?[23]d)?)\s+"
    # optional parallel nominative reporter — "3 U.S. (3 Dall.) 171". Without
    # this the whole cite went unparsed, so every later "Hylton, 3 U.S. at 174"
    # looked like a short form with no antecedent (2026-08-10 calibration).
    r"(?:\([^)]{1,24}\)\s+)?(\d{1,5})")

# Leading signal words the caption regex can swallow ("See Florida v. Jardines").
# They must be stripped before keying, or the same case cited once with a signal
# and once without gets two different keys and the inconsistency check goes
# blind — exactly how Jardines-as-509-vs-569 slipped through on 2026-07-14.
_CAPTION_SIGNALS = {"see", "but", "cf", "eg", "e", "g", "accord", "contra",
                    "compare", "also", "generally", "and", "in", "citing",
                    "quoting", "with"}


def _caption_key(raw):
    words = re.sub(r"[^a-z ]", "", raw.lower()).split()
    while words and words[0] in _CAPTION_SIGNALS:
        words.pop(0)
    return " ".join(words)

# ---- short forms (Bluebook R. 4.2 / R. 10.9 — internal, no source needed) ---------
# Added 2026-08-10 after reader feedback: a draft that cites the same case or
# article at FULL length twice in short order should use the short form, and a
# short form stranded far from its full cite should be re-expanded. Both are
# decidable from the draft alone, which is why they live here and not in
# /cite-check (whose scope is verification against real sources).
#
# The rules, written down because nobody remembers them:
#   * CASES (R. 10.9): a short form ("Marbury, 5 U.S. at 177") is proper if the
#     case was cited in full in the SAME footnote or one of the PRECEDING FIVE
#     footnotes. Inside that window a second full cite is the error. Outside it,
#     repeating the full citation is CORRECT — so a repeat >5 notes later is not
#     flagged, and a short form >5 notes after its full cite is.
#   * SECONDARY SOURCES (R. 4.2): after one full citation, every later reference
#     is "Author, supra note N, at X" — there is no five-footnote window, so any
#     second full cite of the same article/book is flagged wherever it appears.
#   * Cases and statutes do NOT take "supra"; secondary sources do.
_REPORTER_ALT = (r"U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|"
                 r"F\.(?:\s?(?:2d|3d|4th))?|F\.\s?Supp\.(?:\s?[23]d)?")
SHORT_CASE = re.compile(
    r"\b([A-Z][\w.'’\-]+(?:\s+[A-Z][\w.'’\-]+){0,3}),\s+\d{1,4}\s+(?:%s)\s+at\s+\d"
    % _REPORTER_ALT)
# "Author, Title, 97 Harv. L. Rev. 1513" — a full secondary-source citation.
SECONDARY_FULL = re.compile(
    r"([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){0,3}),\s+"      # author(s)
    r"([A-Z][^,;()]{8,90}?),\s+"                                     # title
    # journal: "Harv. L. Rev.", "Wm. & Mary L. Rev." — the ampersand stands
    # alone, and "Mary" carries no period, so neither an all-[A-Z] nor a
    # period-required token pattern matches; a period is required of the whole
    # journal name instead (checked by the caller).
    r"(\d{1,4})\s+((?:(?:[A-Z][\w.'’]*\.?|&)\s+){1,8})(\d{1,5})\b")  # vol journal page
_CASE_WINDOW = 5   # Bluebook's "preceding five footnotes"


def _first_party_token(caption):
    """The word a Bluebook short form actually uses — the last word of the first
    party ("Knowlton v. Moore" -> knowlton, "Free Enter. Fund v. PCAOB" -> fund).
    Short forms are resolved against the FIRST token of the first party, which
    also lets a draft's own "Pollock II" style resolve to "Pollock v. Farmers'
    Loan": deliberately loose, so the check errs toward silence."""
    first = _caption_key(caption).split(" v ")[0].split()
    return first[0] if first else ""


def _secondary_key(author, title):
    a = re.sub(r"[^a-z]", "", author.split()[-1].lower()) if author.split() else ""
    t = " ".join(re.sub(r"[^a-z ]", "", title.lower()).split()[:5])
    return a + "|" + t


def short_form_lint(notes, cap=30):
    """Repeated full citations that should be short forms, and short forms
    stranded past the five-footnote window."""
    out = []
    # Pre-pass: the FIRST footnote in which each case appears in full, keyed by
    # first-party token. A short form is only an orphan if the document has no
    # full cite of that case at all, or has one only LATER (moved-footnote
    # residue) — that needs whole-document knowledge before the walk starts.
    first_full = {}
    for num in sorted(notes):
        for m in CAPTION_CITE.finditer(notes[num]):
            party = _first_party_token(m.group(1))
            if party and party not in first_full:
                first_full[party] = num
    last_full_case, last_full_sec, last_full_party = {}, {}, {}
    for num in sorted(notes):
        t = notes[num]
        for m in CAPTION_CITE.finditer(t):
            key = _caption_key(m.group(1))
            if not key:
                continue
            party = _first_party_token(m.group(1))
            if party:
                last_full_party[party] = num
            prev = last_full_case.get(key)
            if prev is not None and prev != num and num - prev <= _CASE_WINDOW:
                short = m.group(1).split(" v. ")[0].split()[-1]
                out.append({
                    "rule": "cite-short-form",
                    "location": {"where": "footnote", "note": num},
                    "find": _ctx(t, m.start(), m.end()), "exact": m.group(0),
                    "problem": "full citation repeated — this case was already cited in full at note %d, %d note%s earlier, so Bluebook R. 10.9 calls for the short form"
                               % (prev, num - prev, "" if num - prev == 1 else "s"),
                    "fix": "use the short form (e.g. \"%s, %s %s at <pin>\")"
                           % (short, m.group(2), re.sub(r"\s", "", m.group(3))),
                    "severity": "likely"})
            last_full_case[key] = num
        for m in SHORT_CASE.finditer(t):
            party = _first_party_token(m.group(1) + " v. x")
            if not party:
                continue
            first, prev = first_full.get(party), last_full_party.get(party)
            if first is None or first > num:
                # A short form before the case is ever cited in full — usually
                # renumbering residue from a moved footnote. (Real instance in
                # the 2026-08-10 calibration: n.9 short-cites Free Enter. Fund,
                # whose only full cite is n.11.)
                out.append({
                    "rule": "cite-short-form",
                    "location": {"where": "footnote", "note": num},
                    "find": _ctx(t, m.start(), m.end()), "exact": m.group(0),
                    "problem": "short-form cite %s — the reader has nothing to short-cite back to"
                               % ("whose full citation does not appear until note %d" % first
                                  if first else "with no full citation of this case anywhere in the footnotes"),
                    "fix": "give the full citation here (or check whether a footnote moved)",
                    "severity": "likely"})
                continue
            if prev is None or num - prev <= _CASE_WINDOW:
                continue
            out.append({
                "rule": "cite-short-form",
                "location": {"where": "footnote", "note": num},
                "find": _ctx(t, m.start(), m.end()), "exact": m.group(0),
                "problem": "short-form cite %d notes after the last full citation (note %d) — past Bluebook R. 10.9's five-footnote window, the reader can no longer find the full cite"
                           % (num - prev, prev),
                "fix": "repeat the full citation here (or add \"supra note %d\")" % prev,
                "severity": "likely"})
        for m in SECONDARY_FULL.finditer(t):
            author, title, journal = m.group(1), m.group(2), m.group(4)
            if " v. " in author or " v. " in title or len(title.split()) < 2:
                continue
            if not re.search(r"[a-z]", title) or "." not in journal:
                continue
            key = _secondary_key(author, title)
            prev = last_full_sec.get(key)
            if prev is not None and prev != num:
                out.append({
                    "rule": "cite-short-form",
                    "location": {"where": "footnote", "note": num},
                    "find": _ctx(t, m.start(), m.end()), "exact": m.group(0),
                    "problem": "full citation repeated — this source was already cited in full at note %d; secondary sources take the supra short form from their second appearance on (Bluebook R. 4.2)"
                               % prev,
                    "fix": "use \"%s, supra note %d, at <pin>\"" % (author.split()[-1], prev),
                    "severity": "likely"})
            else:
                last_full_sec[key] = num
        if len(out) >= cap:
            break
    return out[:cap]

# ---- typeface / italics (needs the .docx formatting layer) -----------------------
# Bluebook typeface for law review FOOTNOTES (R. 2.1(a), B2), the part everyone
# has to look up every time:
#   * italic: introductory signals (See, See also, Cf., Compare/with, But see,
#     See generally, Accord, Contra, E.g.), "Id.", "supra", "infra",
#     "hereinafter", explanatory phrases that introduce a parenthetical
#     ("quoting", "citing"), and subsequent-history phrases ("aff'd", "rev'd",
#     "cert. denied", "overruled by");
#   * italic: case names in TEXTUAL sentences (body text, and textual sentences
#     inside footnotes) and in SHORT-FORM citations;
#   * ROMAN: case names in FULL citations sitting in a citation clause/sentence
#     of a footnote — the rule most drafts get backwards;
#   * ROMAN: everything around the italicized bit — the "note 3" after an
#     italicized "supra", the "at" of a short form, and the comma or period that
#     follows an italicized case name.
_ITALIC_MIN = 0.6   # a span counts as italicized above this character fraction
_ROMAN_MAX = 0.4    # …and as roman below it

SIGNAL_ITALIC = re.compile(
    r"(?:^|(?<=[.;]\s)|(?<=\())\s*"
    r"(But see, e\.g\.,|But see also|But see|But cf\.|See, e\.g\.,|See also, e\.g\.,|"
    r"See also|See generally|See|Cf\.|Compare|Accord|Contra|E\.g\.,)(?=[\s,]|$)")
ID_ITALIC = re.compile(r"(?:^|(?<=[.;]\s)|(?<=\())\s*(Id\.)(?=[\s,]|$)")
# "hereinafter" is deliberately NOT here: in law review footnotes it is roman —
# "[hereinafter <i>Hearings</i>]" (Bluebook R. 4.2(b); Georgetown Writing Center,
# "Differences in Citation in Scholarly and Practitioner Legal Writing" (2026), § III.A).
# Likewise "(quoting …)"/"(citing …)" are roman in Whitepages style (R. 1.5(b), 10.6.3
# examples); italicizing them is the Bluepages/practitioner convention. Both rules fired
# 11 false positives on the 2026-10-07 HLR run and were removed — see proofread/NOTES.md.
LATIN_ITALIC = re.compile(r"\b(supra|infra)\b")
HIST_ITALIC = re.compile(
    r"\b(aff'd|aff’d|rev'd|rev’d|cert\. denied|cert\. granted|overruled by|"
    r"abrogated by|superseded by)")
NOTE_ROMAN = re.compile(r"\b(?:supra|infra)\s+(notes?\s+\d+(?:\s*[–—-]\s*\d+)?)")
AT_ROMAN = re.compile(r",\s+(at)\s+\d")
_PARTY_WORD = (r"(?:[A-Z&][\w.'’\-]*|,\s+(?:Inc|LLC|Co|Corp|Ltd|N\.A|L\.P)\.?|"
               r"of|for|ex|rel\.|"
               # "the" only inside a party name, never the prose "the Court"
               r"the(?!\s+(?:Court|Justices?|Constitution|Congress|Government|"
               r"Chief|Framers|Founders|majority|dissent)\b))")
CASE_NAME_FMT = re.compile(
    r"\b([A-Z][\w.'’\-]*(?:\s*%s){0,7}\s+v\.\s+[A-Z][\w.'’\-]*(?:\s*%s){0,7})"
    % (_PARTY_WORD, _PARTY_WORD))
FULL_CITE_TAIL = re.compile(r"^,\s+\d{1,4}\s+[A-Z]")
# Signals the case-name regex can swallow, and the clause openers that mark a
# name as starting a CITATION clause rather than sitting inside a sentence.
_LEAD_SIGNAL = re.compile(
    r"^(?:But\s+)?(?:See|Cf\.|Compare|Accord|Contra|E\.g\.|see|cf\.)"
    r"(?:\s+(?:also|generally|e\.g\.,))*[\s,]+")
# A citation clause opener sitting immediately before the name: a bare signal
# ("See, e.g.,"), an explanatory phrase ("(quoting"), or the ";/and" that strings
# one cite onto the next inside a citation sentence.
_PURE_SIGNAL_TAIL = re.compile(
    r"(?:^|[.;)]\s|\A)\s*(?:(?:But|but)\s+)?"
    r"(?:See|see|Cf\.|cf\.|Compare|compare|Accord|accord|Contra|contra|E\.g\.|"
    r"quoting|citing|with)"
    r"(?:\s+(?:also|generally))?(?:,\s*e\.g\.)?,?\s*(?:and\s+)?$")
_CITE_STRING_TAIL = re.compile(
    r"(?:(?:\)[;,]?|;)\s*(?:and|see\s+also)?|\b(?:quoting|citing))\s*$")
# Court-document citations ("Brief for the United States at 46, Moore v. …",
# "Transcript of Oral Argument, Moore v. …"): the typeface conventions there are
# their own tangle (R. 10.8.3), so this pass stays out of them entirely.
_COURT_DOC = re.compile(
    r"\b(Brief|Br\.|Petition|Pet\.|Transcript|Tr\.|Motion|Reply|Response|"
    r"Complaint|Record|Oral Argument|Amicus)\b")


def classify_case_name(text, start, end):
    """('full'|'short'|'textual'|None, name_start) for a case name at
    [start, end). A name inside a TEXTUAL sentence is italicized even when its
    full citation follows inline (R. 2.1(a)) — the distinction that made eight
    of nine first-pass findings on the calibration draft false positives."""
    lead = _LEAD_SIGNAL.match(text[start:end])
    ns = start + lead.end() if lead else start
    if ns >= end:
        return None, start
    pre = text[:ns].rstrip()
    clause = re.split(r"(?<![A-Z])[.;]\s", text[max(0, ns - 240):ns])[-1]
    if _COURT_DOC.search(clause):
        return None, ns
    if (not pre or pre[-1] in ".;:("
            or _PURE_SIGNAL_TAIL.search(pre[-40:])
            or _CITE_STRING_TAIL.search(pre[-24:])):
        # starts its own citation clause
        return ("full" if FULL_CITE_TAIL.match(text[end:end + 30]) else "short"), ns
    return "textual", ns
# A signal word only counts as a signal if a citation follows it soon after.
_CITE_FOLLOWS = re.compile(r"\d\s+[A-Z]|supra|infra|\bat\s+\d")


def _mark(text, m, group, rule, problem, fix, loc, severity="likely"):
    return {"rule": rule, "location": loc,
            "find": _ctx(text, m.start(group), m.end(group)),
            "exact": m.group(group), "problem": problem, "fix": fix,
            "severity": severity}


def typeface_lint(text, spans, loc, in_footnote):
    """Deterministic italicization checks over one passage. `spans` are the
    formatting spans for `text` (offsets already rendered)."""
    out = []
    ital = lambda a, b: prop_ratio(spans, a, b, "i")

    if in_footnote:
        for pat, label in ((SIGNAL_ITALIC, "introductory signal"),
                           (ID_ITALIC, '"Id."')):
            for m in pat.finditer(text):
                if pat is SIGNAL_ITALIC and not _CITE_FOLLOWS.search(
                        text[m.end(1):m.end(1) + 90]):
                    continue  # an ordinary English "See"/"Compare", not a signal
                if ital(m.start(1), m.end(1)) < _ITALIC_MIN:
                    out.append(_mark(text, m, 1, "fmt-signal-roman",
                                     "%s %r is not italicized (Bluebook R. 2.1(a) italicizes signals in footnotes)"
                                     % (label, m.group(1)),
                                     "italicize %r" % m.group(1), loc))
        for m in HIST_ITALIC.finditer(text):
            if ital(m.start(1), m.end(1)) < _ITALIC_MIN:
                out.append(_mark(text, m, 1, "fmt-signal-roman",
                                 "subsequent-history phrase %r is not italicized" % m.group(1),
                                 "italicize %r" % m.group(1), loc))
    for m in LATIN_ITALIC.finditer(text):
        if ital(m.start(1), m.end(1)) < _ITALIC_MIN:
            out.append(_mark(text, m, 1, "fmt-signal-roman",
                             "%r is not italicized (it always is, in text and in footnotes)"
                             % m.group(1),
                             "italicize %r" % m.group(1), loc))
    for m in NOTE_ROMAN.finditer(text):
        if ital(m.start(1), m.end(1)) > _ROMAN_MAX:
            out.append(_mark(text, m, 1, "fmt-over-italicized",
                             "%r is italicized — only the \"supra\"/\"infra\" is italic, the note reference is roman"
                             % m.group(1),
                             "un-italicize %r, keeping the supra/infra italic" % m.group(1),
                             loc))
    for m in AT_ROMAN.finditer(text):
        if ital(m.start(1), m.end(1)) > _ROMAN_MAX:
            out.append(_mark(text, m, 1, "fmt-over-italicized",
                             'the "at" of a short-form cite is italicized; it should be roman',
                             'un-italicize "at"', loc))
    # Italic spilling onto the comma that separates a name from its citation.
    # Narrow deliberately: only a trailing COMMA followed by a volume number.
    # A trailing period is usually the period of an abbreviation that genuinely
    # belongs inside the italics ("See, e.g.," / "Free Enter. Fund"), and the
    # first calibration run flagged five of those before this guard went in.
    for a, b, props in spans:
        if "i" not in props or b - a < 8 or text[b - 1] != ",":
            continue
        if not re.match(r"\s*\d{1,4}\s+[A-Z]", text[b:b + 12]):
            continue
        out.append({"rule": "fmt-over-italicized", "location": loc,
                    "find": _ctx(text, max(a, b - 40), b), "exact": text[a:b][-30:],
                    "problem": "the comma after the italicized name/title is inside the italics; punctuation separating a name or title from its citation is roman",
                    "fix": "move the comma outside the italics",
                    "severity": "likely"})
    # Small caps applied across a word boundary — "amend<sc>. XXII</sc>" and
    # "<sc>, §§ 2-3.</sc>" are drag-select accidents, invisible in plain text.
    for a, b, props in spans:
        if "smallCaps" not in props:
            continue
        for edge, pos in (("starts", a), ("ends", b)):
            nb = text[pos - 1] if edge == "starts" and pos > 0 else (
                text[pos] if edge == "ends" and pos < len(text) else "")
            inside = text[pos] if edge == "starts" else (text[pos - 1] if pos else "")
            if nb.isalnum() and inside.isalnum():
                out.append({"rule": "fmt-partial-small-caps", "location": loc,
                            "find": _ctx(text, max(0, a - 15), min(len(text), b + 15)),
                            "exact": text[a:b][:40],
                            "problem": "small caps %s mid-word (%r) — the run boundary falls inside a word, so the printed page shows a hybrid"
                                       % (edge, text[max(0, a - 6):b][:30]),
                            "fix": "extend or trim the small-caps run to whole words",
                            "severity": "likely"})
                break
    return out


def case_name_typeface(paras, notes, para_spans, note_spans, cap=40):
    """Case-name italicization: an INVENTORY plus counts, not findings.

    Whether a case name sits in a textual sentence (italic) or in a citation
    clause (roman, R. 2.1(a)) is a reading judgment — the 2026-08-10 calibration
    run showed a regex getting it wrong eight times out of nine on real
    footnotes, because "See, e.g., X v. Y", "(quoting X v. Y", "); and X v. Y"
    and "in the early case X v. Y" all look alike to a pattern. So the script
    classifies as best it can and hands every apparent deviation to the typeface
    agent, which reads the sentence. Only a UNIFORM contrary practice — nothing
    to adjudicate, one global find-and-replace — is asserted here, as a
    convention rather than as findings."""
    buckets = {"full": [], "short": [], "textual": [], "body": []}
    for p in paras:
        if p.get("toc") or p["heading"]:
            continue
        sp = para_spans.get(p["id"], [])
        for m in CASE_NAME_FMT.finditer(p["text"]):
            kind, ns = classify_case_name(p["text"], m.start(1), m.end(1))
            if kind is None:
                continue
            buckets["body"].append(
                (("body", p["id"]), p["text"][ns:m.end(1)],
                 prop_ratio(sp, ns, m.end(1), "i"),
                 _ctx(p["text"], ns, m.end(1))))
    for num in sorted(notes):
        t, sp = notes[num], note_spans.get(num, [])
        for m in CASE_NAME_FMT.finditer(t):
            kind, ns = classify_case_name(t, m.start(1), m.end(1))
            if kind is None:
                continue
            buckets[kind].append((("footnote", num), t[ns:m.end(1)],
                                  prop_ratio(sp, ns, m.end(1), "i"),
                                  _ctx(t, ns, m.end(1))))
    inventory, conventions, counts = [], [], {}
    # Rule 2.1(a) expectations: only full cites standing in a citation clause of
    # a footnote are roman; everything else — short forms, textual uses inside a
    # footnote, and body text — is italic.
    want_italic = {"full": False, "short": True, "textual": True, "body": True}
    label = {"full": "case names in full citations in footnotes",
             "short": "short-form case names in footnotes",
             "textual": "case names used in textual sentences of footnotes",
             "body": "case names in body text"}
    for kind, items in buckets.items():
        italic = [x for x in items if x[2] >= _ITALIC_MIN]
        roman = [x for x in items if x[2] <= _ROMAN_MAX]
        counts[kind] = {"total": len(items), "italicized": len(italic),
                        "roman": len(roman), "bluebook_wants":
                        "italic" if want_italic[kind] else "roman"}
        if len(items) < 3:
            continue
        deviant = roman if want_italic[kind] else italic
        if not deviant:
            continue
        if len(deviant) == len(items):
            # nothing to adjudicate — the draft is uniform, just uniformly the
            # other way; one global change, so state it once and make no findings
            conventions.append({
                "issue": "italicization of %s" % label[kind],
                "dominant": "%s, all %d instances"
                            % ("italicized" if not want_italic[kind] else "roman", len(items)),
                "minority": "none — the draft is internally consistent",
                "recommendation": "Bluebook R. 2.1(a) puts %s in %s. The draft is uniform the other way, so this is one global find-and-replace — or a deliberate house style, and the journal will impose its own."
                                  % (label[kind], "italics" if want_italic[kind] else "roman type")})
            continue
        conventions.append({
            "issue": "italicization of %s" % label[kind],
            "dominant": "%s (%d instances)"
                        % ("italicized" if want_italic[kind] else "roman",
                           len(items) - len(deviant)),
            "minority": "%s (%d instances)"
                        % ("roman" if want_italic[kind] else "italicized", len(deviant)),
            "recommendation": "the draft is inconsistent here; Bluebook R. 2.1(a) puts %s in %s"
                              % (label[kind], "italics" if want_italic[kind] else "roman type")})
        for (where, n), name, ratio, ctx in deviant[:cap]:
            inventory.append({
                "kind": kind, "location": "n.%d" % n if where == "footnote" else "¶%d" % n,
                "name": name, "observed": "roman" if ratio <= _ROMAN_MAX else "italic",
                "expected_if_%s" % kind: "italic" if want_italic[kind] else "roman",
                "context": ctx})
    return inventory, conventions, counts

