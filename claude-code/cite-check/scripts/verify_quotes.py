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

SOURCE_FILE is extracted source text (e.g. `fetch_page.py <url> > src.txt`).
QUOTES.json is a list of {"id": ..., "quote": "...", "pincite": "516-17"}.
--first-page maps the source's first page to its printed number (default 1).
Page boundaries are form feeds (as pdftotext emits) or explicit `<<pg. N>>`
markers; with neither, pages are not reported and pincites aren't judged.

Match tiers, reported per quote as `status`:
  verbatim    exact text, modulo whitespace runs / line wraps
  normalized  + typographic folding only (curly vs straight quotes, dash
              forms, soft hyphens, line-break hyphenation, ligatures,
              nested-quote-mark level) — identical as printed
  altered     matches once the draft's MARKED alterations are honored:
              ellipsis omissions (segments in document order, gaps bounded)
              and [bracketed] changes wildcarded
  not_found   no match; `hint` carries the closest source passage when one
              scores near enough — the draft-vs-hint diff IS the finding

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

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
             "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}

PG_MARKER_RE = re.compile(r"<<pg\.\s*(\d+)>>")
STAR_MARKER_RE = re.compile(r"\*(\d{1,4})")
# 3-4 dots with optional single spaces (covers "...", ". . .", four-dot close).
ELLIPSIS_RE = re.compile(r"\.[ ]?\.[ ]?\.(?:[ ]?\.)?")
BRACKET_RE = re.compile(r"\[([^\][]{0,80})\]")

SHORT_SEGMENT = 10     # DingDuff rule: segments around an ellipsis >= ~10 chars
MAX_GAP_WARN = 600     # normalized chars between ellipsis segments before warning
CHAIN_RESTARTS = 50    # attempts to re-anchor segment 1 before giving up


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
    stars = [(m.start(), m.end(), int(m.group(1))) for m in STAR_MARKER_RE.finditer(raw)]
    nums = [s[2] for s in stars]
    if len(stars) >= 3 and all(0 < b - a <= 5 for a, b in zip(nums, nums[1:])):
        return stars, "star"
    return [], "none"


def normalize(raw, fold, page_spans=()):
    """Collapse whitespace (and optionally fold typography) with an offset map.

    Returns (norm, omap, bounds): omap[i] = raw index of norm[i]; bounds =
    [(norm_pos, printed_no)] for each page boundary, boundary owning the text
    that FOLLOWS it (page starts at the boundary).
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
        if fold:
            c = FOLD.get(c, c)
            if c == "­":               # soft hyphen: never printed
                i += 1
                continue
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
                    else:
                        break
                had_ws = j > ws_start
                if (prev_alpha and j < n and raw[j].isalpha() and ndash == 1
                        and (not had_ws or crossed_nl)):
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
            parts.append(r".{0,%d}?" % (len(inner) + 30))
        last = m.end()
    parts.append(re.escape(seg[last:]))
    return re.compile("".join(parts))


def chain_match(src_norm, seg_res):
    """Match segments in order with bounded restarts. Returns (start, end,
    gaps) of the first consistent chain, or None."""
    anchor_from = 0
    for _ in range(CHAIN_RESTARTS):
        m0 = seg_res[0].search(src_norm, anchor_from)
        if not m0:
            return None
        pos, gaps, spans = m0.end(), [], [(m0.start(), m0.end())]
        ok = True
        for sre in seg_res[1:]:
            m = sre.search(src_norm, pos)
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


def count_occurrences(src_norm, needle):
    n, start = 0, 0
    while n < 5:
        i = src_norm.find(needle, start)
        if i < 0:
            break
        n += 1
        start = i + max(1, len(needle))
    return n


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


def check_quote(raw, views, first_page, quote, pincite):
    """views = {False: (norm, omap, bounds), True: (...)} keyed by fold."""
    out = {"quote": quote if len(quote) <= 240 else quote[:240] + "…", "warnings": []}
    q_plain = normalize(quote, fold=False)[0]
    q_fold = normalize(quote, fold=True)[0]

    status = span = None
    if q_plain:
        src_norm, _, _ = views[False]
        i = src_norm.find(q_plain)
        if i >= 0:
            status, span = "verbatim", (i, i + len(q_plain))
            out["occurrences"] = count_occurrences(src_norm, q_plain)
    fsrc_norm, fomap, fbounds = views[True]
    if status is None and q_fold:
        i = fsrc_norm.find(q_fold)
        if i >= 0:
            status, span = "normalized", (i, i + len(q_fold))
            out["occurrences"] = count_occurrences(fsrc_norm, q_fold)
            out["note"] = "matches after typographic folding only — identical as printed"
    if status is None:
        segs = segments_of(q_fold)
        marked = len(segs) > 1 or BRACKET_RE.search(q_fold)
        if segs and marked:
            res = chain_match(fsrc_norm, [segment_regex(s) for s in segs])
            if res:
                s, e, gaps = res
                status, span = "altered", (s, e)
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
        if hint:
            out["hint"] = hint
            diff = word_diff(probe, window)
            if diff:
                out["word_diff"] = diff
            out["reason"] = ("closest source passage differs from the draft quote — "
                            "word_diff separates substantive differences "
                            "(draft_only/source_only/changed words) from cosmetic "
                            "punctuation/case noise (common in OCR'd scans)")
        else:
            out["reason"] = "no similar passage in this source text"
        return out

    out["status"] = status
    # Page + excerpt come from the folded view for normalized/altered matches,
    # the plain view for verbatim (span indexes that view's omap).
    norm, omap, bounds = views[status != "verbatim"]
    s, e = span
    a, b = omap[s], omap[e - 1] + 1
    out["match_excerpt"] = raw[a:b][:280]
    pg = page_of(bounds, first_page, s)
    if pg is not None:
        out["page"] = pg
        pg_end = page_of(bounds, first_page, e - 1)
        if pg_end != pg:
            out["page_end"] = pg_end
    if out.get("occurrences", 1) > 1:
        out["warnings"].append(f"multiple_matches({out['occurrences']}+) — page reported for the first")
    pr = parse_pincite(pincite)
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


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", help="extracted source text file")
    ap.add_argument("quotes", nargs="*", help="quote strings to verify")
    ap.add_argument("--json", dest="json_path", help="JSON file: [{id, quote, pincite}]")
    ap.add_argument("--first-page", type=int, default=1,
                    help="printed page number of the source's first page (form-feed sources)")
    args = ap.parse_args(argv)

    try:
        data = open(args.source, "rb").read()
        raw = data.decode("utf-8", "replace")
    except OSError as e:
        print(f"cannot read source: {e}", file=sys.stderr)
        return 2

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

    results = []
    for it in items:
        r = check_quote(raw, views, args.first_page, str(it.get("quote", "")), it.get("pincite"))
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
