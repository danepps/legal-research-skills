#!/usr/bin/env python3
"""Deterministic screening aids, not citation-form lint or final source resolution.

Adapted from the Claude implementation; the lead confirms each field on the
Codex citation unit. Unknown prose is retained rather than silently discarded.
"""
import argparse
import json
import re
from pathlib import Path
from extract_cites import REPORTER as REPORTER_ANY, CASE_CITE, normalize as _clean

_SIGNAL_AFTER_PERIOD = re.compile(
    r"(?<!\bcf)(?<!\be\.g)\.\s+(?=(?:See|Cf\.|But\s+(?:see|cf\.)|Compare|Accord|Contra|"
    r"E\.g\.,|Id\.)[\s,])")


_SENTENCE_AFTER_CITE = re.compile(r"(?<=[)\d])\.\s+(?=[A-Z*_])")

_PAREN = re.compile(r"\([^()]*\)")
JOURNAL = re.compile(r"\b(\d{1,4})\s+((?:[A-Z][A-Za-z'&]*\.?\s+){1,7}?)(\d{1,5})\b")

def outside(text, end):
    depth, quote = 0, []
    for ch in text[:end]:
        if ch == '“': quote.append(ch)
        elif ch == '”' and quote: quote.pop()
        elif ch == '"':
            if quote and quote[-1] == '"': quote.pop()
            else: quote.append(ch)
        elif not quote:
            if ch == '(': depth += 1
            elif ch == ')': depth = max(0, depth - 1)
    return not depth and not quote


def _depth_split(text, sep=";"):
    """Split only at top-level separators outside nested double quotations."""
    parts, start, depth, quotes = [], 0, 0, []
    for index, ch in enumerate(text):
        if ch == '“': quotes.append(ch)
        elif ch == '”' and quotes: quotes.pop()
        elif ch == '"':
            if quotes and quotes[-1] == '"': quotes.pop()
            else: quotes.append(ch)
        elif not quotes:
            if ch == '(': depth += 1
            elif ch == ')': depth = max(0, depth - 1)
            elif ch == sep and not depth:
                parts.append(text[start:index])
                start = index + 1
    parts.append(text[start:])
    return parts


def _signal_split(clause):
    """Split at ". See ..." style breaks that sit outside parentheses."""
    out, start = [], 0
    breaks = sorted({(m.start(), m.end()) for pat in (_SIGNAL_AFTER_PERIOD, _SENTENCE_AFTER_CITE)
                     for m in pat.finditer(clause)})
    for left, right in breaks:
        if not outside(clause, left):
            continue  # inside a parenthetical
        out.append(clause[start:left + 1])
        start = right
    out.append(clause[start:])
    return out


def _split_compare_with(clause):
    # Keep draft text verbatim: the second fragment starts with the actual "with".
    if not re.match(r"^[*_]*compare\b", clause, re.I):
        return [clause]
    for match in re.finditer(r"\bwith\s+", clause, re.I):
        if outside(clause, match.start()):
            left, right = clause[:match.start()].rstrip(" ,"), clause[match.start():].strip()
            if left and right:
                return [left, right]
    return [clause]


def split_clauses(text):
    text = re.sub(r"^\s*\.?\s*", "", text or "")  # Word's leading ". "
    clauses = []
    for part in _depth_split(text):
        for c in _signal_split(part):
            c = c.strip()
            if c:
                clauses.extend(_split_compare_with(c))
    return clauses


def _strip_parens(s):
    prev = None
    while prev != s:
        prev, s = s, _PAREN.sub(" ", s)
    return s


SIGNAL_PATTERN = (r"see,?\s+e\.g\.,?|see\s+also|see\s+generally|but\s+see|but\s+cf\.|"
                  r"cf\.|see|compare\s+with|compare|with|accord|contra|e\.g\.,?")
SIGNAL_RE = re.compile(r"^(" + SIGNAL_PATTERN + r")(?=[\s,])", re.I)
SIGNAL_INNER = re.compile(r"\b(" + SIGNAL_PATTERN + r")(?=[\s,])", re.I)


def signal_of(clause):
    text = re.sub(r"[*_]", "", clause or "").strip()
    match = SIGNAL_RE.match(text)
    if not match:
        match = next((m for m in SIGNAL_INNER.finditer(text)
                      if outside(text, m.start()) and not re.search(r"\d", text[:m.start()])), None)
    if not match:
        return ""
    signal = re.sub(r"\s+", " ", match.group(1).lower()).rstrip(",")
    if signal == "with": return "compare with"
    return "see, e.g." if signal.replace(",", "") == "see e.g." else signal


_PIN_TAIL = (r"(\d{1,4}(?:\s*[–-]\s*\d{1,4})?(?:\s*(?:&|,)\s*\d{1,4}(?:\s*[–-]\s*\d{1,4})?)*"
             r"(?:\s*(?:&\s*)?nn?\.\s*\d+(?:\s*[–-]\s*\d+)?)?)")
AT_PIN = re.compile(r"(?:(?<=[,.])|^)\s*at\s+" + _PIN_TAIL)
CASE_PIN = re.compile(r"\b\d{1,4}\s+(?:%s)\s+(?:\([^)]{1,24}\)\s+)?\d{1,4},\s*" % REPORTER_ANY
                      + _PIN_TAIL)
SECTION_PIN = re.compile(r"§§?\s*[\w.\-–]+(?:\([\w]+\))*")
RULE_PIN = re.compile(r"\bR\.\s+(?:[A-Z][a-z]*\.\s+)*(\d+[A-Za-z]?(?:\([\w]+\))*)")
USC_PIN = re.compile(r"U\.\s?S\.\s?C\.\s+(\d+[A-Za-z]?(?:[\-–]\d+)?(?:\([\w]+\))*)")
STATUTE = re.compile(r"U\.\s?S\.\s?C\.|C\.\s?F\.\s?R\.|§|Fed\.\s+R\.|\bR\.\s+\d")
PARA_PIN = re.compile(r"¶¶?\s*\d+(?:\s*[–-]\s*\d+)?")
BOOK_PIN = re.compile(r"(?<!No\.)(?<!no\.)(?<!Vol\.)(?<!vol\.)\s" + _PIN_TAIL + r"\s*\((?=[^()]*\d{4}\))")


def locate(clause, kind):
    """The pincite / locator this instance points at, as printed ("431", "820–21",
    "§ 1983", "¶ 12"), or "" for a whole-work cite. A whole-work cite is the one the
    support pass cannot read at a page, so the distinction drives its scope."""
    outer = _strip_parens(clause)
    m = AT_PIN.search(outer)
    if m:
        return _clean(m.group(1))
    if kind in ("case", "case-short"):
        m = CASE_PIN.search(outer)
        if m:
            return _clean(m.group(1))
    if kind in {"statute", "rule"} or "§" in outer:
        m = SECTION_PIN.search(clause)
        if m: return _clean(m.group(0)).rstrip(".")
        m = RULE_PIN.search(clause) or USC_PIN.search(clause)
        return _clean(m.group(1)) if m else ""
    m = PARA_PIN.search(outer)
    if m:
        return _clean(m.group(0))
    if kind == "article":
        jm = JOURNAL.search(outer)
        if jm:
            m = re.compile(r",\s*" + _PIN_TAIL).match(outer, jm.end())
            if m:
                return _clean(m.group(1))
    if kind == "book":
        m = BOOK_PIN.search(clause)
        if m:
            return _clean(m.group(1))
    return ""


def parentheticals(clause):
    """Top-level parenthetical contents, in order."""
    out, depth, start = [], 0, None
    for i, ch in enumerate(clause or ""):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(clause[start + 1:i])
                start = None
    return out


# Parentheticals that are not a proposition: quoting/citing, emphasis/alteration notes,
# edition/editor/translator, file and access notes, docket numbers, and anything that
# ENDS in a year (court/date "(S.D.N.Y. Mar. 3, 2020)", "(last visited Jan. 5, 2020)",
# "(Jacob E. Cooke ed., 1961)"). A proposition parenthetical starts with a verb.
_NON_PROP = re.compile(
    r"^(?:quoting|citing|cited|emphasis|alterations?|internal|footnotes?|citations?|en\s+banc|"
    r"per\s+curiam|plurality|hereinafter|on\s+file|available|archived|codified|as\s+amended|"
    r"repealed|superseded|reprinted|forthcoming|unpublished|manuscript|draft|"
    r"last\s+(?:visited|updated|modified)|accessed|testimony|No\.\s*\d|\d{4}\b|"
    r"\d+(?:st|d|th)?\s+ed\.|(?:[A-Z]\.\s*)*[A-Z][\w.'’\s]*(?:ed|eds|trans)\.?,?\s+\d{4})",
    re.IGNORECASE)
_YEAR_END = re.compile(r"\b(?:1[5-9]|20)\d{2}\.?$")
_PROP_START = re.compile(
    r"^(?:holding|noting|finding|concluding|explaining|arguing|observing|stating|describing|"
    r"rejecting|recognizing|applying|reasoning|suggesting|discussing|adopting|declining|"
    r"affirming|reversing|upholding|striking|interpreting|construing|reading|treating|assuming|"
    r"acknowledging|emphasizing|ruling|deciding|reaffirming|distinguishing|limiting|extending|"
    r"requiring|permitting|allowing|announcing|establishing|defining|listing|surveying|"
    r"reviewing|summarizing|tracing|questioning|criticizing|defending|proposing|contending|"
    r"asserting|claiming|concluding|invalidating|sustaining|remanding|dismissing|denying|"
    r"granting|overruling|abrogating|adopting|endorsing|characterizing|identifying)\b",
    re.IGNORECASE)
# The separate-opinion shapes the draft itself supplies: "(Thomas, J., concurring)",
# "(Roberts, C.J., dissenting)", "(Kagan & Sotomayor, JJ., dissenting)", "(opinion of
# Roberts, C.J.)", "(plurality opinion)", "(per curiam)", "(statement of Sotomayor, J.)".
# Anchored at the start, so "(rejecting the dissenting view ...)" is a proposition.
_OPINION_SHAPE = re.compile(
    r"^(?:opinion\s+of\b|statement\s+of\b|plurality\s+opinion|per\s+curiam|en\s+banc|"
    r"[A-Z][^()]{0,60}?,\s*(?:C\.?\s?J|J|JJ)\.,?\s*(?:concurring|dissenting))", re.IGNORECASE)


def proposition_parenthetical(clause):
    """The first parenthetical that states what the source is cited FOR
    ("holding that ...", "noting the ..."), or ""."""
    for p in parentheticals(clause):
        t = _clean(p)
        if _NON_PROP.match(t) or _OPINION_SHAPE.match(t):
            continue
        if _PROP_START.match(t):
            return t
        if _YEAR_END.search(t) or CASE_CITE.search(t):
            continue
        if len(t.split()) >= 3:
            return t
    return ""


def opinion_note(clause):
    """A separate-opinion parenthetical ("Thomas, J., concurring") the draft itself
    supplies — posture the support checker must honor, not flag."""
    for p in parentheticals(clause):
        t = _clean(p)
        if _OPINION_SHAPE.match(t):
            return t
    return ""



def kind_of(text):
    outer = _strip_parens(text)
    if re.search(r"\b(?:id|ibid)\.", outer, re.I): return "id"
    if re.search(r"supra\s+note", outer, re.I): return "supra"
    if CASE_CITE.search(outer): return "case"
    if STATUTE.search(outer): return "statute"
    if re.search(r"\bv\.\s+.*\bNo\.\s*\d", outer): return "case"
    if re.search(r"https?://|www\.", outer): return "internet"
    if JOURNAL.search(outer): return "article"
    if re.search(r"\([^()]*\b\d{4}\)", text): return "book"
    return "text"


def screen_clause(text, kind=None):
    kind = kind or kind_of(text)
    return {"draft_citation_text": text, "kind_hint": kind, "signal": signal_of(text),
            "pincite": locate(text, kind), "parenthetical": proposition_parenthetical(text),
            "opinion_note": opinion_note(text)}


def prose_clauses(text):
    """Retain standalone prose and introductions such as 'For the contrary view'."""
    result = []
    for clause in split_clauses(text):
        if kind_of(clause) == 'text':
            result.append(clause)
            continue
        for match in re.finditer(r"\b(?:see(?:,?\s+e\.g\.,?|\s+also|\s+generally)?|but\s+(?:see|cf\.)|cf\.|compare|accord|contra)\s+", clause, re.I):
            prefix = clause[:match.start()].strip()
            if prefix and outside(clause, match.start()) and not CASE_CITE.search(prefix):
                result.append(prefix)
                break
    return result


def screen_extraction(data):
    rows = []
    for note in data.get("footnotes", []):
        for clause in split_clauses(note["text"]):
            rows.append({"screen_id": f"C{len(rows)+1}", "footnote_number": note.get("number"),
                         "note_id": note.get("note_id"), "anchor": note.get("anchor"),
                         **screen_clause(clause)})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in screen_extraction(json.loads(args.extraction.read_text())))
    if args.output: args.output.write_text(text, encoding="utf-8")
    else: print(text, end="")
