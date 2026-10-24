#!/usr/bin/env python3
"""Citation-instance LEDGER for the /cite-check skill (added 2026-09-06).

Why: the verification pipeline builds its work units from QUOTATIONS (prepare_units.py)
plus a case-existence pass over reporter cites. An unquoted secondary source therefore
produced no unit at all, and "every citation checked" quietly meant "every quoted
passage and every case cite." This script closes the accounting gap: it inventories
EVERY citation instance in every footnote — quoted or not, case or secondary, and the
Id. / supra / short-form cross-references between them — so the workflow can attach a
disposition to each one (verified / existence-only / finding / unverifiable /
unchecked / cross-reference) and the report can list what was NOT checked instead of
implying coverage it never had.

Deterministic, stdlib only, zero model tokens. Reads extract_cites.py's JSON.

What it does NOT do on its own: assess whether an unquoted cite actually SUPPORTS the
sentence it hangs on. That means reading the source, which the OPT-IN support pass
(prepare_support_units.py + the workflow's Support phase, 2026-10-24) does for the
instances in its scope; everything it did not read stays "existence-only (support not
assessed)" rather than pretending. For that pass each instance also records its
Bluebook signal, its pincite/locator and its proposition parenthetical.

Usage:
    python3 citation_ledger.py <extract.json> [ledger.json]      # full ledger
    python3 citation_ledger.py <extract.json> --compact           # workflow args form
    python3 citation_ledger.py <extract.json> --note 12           # one footnote, readable
    python3 citation_ledger.py --render <ledger_final.json> [--extract <extract.json>]
                                                                  # markdown companion table
                                                                  # (+ body sentence per note)

The workflow (cite-check.workflow.js) joins agent results back onto the ledger with
the same rules as assign_dispositions() below; that function is the reference
implementation and is what the test exercises.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_cites import (MIN_QUOTE_WORDS, QUOTE_PAT, REPORTER_ANY, SIGNAL_PREFIX,  # noqa: E402
                           SUPRA, _clean, find_case_cites)

# ---- clause splitting -------------------------------------------------------
# A footnote is split into citation clauses on ";" (outside parentheses/quotes) and
# on a sentence break followed by a Bluebook signal ("... . See ...", "... . Id. ...").
# The period must not be the one inside "cf." / "e.g." that precedes the next
# signal word ("But cf. Id." is one clause), and the signal may be followed by
# a comma ("See, e.g., X") as well as whitespace.
_SIGNAL_AFTER_PERIOD = re.compile(
    r"(?<!\bcf)(?<!\be\.g)\.\s+(?=(?:See|Cf\.|But\s+(?:see|cf\.)|Compare|Accord|Contra|"
    r"E\.g\.,|Id\.)[\s,])")

# SIGNAL_PREFIX (a Bluebook signal that may sit in front of "id.") is shared
# with extract_cites.py's leading_id so the two never disagree.

ID_RE = re.compile("^" + SIGNAL_PREFIX + r"id\.", re.IGNORECASE)
# Internal cross-references ("See infra Section I.D.1", "supra Part II", "infra notes 40–45
# and accompanying text") and unfilled placeholders ("infra _") are not citations to a
# source; they are inventoried so nothing is dropped, but never verified.
INTERNAL = re.compile(
    r"^(?:(?:see|cf\.|but\s+see|see\s+also|see\s+generally|accord)\s+(?:also\s+)?)?"
    r"(?:infra|supra)\s+(?:_+|\(|(?:section|sections|part|parts|§|notes?\s+\d|nn?\.\s?\d|text|introduction|conclusion|appendix))",
    re.IGNORECASE)
PLACEHOLDER = re.compile(r"(?:^|\s)_{1,3}(?:\s|\.|,|$)")
SHORT_CASE = re.compile(r"\b(\d{1,4})\s+(%s)\s+at\s+\d{1,4}\b" % REPORTER_ANY)
STATUTE = re.compile(r"U\.\s?S\.\s?C\.|C\.\s?F\.\s?R\.|\bStat\.\s+\d|§|U\.S\.\s+Const\.|Fed\.\s+R\.")
URL = re.compile(r"https?://|www\.")
# "110 Harv. L. Rev. 815" — volume, abbreviated journal (must contain a period), page.
JOURNAL = re.compile(r"\b(\d{1,4})\s+((?:[A-Z][A-Za-z'&]*\.?\s+){1,7}?)(\d{1,5})\b")
BOOK = re.compile(r"\([^()]*\b\d{4}\)")  # any parenthetical ending in a year (checked after article)
YEAR = re.compile(r"\(\d{4}\)")
_PAREN = re.compile(r"\([^()]*\)")


def _depth_split(text, sep=";"):
    """Split on `sep` outside parentheses and double quotes."""
    parts, buf, depth, inq = [], [], 0, False
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "“":
            inq = True
        elif ch == "”":
            inq = False
        elif ch == '"':
            inq = not inq
        if ch == sep and depth == 0 and not inq:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _signal_split(clause):
    """Split at ". See ..." style breaks that sit outside parentheses."""
    out, start = [], 0
    for m in _SIGNAL_AFTER_PERIOD.finditer(clause):
        if clause[:m.start()].count("(") > clause[:m.start()].count(")"):
            continue  # inside a parenthetical
        out.append(clause[start:m.start() + 1])
        start = m.end()
    out.append(clause[start:])
    return out


def split_clauses(text):
    text = re.sub(r"^\s*\.?\s*", "", text or "")  # Word's leading ". "
    clauses = []
    for part in _depth_split(text):
        for c in _signal_split(part):
            c = c.strip()
            if c:
                clauses.append(c)
    return clauses


def _strip_parens(s):
    prev = None
    while prev != s:
        prev, s = s, _PAREN.sub(" ", s)
    return s


def _surname(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


# Signals and connectors that can precede an author name in "Author, supra".
_NAME_SIGNALS = {"see", "cf", "but", "accord", "compare", "contra", "eg", "also",
                 "and", "id", "in", "of", "generally", "with", "quoting", "citing"}


def supra_name_keys(outer):
    """Surname keys a 'supra note N' claims, from the comma-separated chunks
    before "supra" (up to three, so "Merrill, Landscape, supra" yields both
    "merrill" and "landscape"; "Bradley & Goldsmith, supra" yields "bradley").
    A target note matches if ANY key appears in it."""
    sm = SUPRA.search(outer)
    if not sm:
        return []
    chunks = [c.strip() for c in outer[:sm.start()].split(",") if c.strip()][-3:]
    keys = []
    for c in chunks:
        toks = [t for t in re.split(r"\s+", c.split("&")[0]) if t]
        while toks and _surname(toks[0]) in _NAME_SIGNALS:
            toks.pop(0)
        if toks and toks[0][:1].isupper():
            k = _surname(toks[-1])
            if k:
                keys.append(k)
    return keys


# ---- signal / locator / parenthetical (support-pass inputs, 2026-10-24) -------
# The introductory signal decides WHAT the cite claims (R. 1.2): no signal or "see"
# = direct support; "see also" = additional support; "cf." = support by analogy;
# "see generally" = background; "compare ... with" = comparison; "but see"/"contra"
# = CONTRARY authority. A support checker that reads a "but see" cite as a support
# claim manufactures a false finding, so the signal is recorded per instance.
SIGNAL_RE = re.compile(
    r"^(see,?\s+e\.g\.,?|see\s+also|see\s+generally|but\s+see|but\s+cf\.|cf\.|see|"
    r"compare|accord|contra|e\.g\.,?)(?=[\s,])", re.IGNORECASE)


def signal_of(clause):
    m = SIGNAL_RE.match((clause or "").strip())
    if not m:
        return ""
    sig = re.sub(r"\s+", " ", m.group(1).lower()).rstrip(",")
    return "see, e.g." if sig.replace(",", "") == "see e.g." else sig


_PIN_TAIL = (r"(\d{1,4}(?:\s*[–-]\s*\d{1,4})?(?:\s*(?:&|,)\s*\d{1,4}(?:\s*[–-]\s*\d{1,4})?)*"
             r"(?:\s*(?:&\s*)?nn?\.\s*\d+(?:\s*[–-]\s*\d+)?)?)")
AT_PIN = re.compile(r"\bat\s+" + _PIN_TAIL)
CASE_PIN = re.compile(r"\b\d{1,4}\s+(?:%s)\s+(?:\([^)]{1,24}\)\s+)?\d{1,4},\s*" % REPORTER_ANY
                      + _PIN_TAIL)
SECTION_PIN = re.compile(r"§§?\s*[\w.\-–]+(?:\([\w]+\))*")
PARA_PIN = re.compile(r"¶¶?\s*\d+(?:\s*[–-]\s*\d+)?")
BOOK_PIN = re.compile(r"\s" + _PIN_TAIL + r"\s*\((?=[^()]*\d{4}\))")


def locate(clause, kind):
    """The pincite / locator this instance points at, as printed ("431", "820–21",
    "§ 1983", "¶ 12"), or "" for a whole-work cite. A whole-work cite is the one the
    support pass cannot read at a page, so the distinction drives its scope."""
    outer = _strip_parens(clause) if kind != "case" else clause
    m = AT_PIN.search(outer)
    if m:
        return _clean(m.group(1))
    if kind in ("case", "case-short"):
        m = CASE_PIN.search(clause)
        if m:
            return _clean(m.group(1))
    if kind == "statute":
        m = SECTION_PIN.search(clause)
        return _clean(m.group(0)) if m else ""
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


# Parentheticals that are not a proposition: year/court, edition, quoting/citing,
# emphasis/alteration notes, and separate-opinion labels.
_NON_PROP = re.compile(
    r"^(?:quoting|citing|cited|emphasis|alterations?|internal|footnotes?|citations?|en banc|"
    r"per curiam|plurality|\d{4}\b|[A-Z0-9][\w.'’&\s]*\d{4}$|\d+(?:st|d|th)?\s+ed\.|"
    r"[A-Z][\w.'’\s]*,\s*(?:C\.?J|J|JJ)\.,?\s*(?:concurring|dissenting)|"
    r"(?:[A-Z]\.\s*)*[A-Z][\w.'’\s]*ed\.?,?\s+\d{4})", re.IGNORECASE)
_OPINION_NOTE = re.compile(r"\b(concurring|dissenting|plurality opinion|per curiam|statement of)\b",
                           re.IGNORECASE)


def proposition_parenthetical(clause):
    """The first parenthetical that states what the source is cited FOR
    ("holding that ...", "noting the ..."), or ""."""
    for p in parentheticals(clause):
        t = _clean(p)
        if len(t.split()) >= 3 and not _NON_PROP.match(t):
            return t
    return ""


def opinion_note(clause):
    """A separate-opinion parenthetical ("Thomas, J., concurring") the draft itself
    supplies — posture the support checker must honor, not flag."""
    for p in parentheticals(clause):
        if _OPINION_NOTE.search(p):
            return _clean(p)
    return ""


# ---- classification ----------------------------------------------------------
def classify(clause):
    """-> (kind, primary_case_cite_or_None, nested_case_cites, supra_note_or_None,
           supra_name_or_None)"""
    outer = _strip_parens(clause)
    cases_outer = find_case_cites(outer)
    cases_all = find_case_cites(clause)
    nested = [c for c in cases_all if c not in cases_outer]
    if ID_RE.match(clause):
        return "id", None, nested, None, None
    if not cases_outer and (INTERNAL.match(outer.strip()) or
                            (PLACEHOLDER.search(outer) and not SUPRA.search(outer))):
        return "internal", None, nested, None, None
    sm = SUPRA.search(outer)
    if sm and not cases_outer:
        name = None
        nm = re.search(r"([A-Z][A-Za-z'\-]{1,}(?:\s+&\s+[A-Z][A-Za-z'\-]{1,})?),?\s+supra", outer)
        if nm:
            name = nm.group(1)
        return "supra", None, nested, int(sm.group(1)), name
    if cases_outer:
        return "case", cases_outer[0], cases_outer[1:] + nested, None, None
    if SHORT_CASE.search(outer):
        return "case-short", None, nested, None, None
    if STATUTE.search(outer):
        return "statute", None, nested, None, None
    if URL.search(outer):
        return "internet", None, nested, None, None
    jm = JOURNAL.search(outer)
    if jm and "." in jm.group(2):
        return "article", None, nested, None, None
    if BOOK.search(clause):
        return "book", None, nested, None, None
    words = outer.split()
    if re.search(r"\d", outer) or ("," in outer and len(words) <= 25):
        return "other", None, nested, None, None
    return "text", None, nested, None, None


def _has_quote(clause):
    return any(len(_clean(m.group(1)).split()) >= MIN_QUOTE_WORDS
               for m in QUOTE_PAT.finditer(clause))


# ---- source key: MUST mirror sourceKey() in cite-check.workflow.js ------------
def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


_KEY_RE = re.compile(
    r"(\d+)\s+(u\.?\s?s\.?|s\.?\s?ct\.?|f\.?\s?(?:2d|3d|4th|supp\.?(?:\s?[23]d)?)?|[a-z.\s]+?)\s+(\d+)")


def source_key(citation):
    s = (citation or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r",?\s*\bat\s+[\d,\s–-]+", " ", s)
    s = re.sub(r"\bslip op[^,;]*", " ", s)
    m = _KEY_RE.search(s)
    if m:
        return norm("%s %s %s" % (m.group(1), m.group(2), m.group(3)))
    return " ".join(norm(s).split(" ")[:8])


# ---- ledger construction -----------------------------------------------------
XREF_KINDS = ("id", "supra", "case-short")


def build_ledger(data):
    notes = data["footnotes"]
    body_quote_notes = {q.get("footnote") for q in data.get("body_quotes", [])
                        if q.get("footnote")}
    instances = []
    for num in sorted(int(k) for k in notes):
        text = notes[str(num)]["text"]
        order = 0
        for clause in split_clauses(text):
            kind, case, nested, sn, sname = classify(clause)
            inst = {
                "i": len(instances), "note": num, "order": order, "kind": kind,
                "text": clause, "key": source_key(clause),
                "case_cite": case, "nested_cases": nested,
                "quoted": _has_quote(clause),
                "xref_note": sn, "xref_name": sname,
                "xref_target": None, "xref_status": None,
                # support-pass inputs (2026-10-24)
                "signal": signal_of(clause),
                "pincite": locate(clause, kind),
                "parenthetical": proposition_parenthetical(clause),
                "opinion_note": opinion_note(clause),
            }
            instances.append(inst)
            order += 1
            for nc in nested:  # a "(quoting X v. Y, 1 U.S. 2)" is a citation too
                instances.append({
                    "i": len(instances), "note": num, "order": order, "kind": "case",
                    "text": nc, "key": source_key(nc), "case_cite": nc,
                    "nested_cases": [], "quoted": False, "nested": True,
                    "xref_note": None, "xref_name": None,
                    "xref_target": None, "xref_status": None,
                    "signal": "", "pincite": locate(nc, "case"), "parenthetical": "",
                    "opinion_note": "",
                })
                order += 1
    # a body quote pinned to a note with exactly one substantive instance is that
    # instance's quote (multi-cite notes are settled by the workflow's resolver)
    for num in body_quote_notes:
        subs = [x for x in instances if x["note"] == num and x["kind"] not in XREF_KINDS + ("text", "internal")]
        if len(subs) == 1:
            subs[0]["quoted"] = True
    _resolve_xrefs(instances)
    by_kind = {}
    for x in instances:
        by_kind[x["kind"]] = by_kind.get(x["kind"], 0) + 1
    secondary = {}
    for x in instances:
        if x["kind"] in ("article", "book", "statute", "internet", "other"):
            secondary.setdefault(x["key"], {"key": x["key"], "kind": x["kind"],
                                            "cite": x["text"], "notes": []})
            secondary[x["key"]]["notes"].append(x["note"])
    return {
        "draft": data.get("source"),
        "instance_count": len(instances),
        "by_kind": by_kind,
        "unresolved_xrefs": [x["i"] for x in instances
                             if x["xref_status"] in ("unresolved", "name-mismatch")],
        "secondary_cites": list(secondary.values()),
        "instances": instances,
    }


def _resolve_xrefs(instances):
    def follow(idx, hops=0):
        x = instances[idx]
        if x["kind"] not in XREF_KINDS or hops > 12:
            return idx
        t = x["xref_target"]
        return follow(t, hops + 1) if t is not None else None

    for x in instances:
        status = None
        if x["kind"] == "id":
            # "Id." = the immediately preceding AUTHORITY; an internal "see infra
            # Part II" is not one and must be skipped, like prose.
            prev = [y for y in instances if y["i"] < x["i"]
                    and y["kind"] not in ("text", "internal") and not y.get("nested")]
            x["xref_target"] = prev[-1]["i"] if prev else None
        elif x["kind"] == "supra":
            cands = [y for y in instances if y["note"] == x["xref_note"]
                     and y["kind"] not in XREF_KINDS + ("text", "internal") and not y.get("nested")]
            # A target note holding only Id./short forms is left UNRESOLVED on purpose: a
            # "supra note N" must point at the note with the full citation, and on the real
            # test draft every such case was a renumbering break, not a chain to follow.
            pick = None
            keys = supra_name_keys(_strip_parens(x["text"]))
            if x["xref_name"]:
                keys.append(_surname(x["xref_name"].split("&")[0]))
            keys = [k for k in keys if k]
            if keys:
                for y in cands:
                    if any(k in _surname(y["text"]) for k in keys):
                        pick = y
                        break
                if pick is None and cands:
                    # The note exists and holds a full cite, but not of the author
                    # this supra names: the classic post-edit renumbering break.
                    # Never silently fall back to "whatever is in note N".
                    status = "name-mismatch"
            elif cands:
                pick = cands[0]
            x["xref_target"] = pick["i"] if pick else None
        elif x["kind"] == "case-short":
            m = SHORT_CASE.search(_strip_parens(x["text"]))
            vol, rep = m.group(1), re.sub(r"\s+", "", m.group(2))
            earlier = [y for y in instances if y["i"] < x["i"] and y["kind"] == "case"
                       and y["case_cite"] and y["case_cite"].startswith(vol + " ")
                       and re.sub(r"\s+", "", y["case_cite"].split(" ", 1)[1]).startswith(rep)]
            x["xref_target"] = earlier[-1]["i"] if earlier else None
        else:
            continue
        x["xref_status"] = status or ("resolved" if x["xref_target"] is not None else "unresolved")
    for x in instances:
        if x["kind"] in XREF_KINDS and x["xref_target"] is not None:
            end = follow(x["i"])
            if end is None:
                x["xref_status"] = "unresolved"
            else:
                x["xref_final"] = end


# ---- dispositions: reference implementation (mirrored in the workflow) -------
VERIFIED_VERDICTS = ("verbatim", "altered_marked", "fragment_framing")
FINDING_VERDICTS = ("mismatch", "not_found_in_sources", "syllabus_quote",
                    "superseded_source", "pincite_off")
# Opt-in support pass (2026-10-24). "overstated" is a CONFIRM item by design (the
# author's call, 2026-10-24): the source supports a narrower or weaker claim than
# the sentence makes, which is a judgment, never an error.
SUPPORT_FINDING_VERDICTS = ("contradicted", "not_supported")
SUPPORT_CONFIRM_VERDICTS = ("overstated",)
SUPPORTED_VERDICTS = ("supported", "supported_qualified")


def support_disposition(verdict):
    if verdict in SUPPORT_FINDING_VERDICTS:
        return "support-finding"
    if verdict in SUPPORT_CONFIRM_VERDICTS:
        return "support-confirm"
    if verdict in SUPPORTED_VERDICTS:
        return "supported"
    if verdict == "unverifiable":
        return "support-unverifiable"
    return None  # "unread" / unknown: the instance keeps its non-support disposition


def assign_dispositions(ledger, case_existence=None, secondary_existence=None,
                        quote_verdicts=None, secondary_pass_ran=True,
                        case_pass_ran=True, support_verdicts=None):
    """case_existence: {normalized cite: {"exists": bool|None}}
    secondary_existence: {source key: {"exists": bool|None}}
    quote_verdicts: {instance i: [verdict, ...]} (already joined to instances)
    support_verdicts: {instance i: verdict} from the opt-in support pass
    Mutates ledger instances in place, adding `disposition` (+ `reason`), and
    returns counts by disposition."""
    case_existence = case_existence or {}
    secondary_existence = secondary_existence or {}
    quote_verdicts = quote_verdicts or {}
    support_verdicts = support_verdicts or {}
    inst = ledger["instances"]
    for x in inst:
        k = x["kind"]
        sd = support_disposition(support_verdicts.get(x["i"]))
        if k == "text":
            x["disposition"] = "not-a-citation"
            continue
        if k == "internal":
            x["disposition"] = "internal-ref"
            x["reason"] = "cross-reference within the draft (or an unfilled placeholder), not a source"
            continue
        if k in XREF_KINDS:
            if x["xref_status"] == "name-mismatch":
                x["disposition"] = "unresolved-xref"
                x["reason"] = ("supra names an author who is not cited in note %s — "
                               "likely a renumbered footnote" % x["xref_note"])
            elif x["xref_status"] != "resolved":
                x["disposition"] = "unresolved-xref"
                x["reason"] = "cross-reference target could not be resolved from the draft"
            else:
                x["disposition"] = "xref"
                x["reason"] = "resolves to instance %d (n.%d)" % (
                    x.get("xref_final", x["xref_target"]),
                    inst[x.get("xref_final", x["xref_target"])]["note"])
            # a quote hanging on an Id./supra still gets its own verdict record
            vs = quote_verdicts.get(x["i"], [])
            if any(v in FINDING_VERDICTS for v in vs):
                x["disposition"] = "finding"
            elif sd and x["xref_status"] == "resolved":
                # an "Id. at 512" read for support has its own status now
                x["disposition"] = sd
                x["reason"] = "support pass: %s" % support_verdicts[x["i"]]
            continue
        vs = quote_verdicts.get(x["i"], [])
        if k == "case":
            ex = case_existence.get(x["case_cite"] or "")
            ran = case_pass_ran
        else:
            ex = secondary_existence.get(x["key"])
            ran = secondary_pass_ran
        exists = None
        if ex:
            if ex.get("exists") is True:
                exists = True
            elif ex.get("exists") is False and ex.get("basis") != "unconfirmed":
                exists = False  # located a catalog/site and it is not there
            # exists False + basis "unconfirmed" = could not tell -> unverifiable below
        if any(v in FINDING_VERDICTS for v in vs) or exists is False:
            x["disposition"] = "finding"
        elif sd == "support-finding" or sd == "support-confirm":
            x["disposition"] = sd
            x["reason"] = "support pass: %s" % support_verdicts[x["i"]]
        elif any(v in VERIFIED_VERDICTS for v in vs):
            x["disposition"] = "verified"
        elif sd == "supported":
            x["disposition"] = "supported"
            x["reason"] = "support pass: %s" % support_verdicts[x["i"]]
        elif vs and all(v == "unverifiable" for v in vs):
            x["disposition"] = "unverifiable"
        elif sd == "support-unverifiable":
            x["disposition"] = "support-unverifiable"
            x["reason"] = "source exists; could not be read for support"
        elif exists is True:
            x["disposition"] = "existence-only"
            x["reason"] = "source exists; no quotation to verify; proposition support NOT assessed"
        elif ex is not None:  # ran, came back unconfirmed
            x["disposition"] = "unverifiable"
            x["reason"] = "existence could not be confirmed from free sources"
        else:
            x["disposition"] = "unchecked"
            x["reason"] = ("no existence pass ran for this kind" if not ran
                           else "not reached by any pass")
    counts = {}
    for x in inst:
        counts[x["disposition"]] = counts.get(x["disposition"], 0) + 1
    ledger["disposition_counts"] = counts
    return counts


def compact(ledger):
    """Small form for Workflow args: one short object per instance."""
    return [{"i": x["i"], "n": x["note"], "k": x["kind"], "c": x["text"],
             "key": x["key"], "case": x["case_cite"], "x": x.get("xref_final"),
             "xs": x["xref_status"], "q": x["quoted"],
             "s": x.get("signal", ""), "pin": x.get("pincite", ""),
             "par": bool(x.get("parenthetical"))} for x in ledger["instances"]]


def render(instances, anchors=None):
    """Markdown table for the companion '<draft> — Citation Ledger.md' file. Accepts the
    workflow's returned ledger (compact form with `d`) or the full form with `disposition`.
    `anchors` ({note number: anchor dict}, from extract.json's footnotes) adds the body
    sentence each note hangs on, so an existence-only row can be audited by eye."""
    anchors = anchors or {}
    cols = "| Note | # | Kind | Signal | Disposition | Citation (as in draft) |"
    sep = "|---|---|---|---|---|---|"
    if anchors:
        cols += " Supports (body sentence) |"
        sep += "---|"
    rows = [cols, sep]
    counts = {}
    for x in instances:
        d = x.get("d") or x.get("disposition") or "?"
        counts[d] = counts.get(d, 0) + 1
        text = (x.get("c") or x.get("text") or "").replace("|", "\\|")
        why = x.get("why") or x.get("reason") or ""
        note = x.get("n", x.get("note"))
        row = "| n.%s | %s | %s | %s | %s%s | %s |" % (
            note, x["i"], x.get("k", x.get("kind")), x.get("s", x.get("signal", "")) or "—", d,
            (" (%s)" % why) if why and d in ("unchecked", "unverifiable", "support-unverifiable") else "",
            text[:200])
        if anchors:
            a = anchors.get(str(note)) or anchors.get(note) or {}
            sent = (a.get("clause") or a.get("sentence") or "").replace("|", "\\|")
            row += " %s |" % sent[:220]
        rows.append(row)
    head = ["# Citation ledger", "",
            "Every citation instance the extractor found, with what the cite-check run did to it. "
            "`existence-only` = the source exists but was not read for whether it supports the "
            "proposition; `supported` / `support-confirm` / `support-finding` / "
            "`support-unverifiable` = the opt-in support pass read it (`support-confirm` is a "
            "possible overstatement to confirm, never an error); "
            "`xref` = an Id./supra/short form that inherits its antecedent's status; "
            "`unchecked` = no pass reached it; `internal-ref` = a cross-reference within the draft "
            "(infra/supra Section, or an unfilled placeholder), not a source. The Signal column "
            "is the Bluebook introductory signal (— = direct support, no signal).", "",
            "Totals: " + ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())), ""]
    return "\n".join(head + rows) + "\n"


def main(argv):
    if not argv:
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    if argv[0] == "--render":
        obj = json.load(open(argv[1], encoding="utf-8"))
        inst = obj["instances"] if isinstance(obj, dict) and "instances" in obj else \
            obj["ledger"] if isinstance(obj, dict) and "ledger" in obj else obj
        anchors = None
        if "--extract" in argv:  # join the body anchor sentence by footnote number
            ex = json.load(open(argv[argv.index("--extract") + 1], encoding="utf-8"))
            anchors = {k: v.get("anchor") or {} for k, v in ex.get("footnotes", {}).items()}
        sys.stdout.write(render(inst, anchors))
        return 0
    data = json.load(open(argv[0], encoding="utf-8"))
    ledger = build_ledger(data)
    if len(argv) > 1 and argv[1] == "--compact":
        print(json.dumps({"instances": compact(ledger),
                          "secondary": ledger["secondary_cites"]}, ensure_ascii=False))
        return 0
    if len(argv) > 1 and argv[1] == "--note":
        n = int(argv[2])
        for x in ledger["instances"]:
            if x["note"] == n:
                print("[%d] %-10s %s%s" % (x["i"], x["kind"], x["text"][:120],
                                          "  -> %s" % x["xref_target"] if x["xref_target"] is not None else ""))
        return 0
    payload = json.dumps(ledger, ensure_ascii=False, indent=1)
    if len(argv) > 1:
        with open(argv[1], "w", encoding="utf-8") as f:
            f.write(payload)
    print(json.dumps({"instance_count": ledger["instance_count"],
                      "by_kind": ledger["by_kind"],
                      "unique_secondary_cites": len(ledger["secondary_cites"]),
                      "unresolved_xrefs": len(ledger["unresolved_xrefs"])}, indent=2))
    if len(argv) == 1:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
