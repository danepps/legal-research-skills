#!/usr/bin/env python3
"""Deterministic quote verifier for the cite-check skill.

The model PROPOSES that a draft quotation appears in a fetched source; this
script PROVES or refutes it, so a hallucinated "verbatim" cannot survive.
It also reports the printed PAGE each match sits on (from page boundaries in
the extracted text), which settles pincites without reading footer/star
markers by eye — the off-by-one marker-convention trap (NOTES item 12).

Usage:
    verify_quotes.py SOURCE_FILE "quote one" ["quote two" ...]
    verify_quotes.py SOURCE_FILE --json QUOTES.json [--first-page N]
    verify_quotes.py SOURCE_FILE --page 512 [--first-page N]   # print one printed page

SOURCE_FILE is extracted source text (e.g. `fetch_page.py <url> > src.txt`).
QUOTES.json is a list of {"id": ..., "quote": "...", "pincite": "516-17"}.
--first-page maps the source's first page to its printed number (default 1).
Page boundaries are form feeds (as pdftotext emits), explicit `<<pg. N>>`
markers, or star pagination (`*516` or `[*516]`); with none, pages are not
reported and pincites aren't judged. A bracketed star marker is never text,
and a word split by a soft hyphen at a line end is one word, at every tier.

Match tiers, reported per quote as `status`:
  verbatim    exact text, modulo whitespace runs / line wraps
  normalized  + typographic folding only (curly vs straight quotes, dash
              forms, soft hyphens, line-break hyphenation, ligatures,
              nested-quote-mark level) — identical as printed. Invisible
              format characters (zero-width space etc.) and the Unicode
              normalization form are ignored at every tier.
  altered     matches once the draft's MARKED alterations are honored:
              ellipsis omissions (segments in document order, gaps bounded)
              and [bracketed] changes wildcarded
  not_found   no match; `hint` carries the closest source passage when one
              scores near enough — the draft-vs-hint diff IS the finding

Every tier matches WHOLE source tokens. A quote that begins or ends inside a
source word or number is not a match ("eligible" is not in a source that says
"ineligible"; "$400," is not in "$400,000") — see the token-boundary section.
Such a quote is not_found, with `partial_token_match` showing the source words.

Exit codes: 0 = every quote matched (any tier); 1 = at least one not_found;
2 = usage/read error. Stdlib only. Output is one JSON object on stdout.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from bisect import bisect_right
from difflib import SequenceMatcher

# Typographic folds (single char -> replacement). All quote marks fold to a
# single apostrophe: Bluebook legitimately shifts nested quotation levels
# (interior doubles become singles), so mark LEVEL is not a matchable fact.
FOLD = {}
for _c in "‘’‚‛′‵“”„‟″‶'\"":
    FOLD[_c] = "'"
for _c in "‐‑‒–—―−":
    FOLD[_c] = "-"
FOLD[" "] = " "

# Dashes that may JOIN two word halves (a hyphenated word, or pdftotext's
# line-end hyphenation): the ASCII hyphen-minus, U+2010 hyphen, U+2011
# non-breaking hyphen. En/em dashes, the horizontal bar and the minus sign are
# always punctuation — a closed-up em dash ("knows—or") is the standard
# typographic form in law reviews and opinions, and folding it into a joiner
# turned "knows—or" into "knowsor", which no draft spelling could match.
JOIN_DASHES = frozenset("-\u2010\u2011")
# An INLINE hyphen between letters (no whitespace after it) is ambiguous: a wrap
# hyphen that a re-flowed source left inline ("estab-lished") or a meaningful
# one ("re-signed" is not "resigned"). It joins its halves only when (a) the
# joined token actually occurs in the other text being compared and (b) the
# left half is not a bare English prefix — a prefix hyphen is exactly where
# joining changes meaning, and "re-signed"/"resigned" both yield a token the
# draft contains, so (a) alone cannot tell them apart. Otherwise it is a word
# boundary, and the difference surfaces in word_diff. Hyphens at a line wrap
# (newline after them) always join, as before.
HYPHEN_PREFIXES = frozenset(
    "re pre co non un de anti pro sub inter intra multi post semi self ex quasi over "
    "under counter cross bi tri mid mis dis trans super ultra pseudo neo vice "
    "extra pan uni".split())
_JOIN_HALVES = re.compile(r"([A-Za-z]+)[-\u2010\u2011]([A-Za-z]+)")

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
             "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}

PG_MARKER_RE = re.compile(r"<<pg\.\s*(\d+)>>")
# Star pagination: a bare *516, or the bracketed [*516] that Lexis-style text
# carries. A bracketed marker is a page marker wherever it appears, so it is
# always treated as whitespace ([**12] and [***3], parallel reporters, too); a
# bare *N counts only when the file holds a plausible page sequence.
STAR_MARKER_RE = re.compile(r"\[\*{2,3}\d{1,4}\]|\[\*(\d{1,4})\]|\*(\d{1,4})")
BRACKET_STAR_RE = re.compile(r"\[\*{1,3}\d{1,4}\]")
# 3-4 dots with optional single spaces (covers "...", ". . .", four-dot close).
ELLIPSIS_RE = re.compile(r"\.[ ]?\.[ ]?\.(?:[ ]?\.)?")
BRACKET_RE = re.compile(r"\[([^\][]{0,80})\]")

BRACKET_SLACK = 30     # a bracket may stand for up to len(inner) + this many source chars
SHORT_SEGMENT = 10     # DingDuff rule: segments around an ellipsis >= ~10 chars
MAX_GAP_WARN = 600     # normalized chars between ellipsis segments before warning
CHAIN_RESTARTS = 50    # attempts to re-anchor segment 1 before giving up


# ---- Token boundaries -------------------------------------------------------
# A match must start and end on a source-token boundary. Substring search alone
# accepted "eligible for protection" against "ineligible for protection" and
# "$400," against "$400,000" as verbatim. A cut is INSIDE a token when it falls:
#   - between two letters, two digits, or a digit and a following letter
#     ("10b", "4th"); combining marks count as letters;
#   - next to an apostrophe that has a letter on both sides ("can't" is not
#     "can", "court's" is not "court");
#   - inside a number: at a thousands comma (a comma followed by exactly three
#     digits) or a decimal point;
#   - next to a single hyphen that joins two word halves, written closed up
#     ("non-binding" is not "binding") or broken across a line or page
#     ("in-\neligible" is not "eligible"), a soft hyphen at a line end
#     included. "pre- and post-trial" (spaces only) and dashes ("knows—or",
#     "knows--or") are boundaries.
# Two shapes are allowed because flattened footnote calls produce them, and are
# reported as a warning instead: a word followed directly by digits
# ("protection12") and a number, a period, then one to three digits before a
# new sentence ("in 1871.45 The Court").
APOSTROPHES = frozenset("'\u2019\u02bc")
SOFT_HYPHEN = "\u00ad"       # invisible unless it ends a line, where it splits a word;
                             # followed by any whitespace it marks such a split
_SENTENCE_OPENERS = frozenset("'\"\u2018\u201c([")


def _cls(c):
    """'L' for a letter or combining mark, 'D' for a digit, '' otherwise —
    including for the empty string _at() returns past either end of the text."""
    if not c:
        return ""
    k = unicodedata.category(c)[0]
    return "L" if k in "LM" else "D" if k == "N" else ""


def _at(text, i):
    return text[i] if 0 <= i < len(text) else ""


def _separator_joins(norm, k):
    """norm[k] is ',' or '.' with a digit on each side: is it part of ONE number?
    A comma is when exactly three digits follow. A period is unless one to
    three digits and then a new sentence follow (a footnote call)."""
    j = k + 1
    while j < len(norm) and _cls(norm[j]) == "D":
        j += 1
    ndigits = j - (k + 1)
    if norm[k] == ",":
        return ndigits == 3
    if ndigits > 3:
        return True
    if j >= len(norm):
        return False
    if norm[j] != " ":
        return True
    nxt = _at(norm, j + 1)
    if nxt in _SENTENCE_OPENERS:
        nxt = _at(norm, j + 2)
    return not nxt.isupper()


def _cut(norm, i, at_end):
    """Classify the cut between norm[i-1] and norm[i]: "inside" a source token,
    "digits" (allowed, but digits follow the match — see above) or None."""
    p, c = _at(norm, i - 1), _at(norm, i)
    if not p or not c:
        return None
    a, b = _cls(p), _cls(c)
    if a and b:
        return "digits" if (at_end and a == "L" and b == "D") else "inside"
    if c in APOSTROPHES and a == "L" and _cls(_at(norm, i + 1)) == "L":
        return "inside"
    if p in APOSTROPHES and b == "L" and _cls(_at(norm, i - 2)) == "L":
        return "inside"
    if c in ",." and a == "D" and _cls(_at(norm, i + 1)) == "D":
        return "inside" if _separator_joins(norm, i) else ("digits" if at_end else None)
    if p in ",." and b == "D" and _cls(_at(norm, i - 2)) == "D":
        return "inside" if _separator_joins(norm, i - 1) else ("digits" if at_end else None)
    return None


def _is_cf(c):
    return unicodedata.category(c) == "Cf"


def span_jumps(page_spans, raw=""):
    """({marker_end: marker_start}, {marker_start: marker_end}) for the raw-text
    scans: the page spans, plus every bracketed star marker in raw."""
    pairs = [(s, e) for s, e, _ in page_spans]
    pairs += [(m.start(), m.end()) for m in BRACKET_STAR_RE.finditer(raw)]
    return ({e: s for s, e in pairs}, {s: e for s, e in pairs})


def _gap_after(raw, j, fwd):
    """Skip whitespace, page markers and format characters from raw[j] on.
    Returns (index of the next printed character, saw whitespace, saw a line
    or page break)."""
    ws = brk = False
    n = len(raw)
    while j < n:
        ch = raw[j]
        if j in fwd:                        # a page marker sits in the gap
            j, ws, brk = fwd[j], True, True
        elif ch.isspace():
            ws, brk, j = True, brk or ch not in " \t\u00a0", j + 1
        elif _is_cf(ch):
            j += 1
        else:
            break
    return j, ws, brk


def _letter_before(raw, j):
    """Is the printed character before raw[j] a letter?"""
    while j > 0 and _is_cf(raw[j - 1]):
        j -= 1
    return _cls(_at(raw, j - 1)) == "L"


def _hyphen_joins_at(raw, k, fwd):
    """Is raw[k] ONE hyphen joining two word halves: a letter right before it,
    and a letter right after it or after a line or page break?"""
    if _at(raw, k) not in JOIN_DASHES or not _letter_before(raw, k):
        return False
    j, ws, brk = _gap_after(raw, k + 1, fwd)
    return _cls(_at(raw, j)) == "L" and (not ws or brk)


def _hyphen_before(raw, a, back, fwd=None):
    """Is raw[a] the first letter of the SECOND half of a hyphenated word, or
    the joining hyphen itself (a quote that starts "-binding")?"""
    if fwd is not None and _hyphen_joins_at(raw, a, fwd):
        return True
    if _cls(_at(raw, a)) != "L":
        return False
    j, ws, brk = a, False, False
    while j > 0:
        ch = raw[j - 1]
        if j in back:                       # a page marker sits in the gap
            j, ws, brk = back[j], True, True
        elif ch.isspace():
            ws, brk, j = True, brk or ch not in " \t\u00a0", j - 1
        elif _is_cf(ch) and ch != SOFT_HYPHEN:
            j -= 1
        else:
            break
    if j < 1:
        return False
    if raw[j - 1] == SOFT_HYPHEN:
        if not ws:                  # mid-line: the views drop it and the letters touch
            return False
    elif raw[j - 1] not in JOIN_DASHES or (ws and not brk):
        return False
    j -= 1
    while j > 0 and _is_cf(raw[j - 1]):
        j -= 1
    return _cls(_at(raw, j - 1)) == "L"


def _hyphen_after(raw, b, fwd):
    """Is raw[b-1] the last letter of the FIRST half of a hyphenated word, or
    the joining hyphen itself (a quote that ends "non-")?"""
    if _hyphen_joins_at(raw, b - 1, fwd):
        return True
    if _cls(_at(raw, b - 1)) != "L":
        return False
    j, n = b, len(raw)
    soft = False
    while j < n and _is_cf(raw[j]):
        soft = soft or raw[j] == SOFT_HYPHEN
        j += 1
    if j < n and raw[j] in JOIN_DASHES:
        j, soft = j + 1, False
    elif not soft:
        return False
    ws = brk = False
    while j < n:
        ch = raw[j]
        if j in fwd:
            j, ws, brk = fwd[j], True, True
        elif ch.isspace():
            ws, brk, j = True, brk or ch not in " \t\u00a0", j + 1
        elif _is_cf(ch):
            j += 1
        else:
            break
    if soft:                        # a soft hyphen joins only across whitespace
        return _cls(_at(raw, j)) == "L" and ws
    return _cls(_at(raw, j)) == "L" and (not ws or brk)


def match_edges(norm, omap, raw, s, e, jumps=({}, {}), check_start=True, check_end=True):
    """Do the edges of norm[s:e] sit on source-token boundaries? Returns
    "inside" (they do not: not a match), "digits" (a match, but digits follow
    it directly) or None. The hyphen tests read the RAW text through omap,
    because the folded view turns a hyphen into a space or drops it."""
    if e <= s:
        return None
    verdict = None
    if check_start:
        if _cut(norm, s, False) == "inside" or _hyphen_before(raw, omap[s], jumps[0], jumps[1]):
            return "inside"
    if check_end:
        verdict = _cut(norm, e, True)
        if verdict == "inside" or _hyphen_after(raw, omap[e - 1] + 1, jumps[1]):
            return "inside"
    return verdict


def token_context(norm, omap, raw, s, e):
    """The source text around norm[s:e], widened to whole words, for a report."""
    while s > 0 and norm[s - 1] != " ":
        s -= 1
    while e < len(norm) and norm[e] != " ":
        e += 1
    return raw[omap[s]:omap[e - 1] + 1][:280]


def find_page_spans(raw):
    """Spans in the raw text that are page boundaries: (start, end, printed_no).

    Explicit <<pg. N>> markers win (they carry their own numbers); then form
    feeds (physical pages, numbered via --first-page; printed_no None); then
    star pagination (*N, as CAP/CourtListener official-reporter text carries),
    accepted only when it looks like a real page sequence — at least three
    markers, strictly ascending in small steps — so footnote asterisks and
    stray *N text fall back to "none" rather than mis-paginate.
    """
    spans = [(m.start(), m.end(), int(m.group(1))) for m in PG_MARKER_RE.finditer(raw)]
    if spans:
        return spans, "pg-markers"
    spans = [(m.start(), m.end(), None) for m in re.finditer("\f", raw)]
    if spans:
        return spans, "form-feed"
    stars = [(m.start(), m.end(), int(m.group(1) or m.group(2)))
             for m in STAR_MARKER_RE.finditer(raw) if m.group(1) or m.group(2)]
    nums = [s[2] for s in stars]
    if len(stars) >= 3 and all(0 < b - a <= 5 for a, b in zip(nums, nums[1:])):
        return stars, "star"
    return [], "none"


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def source_join_candidates(raw):
    """Joined forms of every inline letter-hyphen-letter pair in the source."""
    return {(a + b).lower() for a, b in _JOIN_HALVES.findall(raw)}


def _inline_join_ok(norm, raw, j, join_tokens):
    """Whether the inline hyphen just before raw[j] may join its halves."""
    k = len(norm)
    while k > 0 and norm[k - 1].isalpha():
        k -= 1
    left = "".join(norm[k:]).lower()
    m = j
    while m < len(raw) and raw[m].isalpha():
        m += 1
    right = raw[j:m].lower()
    if left in HYPHEN_PREFIXES:
        return False
    return bool(join_tokens) and (left + right) in join_tokens


def normalize(raw, fold, page_spans=(), join_tokens=None):
    """Collapse whitespace (and optionally fold typography) with an offset map.

    Returns (norm, omap, bounds): omap[i] = raw index of norm[i]; bounds =
    [(norm_pos, printed_no)] for each page boundary, boundary owning the text
    that FOLLOWS it (page starts at the boundary). `join_tokens` is the token
    set of the OTHER text, consulted for inline hyphens (see HYPHEN_PREFIXES).
    """
    norm, omap, bounds = [], [], []
    pending_ws = False
    spans = list(page_spans)
    si = 0

    def emit(ch, src):
        nonlocal pending_ws
        if pending_ws and norm:
            norm.append(" ")
            omap.append(src)
        pending_ws = False
        norm.append(ch)
        omap.append(src)

    i, n = 0, len(raw)
    while i < n:
        if si < len(spans) and i == spans[si][0]:
            # A page boundary behaves like whitespace; text after it is on the
            # new page, so record the position the NEXT emitted char will get.
            bounds.append((len(norm) + (1 if (pending_ws and norm) else 0), spans[si][2]))
            i = spans[si][1]
            si += 1
            pending_ws = True
            continue
        c = raw[i]
        if c.isspace():
            pending_ws = True
            i += 1
            continue
        if c == "[":
            mk = BRACKET_STAR_RE.match(raw, i)
            if mk:
                # "[*516]" is a reporter's page marker, never text. Left in, its
                # brackets blocked every quote that crossed a page.
                pending_ws = True
                i = mk.end()
                continue
        if unicodedata.category(c) == "Cf":
            # Format characters are never printed: soft hyphen, zero-width
            # space/joiner/non-joiner, BOM, word joiner. Word output is full of
            # U+200B, and one of them inside a quote blocked every match tier.
            if c == SOFT_HYPHEN and norm and norm[-1].isalpha() and not pending_ws:
                # A soft hyphen shows only where a line breaks inside a word
                # (pdftotext output is full of them). The halves are one word at
                # every tier: without this "un<SHY>\nnecessary" read "un necessary".
                # Any whitespace after it counts, since re-flowed or pasted text
                # turns the line break into a space.
                j, k, crossed = i + 1, si, []
                while j < n:
                    if k < len(spans) and j == spans[k][0]:
                        crossed.append(spans[k][2])
                        j, k = spans[k][1], k + 1
                    elif raw[j].isspace() or unicodedata.category(raw[j]) == "Cf":
                        j += 1
                    elif raw[j] == "[" and BRACKET_STAR_RE.match(raw, j):
                        j = BRACKET_STAR_RE.match(raw, j).end()
                    else:
                        break
                if j < n and raw[j].isalpha():
                    bounds.extend((len(norm), no) for no in crossed)
                    si, i = k, j
                    continue
            i += 1
            continue
        if fold:
            raw_c = c
            c = FOLD.get(c, c)
            if c in LIGATURES:
                for ch in LIGATURES[c]:
                    emit(ch, i)
                i += 1
                continue
            if ord(c) > 127:
                d = unicodedata.normalize("NFKC", c)
                if d != c and d.isascii():
                    for ch in d:
                        emit(ch, i)
                    i += 1
                    continue
            if c == "-":
                # Dashes are unmatchable facts across draft/source: pdftotext
                # breaks words at line ends ("juris-\ndiction"), drafts close
                # them up, and an em dash may be typed as "--". Rule: a SINGLE
                # hyphen between letters (with at most a line break inside)
                # joins the halves, so "well-settled" == "wellsettled" ==
                # "well-\nsettled"; any other dash run is punctuation and
                # equivalent to a space, so "knows — or" == "knows--or".
                prev_alpha = bool(norm) and norm[-1].isalpha() and not pending_ws
                ndash, j = 1, i + 1
                while j < n and FOLD.get(raw[j], raw[j]) == "-":
                    ndash += 1
                    j += 1
                ws_start = j
                crossed_nl = False
                while j < n:
                    if si < len(spans) and j == spans[si][0]:
                        bounds.append((len(norm), spans[si][2]))
                        j = spans[si][1]
                        si += 1
                        crossed_nl = True
                    elif raw[j].isspace():
                        crossed_nl = crossed_nl or raw[j] in "\n\r\f\v"
                        j += 1
                    elif raw[j] == "[" and BRACKET_STAR_RE.match(raw, j):
                        j = BRACKET_STAR_RE.match(raw, j).end()   # a page marker in the gap
                        crossed_nl = True
                    else:
                        break
                had_ws = j > ws_start
                if (prev_alpha and j < n and raw[j].isalpha() and ndash == 1
                        and raw_c in JOIN_DASHES and (not had_ws or crossed_nl)):
                    if not had_ws and not _inline_join_ok(norm, raw, j, join_tokens):
                        pending_ws = True      # meaningful hyphen: word boundary
                        i = j
                        continue
                    i = j if had_ws else i + 1
                    continue
                pending_ws = True
                i = j
                continue
        emit(c, i)
        i += 1
    return "".join(norm), omap, bounds


def page_of(bounds, first_page, pos):
    """Printed page number at normalized offset pos, or None if no bounds."""
    if not bounds:
        return None
    idx = bisect_right([b[0] for b in bounds], pos) - 1
    if idx < 0:
        # Text before the first boundary. With numbered markers at page
        # starts, that text belongs to the page before the first marker.
        first = bounds[0][1]
        return (first - 1) if first is not None else first_page
    numbered = bounds[idx][1]
    if numbered is not None:
        return numbered
    return first_page + idx + 1 if bounds[0][1] is None and bounds[0][0] > 0 else first_page + idx


def parse_pincite(pin):
    """'516', '516-17', '516–517', '461 n.4' -> (start, end) or None."""
    if not pin:
        return None
    nums = re.findall(r"\d+", str(pin).split("n.")[0] or str(pin))
    if not nums:
        return None
    start = int(nums[0])
    end = start
    if len(nums) > 1:
        e = nums[1]
        # "516-17" style: graft the start's prefix onto a shortened endpoint.
        if int(e) < start and len(e) < len(nums[0]):
            e = nums[0][: len(nums[0]) - len(e)] + e
        end = max(start, int(e))
    return (start, end)


def segments_of(quote_norm):
    """Split a normalized quote at marked ellipses -> list of segment strings."""
    return [s.strip() for s in ELLIPSIS_RE.split(quote_norm) if s.strip()]


def segment_regex(seg):
    """Segment -> compiled regex with [bracketed] alterations wildcarded."""
    parts, last = [], 0
    for m in BRACKET_RE.finditer(seg):
        parts.append(re.escape(seg[last:m.start()]))
        inner = m.group(1).strip()
        if inner.lower() == "sic":
            parts.append(r"\s?")            # [sic] flags the source's own text
        elif len(inner) <= 2:
            parts.append(r".{0,4}")         # "[T]he", "[a]" — tiny substitution
        else:
            parts.append(r".{0,%d}?" % (len(inner) + BRACKET_SLACK))
        last = m.end()
    parts.append(re.escape(seg[last:]))
    return re.compile("".join(parts))


def segment_free_edges(seg):
    """(start, end, max_len) for a segment. start/end: edges that a
    [bracketed] alteration occupies. The bracket stands for source text of
    unknown length ("[T]he" for "the"), so no token boundary can be required
    of that edge. max_len: the longest source text the segment's regex can
    match, or None when it has no bracket and so only one way to match."""
    ms = list(BRACKET_RE.finditer(seg))
    if not ms:
        return (False, False, None)
    return (ms[0].start() == 0, ms[-1].end() == len(seg),
            len(seg) + BRACKET_SLACK * len(ms))


def search_segment(sre, src_norm, pos, edge=None, free=(False, False, None)):
    """First match at or after pos whose edges sit on source-token boundaries.

    A bracket wildcard can match more than one stretch of source from the same
    start. In "The [official] may" against "The old mayor may issue", the lazy
    wildcard first takes "old" and the segment ends inside "mayor"; taking
    "old mayor" ends it on the word "may". So when a match ends inside a token,
    every other ending from that start is tried before moving on."""
    while True:
        m = sre.search(src_norm, pos)
        if not m or edge is None or m.end() == m.start():
            return m
        cs, ce = not free[0], not free[1]
        if edge(m.start(), m.end(), cs, ce) != "inside":
            return m
        max_len = free[2] if len(free) > 2 else None
        if max_len and edge(m.start(), m.end(), cs, False) != "inside":
            for end in range(m.start() + 1, min(len(src_norm), m.start() + max_len) + 1):
                if end == m.end():
                    continue
                alt = sre.fullmatch(src_norm, m.start(), end)
                if alt and edge(alt.start(), alt.end(), cs, ce) != "inside":
                    return alt
        pos = m.start() + 1


def chain_match(src_norm, seg_res, edge=None, free=None):
    """Match segments in order with bounded restarts. Returns (start, end,
    gaps) of the first consistent chain, or None. `edge(s, e, check_start,
    check_end)` rejects a segment that starts or ends inside a source token;
    `free[i]` names the edges of segment i that a bracket leaves unchecked."""
    free = free or [(False, False, None)] * len(seg_res)
    anchor_from = 0
    for _ in range(CHAIN_RESTARTS):
        m0 = search_segment(seg_res[0], src_norm, anchor_from, edge, free[0])
        if not m0:
            return None
        pos, gaps, spans = m0.end(), [], [(m0.start(), m0.end())]
        ok = True
        for sre, fr in zip(seg_res[1:], free[1:]):
            m = search_segment(sre, src_norm, pos, edge, fr)
            if not m:
                ok = False
                break
            gaps.append(m.start() - pos)
            spans.append((m.start(), m.end()))
            pos = m.end()
        if ok:
            return spans[0][0], spans[-1][1], gaps
        anchor_from = m0.start() + 1
    return None


OCCURRENCE_LIMIT = 20


def find_occurrences(src_norm, needle, limit=OCCURRENCE_LIMIT, edge=None, partial=None):
    """Start offsets of up to `limit` non-overlapping occurrences. With `edge`
    (a function of (start, end)), an occurrence that starts or ends inside a
    source token is skipped and its offset appended to the `partial` list."""
    out, start = [], 0
    while len(out) < limit:
        i = src_norm.find(needle, start)
        if i < 0:
            break
        if edge is not None and edge(i, i + len(needle)) == "inside":
            if partial is not None and len(partial) < limit:
                partial.append(i)
            start = i + 1
            continue
        out.append(i)
        start = i + max(1, len(needle))
    return out


def count_occurrences(src_norm, needle):
    return len(find_occurrences(src_norm, needle))


def choose_occurrence(occ, length, bounds, first_page, pr):
    """Among repeated matches, prefer the first whose printed page range
    intersects the cited pincite range `pr` = (lo, hi); else the first.
    Returns (chosen_start, pages_per_occurrence, chosen_index)."""
    pages = []
    for o in occ:
        a = page_of(bounds, first_page, o)
        b = page_of(bounds, first_page, o + max(1, length) - 1)
        pages.append(a if a == b else (a, b))
    pick = 0
    if pr and bounds:
        lo, hi = pr
        for idx, o in enumerate(occ):
            a = page_of(bounds, first_page, o)
            b = page_of(bounds, first_page, o + max(1, length) - 1)
            if a is None or b is None:
                continue
            if a <= hi and b >= lo:
                pick = idx
                break
    return occ[pick], pages, pick


def fuzzy_hint(src_norm, omap, raw, probe):
    """Best approximate window for a missing quote.

    Returns (ratio, original-text hint, normalized window) — the window
    extended outward to word boundaries so word_diff sees whole tokens.
    """
    L = len(probe)
    if not L or not src_norm:
        return 0.0, "", ""
    step = max(10, L // 4)
    best_r, best_i = 0.0, 0
    sm = SequenceMatcher(autojunk=False)
    sm.set_seq2(probe)
    for i in range(0, max(1, len(src_norm) - L + 1), step):
        sm.set_seq1(src_norm[i:i + L])
        if sm.real_quick_ratio() <= best_r:
            continue
        r = sm.ratio()
        if r > best_r:
            best_r, best_i = r, i
    for i in range(max(0, best_i - step), min(len(src_norm) - L, best_i + step) + 1, max(1, step // 8)):
        sm.set_seq1(src_norm[i:i + L])
        r = sm.ratio()
        if r > best_r:
            best_r, best_i = r, i
    if best_r < 0.5:
        return best_r, "", ""
    # Pad beyond the probe-sized window (the true source passage may be LONGER
    # than the draft quote — e.g. words the draft dropped), out to word
    # boundaries; word_diff skips edge insertions, so the padding reads as
    # context, not differences.
    s, e = max(0, best_i - 60), min(best_i + L + 60, len(src_norm))
    while s > 0 and src_norm[s - 1] != " ":
        s -= 1
    while e < len(src_norm) and src_norm[e] != " ":
        e += 1
    a = omap[s]
    b = omap[e - 1] + 1
    return best_r, raw[a:b].strip(), src_norm[s:e]


PUNCT_STRIP_RE = re.compile(r"[^0-9a-zA-Z]+")


def word_diff(probe, window):
    """Word-level diff of the draft quote vs the closest source window.

    Separates SUBSTANTIVE differences (whole words on one side only, or
    genuinely different words) from COSMETIC ones (same word modulo
    punctuation/case — the OCR-noise signature). Insertions at the window's
    edges are surrounding context, not differences, and are ignored.
    """
    a, b = probe.split(), window.split()
    # Align on punctuation-stripped lowercase tokens so OCR punctuation can't
    # break the alignment ("suffice" still anchors to "suffice.'"); compare
    # the ORIGINAL tokens inside equal runs to surface the cosmetic noise.
    ka = [PUNCT_STRIP_RE.sub("", w).lower() for w in a]
    kb = [PUNCT_STRIP_RE.sub("", w).lower() for w in b]
    sm = SequenceMatcher(None, ka, kb, autojunk=False)
    draft_only, source_only, changed, cosmetic = [], [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            cosmetic += [f"{x} ~ {y}" for x, y in zip(a[i1:i2], b[j1:j2]) if x != y]
        elif op == "delete":
            draft_only += a[i1:i2]
        elif op == "insert":
            if j1 == 0 or j2 == len(b):
                continue
            source_only += b[j1:j2]
        else:
            changed.append({"draft": " ".join(a[i1:i2]), "source": " ".join(b[j1:j2])})
    out = {}
    if draft_only:
        out["draft_only"] = draft_only
    if source_only:
        out["source_only"] = source_only
    if changed:
        out["changed"] = changed
    if cosmetic:
        out["cosmetic"] = cosmetic
    return out


def check_quote(raw, views, first_page, quote, pincite, fold_view=None):
    """views = {False: (norm, omap, bounds), True: (...), "src_tokens": set}
    keyed by fold. `fold_view(tokens)` returns the folded source view whose
    inline hyphens may join against the given quote tokens (cached in main)."""
    quote = unicodedata.normalize("NFC", quote)
    out = {"quote": quote if len(quote) <= 240 else quote[:240] + "…", "warnings": []}
    q_plain = normalize(quote, fold=False)[0]
    q_fold = normalize(quote, fold=True, join_tokens=views.get("src_tokens"))[0]
    pr = parse_pincite(pincite)
    if "page_jumps" not in views:
        views["page_jumps"] = span_jumps(find_page_spans(raw)[0], raw)
    jumps = views["page_jumps"]

    def edges_in(view):
        norm, omap = view[0], view[1]
        return lambda s, e, cs=True, ce=True: match_edges(norm, omap, raw, s, e, jumps, cs, ce)

    status = span = mv = None
    occ = []
    partial = None                 # (view, offset, length) of a rejected partial-token hit
    if q_plain:
        src_norm, _, _ = views[False]
        rejected = []
        occ = find_occurrences(src_norm, q_plain, edge=edges_in(views[False]), partial=rejected)
        if rejected:
            partial = (views[False], rejected[0], len(q_plain))
        if occ:
            status, mv = "verbatim", views[False]
            span = (occ[0], occ[0] + len(q_plain))
    q_tokens = _tokens(q_fold)
    fsrc_norm, fomap, fbounds = fold_view(q_tokens) if fold_view else views[True]
    fview = (fsrc_norm, fomap, fbounds)
    if status is None and q_fold:
        rejected = []
        occ = find_occurrences(fsrc_norm, q_fold, edge=edges_in(fview), partial=rejected)
        if rejected and partial is None:
            partial = (fview, rejected[0], len(q_fold))
        if occ:
            status, mv = "normalized", (fsrc_norm, fomap, fbounds)
            span = (occ[0], occ[0] + len(q_fold))
            out["note"] = "matches after typographic folding only — identical as printed"
    if status is None:
        segs = segments_of(q_fold)
        # A quote with only a LEADING or TRAILING ellipsis has one segment but
        # is still a marked alteration; without this it never reached the
        # altered tier and was reported not_found even when verbatim.
        marked = (len(segs) > 1 or BRACKET_RE.search(q_fold)
                  or ELLIPSIS_RE.search(q_fold))
        if segs and marked:
            res = chain_match(fsrc_norm, [segment_regex(s) for s in segs],
                              edge=edges_in(fview), free=[segment_free_edges(s) for s in segs])
            if res and res[1] > res[0]:   # an empty match (a bare "[T]") locates nothing
                s, e, gaps = res
                status, span, mv = "altered", (s, e), (fsrc_norm, fomap, fbounds)
                out["note"] = ("matches with the draft's marked alterations honored "
                               f"({len(segs)} segment(s), gaps {gaps or 'n/a'})")
                for seg in segs:
                    if len(seg) < SHORT_SEGMENT and len(segs) > 1:
                        out["warnings"].append(f"short_segment(<{SHORT_SEGMENT} chars): \"{seg}\"")
                for g in gaps:
                    if g > MAX_GAP_WARN:
                        out["warnings"].append(f"large_gap({g} chars between ellipsis segments)")

    if status is None:
        out["status"] = "not_found"
        probe = max(segments_of(q_fold) or [q_fold], key=len)
        ratio, hint, window = fuzzy_hint(fsrc_norm, fomap, raw, probe)
        out["best_ratio"] = round(ratio, 2)
        if partial:
            pview, at, length = partial
            out["partial_token_match"] = token_context(pview[0], pview[1], raw, at, at + length)
        if hint:
            out["hint"] = hint
            diff = word_diff(probe, window)
            if diff:
                out["word_diff"] = diff
        if partial:
            out["reason"] = ("the quote's wording occurs in this source only INSIDE a longer "
                            "word or number (partial_token_match shows the source's own "
                            "words) — the quote starts or ends mid-token, so the source "
                            "says something different")
        elif hint:
            out["reason"] = ("closest source passage differs from the draft quote — "
                            "word_diff separates substantive differences "
                            "(draft_only/source_only/changed words) from cosmetic "
                            "punctuation/case noise (common in OCR'd scans)")
        else:
            out["reason"] = "no similar passage in this source text"
        return out

    out["status"] = status
    # Page + excerpt come from the view the match was found in.
    norm, omap, bounds = mv
    if len(occ) > 1:
        # Repeated passage: prefer the occurrence on the cited page (a quote
        # printed on pp. 10 and 15 and pinned to 15 used to report p. 10 and a
        # false pincite_ok), and always say where the others are.
        length = span[1] - span[0]
        chosen, pages, pick = choose_occurrence(occ, length, bounds, first_page, pr)
        span = (chosen, chosen + length)
        out["occurrences"] = len(occ) if len(occ) < OCCURRENCE_LIMIT else "%d+" % OCCURRENCE_LIMIT
        if bounds:
            out["occurrence_pages"] = pages
            out["warnings"].append(
                "multiple_matches(%s) on pages %s — %s"
                % (out["occurrences"], pages,
                   "reported the one inside the pincite" if pr and pick > 0 or (pr and bounds and pick == 0 and pages and _page_in(pages[0], pr))
                   else ("none falls inside the pincite; page reported for the first" if pr
                         else "page reported for the first")))
        else:
            out["warnings"].append("multiple_matches(%s) — no page boundaries, first reported"
                                   % out["occurrences"])
    elif occ:
        out["occurrences"] = 1
    s, e = span
    a, b = omap[s], omap[e - 1] + 1
    out["match_excerpt"] = raw[a:b][:280]
    if status != "altered" and match_edges(norm, omap, raw, s, e, jumps) == "digits":
        out["warnings"].append(
            "match_abuts_digits — the source continues with digits directly after the "
            "match (\"%s\"); usually a flattened footnote call, but confirm the quote "
            "does not cut a number or identifier short" % raw[max(a, b - 12):b + 8].strip())
    if status == "normalized":
        # Inline hyphens inside the MATCHED passage that were joined to reach
        # the match: say so, since "estab-lished" may equally be a real hyphen.
        used = sorted({(x + y).lower() for x, y in _JOIN_HALVES.findall(raw[a:b])} & q_tokens)
        if used:
            out["note"] += " (inline hyphen(s) joined as wrap artifacts: %s)" % ", ".join(used)
            out["warnings"].append("inline_hyphen_joined(%s) — a hyphen inside the matched "
                                   "source passage was treated as a line-wrap artifact; "
                                   "confirm it is not a meaningful hyphen" % ", ".join(used))
    pg = page_of(bounds, first_page, s)
    if pg is not None:
        out["page"] = pg
        pg_end = page_of(bounds, first_page, e - 1)
        if pg_end != pg:
            out["page_end"] = pg_end
    if pr:
        out["pincite"] = pincite
        if pg is not None:
            lo, hi = pr
            match_pages = range(pg, (out.get("page_end") or pg) + 1)
            out["pincite_ok"] = any(lo <= p <= hi for p in match_pages)
        else:
            out["pincite_ok"] = None
            out["warnings"].append("pincite not judged — no page boundaries in source text")
    return out


def _page_in(page, pr):
    if page is None or pr is None:
        return False
    a, b = page if isinstance(page, tuple) else (page, page)
    return a is not None and b is not None and a <= pr[1] and b >= pr[0]


def print_page(raw, spec, first_page, max_chars):
    """--page: print the text of printed page N (or N-M) using the same page-boundary
    detection the quote check uses, so a support agent reads the pincited page without
    dumping a whole opinion into its context. Exit 1 when the file carries no page
    boundaries or the page is outside the file."""
    spans, marker = find_page_spans(raw)
    if marker == "none":
        print("no page boundaries in this file (no <<pg. N>>, form feeds or star pagination); "
              "read it by searching for the passage instead", file=sys.stderr)
        return 1
    m = re.match(r"^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$", spec)
    if not m:
        print("--page takes N or N-M", file=sys.stderr)
        return 2
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    if hi < lo:  # "512-13" style
        hi = int(str(lo)[:len(str(lo)) - len(m.group(2))] + m.group(2))
    bounds = [(s, n) for s, e, n in spans]
    cuts = [0] + [s for s, e, n in spans] + [len(raw)]
    pages = {}
    for k in range(len(cuts) - 1):
        a, b = cuts[k], cuts[k + 1]
        if b <= a:
            continue
        pg = page_of(bounds, first_page, a)
        pages.setdefault(pg, []).append(raw[a:b])
    avail = sorted(p for p in pages if p is not None)
    want = [p for p in range(lo, hi + 1) if p in pages]
    if not want:
        print("page %s not in this file (marker: %s; pages %s–%s)%s" % (
            spec, marker, avail[0] if avail else "?", avail[-1] if avail else "?",
            "; with form feeds the numbering depends on --first-page" if marker == "form-feed" else ""),
            file=sys.stderr)
        return 1
    out = []
    for p in want:
        out.append("[[page %d — marker: %s]]\n" % (p, marker) + "".join(pages[p]).strip("\f\n"))
    text = "\n\n".join(out)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[TRUNCATED at %d chars — narrow the page range]" % max_chars
    sys.stdout.write(text + "\n")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", help="extracted source text file")
    ap.add_argument("quotes", nargs="*", help="quote strings to verify")
    ap.add_argument("--json", dest="json_path", help="JSON file: [{id, quote, pincite}]")
    ap.add_argument("--first-page", type=int, default=1,
                    help="printed page number of the source's first page (form-feed sources)")
    ap.add_argument("--page", dest="page",
                    help="print the text of printed page N (or a range N-M) instead of "
                         "checking quotes — for the support pass, which reads a pincited "
                         "page rather than matching a quotation")
    ap.add_argument("--max-chars", type=int, default=12_000,
                    help="cap on --page output (default 12000)")
    args = ap.parse_args(argv)

    try:
        data = open(args.source, "rb").read()
        # NFC so a decomposed accent (e + U+0301) matches its composed form;
        # ligatures and "…" are left to the fold pass (NFC keeps them).
        raw = unicodedata.normalize("NFC", data.decode("utf-8", "replace"))
    except OSError as e:
        print(f"cannot read source: {e}", file=sys.stderr)
        return 2

    if args.page:
        return print_page(raw, args.page, args.first_page, args.max_chars)

    items = [{"quote": q} for q in args.quotes]
    if args.json_path:
        try:
            loaded = json.load(open(args.json_path, encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"cannot read --json file: {e}", file=sys.stderr)
            return 2
        if not isinstance(loaded, list):
            print("--json must contain a JSON array of {id, quote, pincite}", file=sys.stderr)
            return 2
        items += loaded
    if not items:
        ap.print_usage(sys.stderr)
        print("no quotes given (args or --json)", file=sys.stderr)
        return 2

    spans, marker = find_page_spans(raw)
    views = {fold: normalize(raw, fold=fold, page_spans=spans) for fold in (False, True)}
    views["src_tokens"] = _tokens(views[True][0])
    views["src_candidates"] = source_join_candidates(raw)
    views["page_jumps"] = span_jumps(spans, raw)
    cache = {frozenset(): views[True]}

    def fold_view(tokens):
        """Folded source view in which inline hyphens may join against the
        quote's own tokens; one view per distinct candidate set, cached."""
        jt = frozenset(tokens & views["src_candidates"])
        if jt not in cache:
            cache[jt] = normalize(raw, fold=True, page_spans=spans, join_tokens=jt)
        return cache[jt]

    results = []
    for it in items:
        r = check_quote(raw, views, args.first_page, str(it.get("quote", "")), it.get("pincite"),
                        fold_view=fold_view)
        if "id" in it:
            r = {"id": it["id"], **r}
        results.append(r)

    report = {
        "source": args.source,
        "sha256": hashlib.sha256(data).hexdigest(),
        "chars": len(raw),
        "page_boundaries": {"marker": marker, "count": len(spans),
                            "first_page": args.first_page if marker == "form-feed" else None},
        "results": results,
    }
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 1 if any(r["status"] == "not_found" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
