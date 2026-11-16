#!/usr/bin/env python3
"""Check every quotation in a saved research memo against the sources it cites, by script.

The pipeline's cite-check confirms that each authority exists and is cited correctly. In lean
mode it does not re-open an opinion to confirm the words quoted from it or the page they are on,
so a memo's quotations rest on one reading agent's capture. This script closes that gap after the
memo is saved, without a model reading anything: it pulls each quotation and the citation it hangs
on out of the memo, finds a copy of the source, and runs the cite-check skill's deterministic
verifier (verify_quotes.py) over it.

    check_memo_quotes.py <memo.md> [--sources DIR ...] [--fetch] [--append] [--workdir DIR]

--sources DIR  a folder searched recursively for local copies of the cases: .pdf or .txt files
               whose NAME carries the reporter cite ("Carter v. United States, 530 U.S. 255
               (2000).pdf"). Repeatable. A local copy is preferred to anything fetched.
--fetch        for a case with no local copy, try the public web: a URL in the memo's own
               footnote (Caselaw Access Project, Justia, LII, supremecourt.gov), then the Caselaw
               Access Project page built from a U.S. Reports cite, then CourtListener's API text.
--append       write the results into the memo as an addendum, placed before the final
               "Production details" block. Refused (exit 2) if the memo already has one.
--workdir DIR  where extracted source text is kept (default: a new temporary folder).

It prints a JSON summary: counts, every quotation's result, the pins that differ from the page
found, the quotations not found, and the citations no source could be found for. It does not
change the memo's body; fix a differing pin by hand after looking at the page.

What a result means. "verbatim" / "normalized" / "altered" are the verifier's tiers (exact;
typographic differences only; exact once the memo's marked ellipses and [brackets] are honored).
"found_elsewhere" means the words are in a different source the memo cites, which usually signals
a quotation inside a quotation or a wrong footnote. "not_found" is a prompt to look at the page,
not proof of a misquotation: a quotation that runs across a page break under a footnote, or bad
OCR, can defeat the match. Pages come from the source's own page breaks: star pagination where the
text has it, otherwise counted from the first page of a local PDF, which is right only if the PDF
starts on the report's first page. The summary says which for every source.

Stdlib only; needs pdftotext for PDFs. Uses fetch_page.py and cl_case_tools.py from this folder
and ../cite-check/scripts/verify_quotes.py.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFIER = HERE.parent / "cite-check" / "scripts" / "verify_quotes.py"
FETCH_PAGE = HERE / "fetch_page.py"

REPORTER = r"(U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.(?:\s?(?:2d|3d|4th))?|F\.\s?Supp\.(?:\s?[23]d)?)"
CITE = re.compile(r"\b(\d{1,3})\s+" + REPORTER + r"\s+(?:\([^)]{1,20}\)\s+)?(\d{1,5})\b")
SHORT = re.compile(r"\b(\d{1,3})\s+" + REPORTER + r"\s+at\s+(\d{1,5})")
FOOTNOTE_DEF = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
MARKER_RUN = re.compile(r"(?:\[\^[^\]]+\])+")
MARKER = re.compile(r"\[\^([^\]]+)\]")
URL = re.compile(r"https?://[^\s)>\]]+")
END_OF_BODY = re.compile(r"^## (Table of Authorities|Limits of this research|Addendum)", re.M)
ADDENDUM_TITLE = "## Addendum: quotation check against the sources"
FETCHABLE = ("static.case.law", "supreme.justia.com", "law.cornell.edu", "supremecourt.gov", "tile.loc.gov", "govinfo.gov")


def key_of(vol, rep, page):
    return "%s %s %s" % (vol, re.sub(r"[^a-z0-9]", "", rep.lower()), page)


def show_key(k):
    vol, rep, page = k.split(" ")
    return "%s %s %s" % (vol, {"us": "U.S.", "sct": "S. Ct."}.get(rep, rep), page)


def page_ranges(text):
    """Page ranges named in a footnote: the pin after a full cite and every "at N" or "at N-M"."""
    out = []
    spans = [m.group(1) for m in re.finditer(r"\bat\s+(\d{1,5}(?:\s*[-–]\s*\d{1,5})?)", text)]
    for m in CITE.finditer(text):
        tail = re.match(r",\s*((?:\d{1,5}(?:\s*[-–]\s*\d{1,5})?(?:,\s*)?)+)", text[m.end():])
        if tail:
            spans += re.findall(r"\d{1,5}(?:\s*[-–]\s*\d{1,5})?", tail.group(1))
    for s in spans:
        a, _, b = re.sub(r"\s", "", s).replace("–", "-").partition("-")
        lo = int(a)
        hi = lo
        if b:
            hi = int(a[: len(a) - len(b)] + b) if len(b) < len(a) else int(b)
        if hi >= lo:
            out.append((lo, hi))
    return out


def parse_memo(text):
    """Footnotes (id -> {text, keys, pins, urls}) and the quotations with their candidate notes."""
    end = END_OF_BODY.search(text)
    body = text[: end.start()] if end else text
    notes, order, body_lines, current = {}, [], [], None
    for line in body.split("\n"):
        m = FOOTNOTE_DEF.match(line)
        if m:
            current = m.group(1)
            notes[current] = {"text": m.group(2)}
            order.append(current)
        elif current and line.startswith(("    ", "\t")) and line.strip():
            notes[current]["text"] += " " + line.strip()
        else:
            current = None
            body_lines.append(line)
    full = {}
    for m in CITE.finditer(text):
        full.setdefault((m.group(1), re.sub(r"[^a-z0-9]", "", m.group(2).lower())), set()).add(int(m.group(3)))

    def keys_in(s, fallback):
        keys = [key_of(*m.groups()) for m in CITE.finditer(s)]
        for m in SHORT.finditer(s):
            firsts = [p for p in full.get((m.group(1), re.sub(r"[^a-z0-9]", "", m.group(2).lower())), ()) if p <= int(m.group(3))]
            if firsts:
                keys.append(key_of(m.group(1), m.group(2), max(firsts)))
        if not keys and fallback and re.match(r"\W*id\b", s, re.I):
            keys = [fallback]
        return list(dict.fromkeys(keys))

    previous = None
    for fid in order:
        n = notes[fid]
        n["keys"] = keys_in(n["text"], previous)
        n["pins"] = page_ranges(n["text"])
        n["urls"] = URL.findall(n["text"])
        if n["keys"]:
            previous = n["keys"][0]

    quotes = []

    def add(q, note_ids, inline_keys, where, inline_pins=()):
        q = re.sub(r"\[\^[^\]]+\]", "", q)
        q = re.sub(r"\*+|(?<!\w)_+|_+(?!\w)", "", q).strip()
        if len(q.split()) >= 2:
            quotes.append({"quote": q, "notes": note_ids, "inlineKeys": inline_keys, "inlinePins": inline_pins, "where": where})

    def inline_quotes(par, where, own_note=None):
        for m in re.finditer(r"“([^”]+)”|\"([^\"]+)\"", par):
            q = m.group(1) or m.group(2)
            after = MARKER_RUN.search(par, m.end())
            runs_before = list(MARKER_RUN.finditer(par[: m.start()]))
            ids = MARKER.findall(after.group(0)) if after else (MARKER.findall(runs_before[-1].group(0)) if runs_before else [])
            if own_note:
                ids = [own_note]
            add(q, ids, keys_in(par, None), where, page_ranges(par))

    paragraphs = re.split(r"\n\s*\n", "\n".join(body_lines))
    last_markers = []
    for par in paragraphs:
        lines = [l for l in par.split("\n") if l.strip()]
        if not lines:
            continue
        if all(l.lstrip().startswith(">") for l in lines):
            q = " ".join(re.sub(r"^\s*>\s?", "", l) for l in lines)
            add(q, MARKER.findall(q) or last_markers, [], "blockquote")
        elif all(l.lstrip().startswith("|") for l in lines):
            for row in lines:
                inline_quotes(row, "table")
        else:
            inline_quotes(par, "text")
        runs = list(MARKER_RUN.finditer(par))
        if runs:
            last_markers = MARKER.findall(runs[-1].group(0))
    for fid in order:
        inline_quotes(notes[fid]["text"], "note %s" % fid, own_note=fid)
    return notes, quotes


class Sources:
    """Finds and caches one text file per reporter cite."""

    def __init__(self, dirs, fetch, workdir):
        self.fetch, self.workdir, self.cache, self.local = fetch, Path(workdir), {}, {}
        seen = 0
        for d in dirs:
            for root, subdirs, files in os.walk(os.path.expanduser(d)):
                subdirs[:] = [s for s in subdirs if not s.startswith(".")]
                for f in files:
                    seen += 1
                    if seen > 50000:
                        break
                    if f.lower().endswith((".pdf", ".txt")):
                        for m in CITE.finditer(f):
                            self.local.setdefault(key_of(*m.groups()), os.path.join(root, f))

    def _out(self, key, tag):
        return self.workdir / ("%s-%s.txt" % (re.sub(r"\W+", "_", key), tag))

    def _pdf_text(self, pdf, out):
        if not shutil.which("pdftotext"):
            return "pdftotext is not installed"
        p = subprocess.run(["pdftotext", "-layout", str(pdf), str(out)], capture_output=True, text=True)
        return None if p.returncode == 0 and out.exists() and out.stat().st_size > 200 else "pdftotext produced no text (%s)" % p.stderr.strip()[:80]

    def _cap(self, url, out):
        """A Caselaw Access Project page, with its page labels kept as <<pg. N>> marks (the form the
        verifier takes at face value: the labels restart in the footnote section, so they are not
        one ascending run) and its footnote reference numbers dropped. A plain text extraction glues both to the neighbouring word
        ("*222has made a crime", "*3483"), which hides the quotation and corrupts the page."""
        req = urllib.request.Request(url, headers={"User-Agent": "legal-research-skill quote check"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            h = resp.read(8_000_000).decode("utf-8", "replace")
        h = re.sub(r'<a[^>]*class="page-label"[^>]*>\s*\*?(\d+)\s*</a>', r" <<pg. \1>> ", h)
        h = re.sub(r'<a[^>]*class="footnotemark"[^>]*>[^<]*</a>', "", h)
        h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", h)
        h = h.replace("<<pg. ", "\x00pg. ").replace(">> ", "\x01 ")
        t = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"</(p|div|blockquote|h\d|li|aside|section)>|<br\s*/?>", "\n", h)))
        out.write_text(t.replace("\x00pg. ", "<<pg. ").replace("\x01 ", ">> "), encoding="utf-8")
        return out.stat().st_size > 2000

    def _fetch_url(self, url, out):
        if "static.case.law" in url:
            return self._cap(url, out)
        p = subprocess.run([sys.executable, str(FETCH_PAGE), url, "--out", str(out)], capture_output=True, text=True, timeout=180)
        return out.exists() and out.stat().st_size > 2000

    def _courtlistener(self, key, out):
        sys.path.insert(0, str(HERE))
        import cl_case_tools as cl  # noqa: E402  (same folder)

        hit = cl.lookup_cite(show_key(key))
        if not hit.get("cluster_id"):
            return False
        got = cl.request("%s/api/rest/v4/opinions/?cluster=%s&fields=id,type,ordering_key,html_with_citations,plain_text" % (cl.BASE, hit["cluster_id"]))
        parts = []
        for o in sorted(got.get("results") or [], key=lambda o: (o.get("ordering_key") is None, o.get("ordering_key") or 0, o.get("type") or "")):
            h = o.get("html_with_citations") or ""
            h = re.sub(r'<(span|a)[^>]*class="[^"]*(?:star-pagination|page-label|page-number)[^"]*"[^>]*>\s*\*?(\d+)\s*</\1>', r" <<pg. \2>> ", h)
            h = h.replace("<<pg. ", "\x00pg. ").replace(">> ", "\x01 ")
            t = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"</(p|div|blockquote|h\d)>|<br\s*/?>", "\n", h))) if h else (o.get("plain_text") or "")
            t = t.replace("\x00pg. ", "<<pg. ").replace("\x01 ", ">> ")
            # This text is often a slip opinion, whose page breaks are not reporter pages: drop
            # them, so that a page is reported only where the text carries star pagination.
            t = t.replace("\f", "\n")
            if t.strip():
                parts.append(t)
        if not parts:
            return False
        out.write_text("\n\n".join(parts), encoding="utf-8")
        return out.stat().st_size > 2000

    def get(self, key, urls=()):
        if key in self.cache:
            return self.cache[key]
        first = int(key.split(" ")[2])
        src = {"key": key, "path": None, "firstPage": first, "origin": None, "pages": None, "why": "no local copy" + ("" if self.fetch else "; --fetch not given")}
        local = self.local.get(key)
        if local:
            out = self._out(key, "local")
            err = self._pdf_text(local, out) if local.lower().endswith(".pdf") else None
            if not err:
                src.update(path=str(out if local.lower().endswith(".pdf") else local), origin="local file: " + os.path.basename(local),
                           pages="counted from the first page of the file" if local.lower().endswith(".pdf") else "from the file's own page marks")
            else:
                src["why"] = err
        if not src["path"] and self.fetch:
            tries = [u for u in urls if any(h in u for h in FETCHABLE)]
            if key.split(" ")[1] == "us":
                tries.append("https://static.case.law/us/%s/html/%04d-01.html" % (key.split(" ")[0], first))
            for i, u in enumerate(dict.fromkeys(tries)):
                out = self._out(key, "web%d" % i)
                try:
                    if self._fetch_url(u, out):
                        src.update(path=str(out), origin="fetched: " + u, pages="star pagination in the fetched text, where present")
                        break
                except (subprocess.SubprocessError, OSError, ValueError):
                    pass
            if not src["path"]:
                out = self._out(key, "cl")
                try:
                    if self._courtlistener(key, out):
                        src.update(path=str(out), origin="fetched: CourtListener API text", pages="star pagination in the fetched text, where present (slip-opinion text has none)")
                except Exception as e:  # network, token, or an unexpected response: reported, not fatal
                    src["why"] = "no local copy; fetch failed (%s)" % str(e)[:80]
            if not src["path"] and src["why"] == "no local copy":
                src["why"] = "no local copy; nothing fetchable"
        self.cache[key] = src
        return src


def verify(src, quote, workdir):
    """One quotation against one source. A closing period, comma, semicolon or colon is placed
    inside the quotation marks by convention whether or not the source has it there, so a
    quotation that fails only with that mark is tried again without it."""
    r = verify_once(src, quote, workdir)
    bare = quote.rstrip().rstrip(".,;:").rstrip()
    if r.get("status") not in ("verbatim", "normalized", "altered") and bare != quote.rstrip() and len(bare.split()) >= 2:
        r2 = verify_once(src, bare, workdir)
        if r2.get("status") in ("verbatim", "normalized", "altered"):
            r2["closingMark"] = "the memo's closing punctuation mark is not in the source at that point"
            return r2
    return r


def verify_once(src, quote, workdir):
    qfile = Path(workdir) / "q.json"
    qfile.write_text(json.dumps([{"id": "q", "quote": quote}]), encoding="utf-8")
    p = subprocess.run([sys.executable, str(VERIFIER), src["path"], "--json", str(qfile), "--first-page", str(src["firstPage"])], capture_output=True, text=True)
    try:
        doc = json.loads(p.stdout)
        r = doc["results"][0]
        r["pageMarks"] = (doc.get("page_boundaries") or {}).get("marker")
        return r
    except (ValueError, KeyError, IndexError):
        return {"status": "error", "error": (p.stderr or p.stdout)[:200]}


def check(memo_text, sources, workdir):
    notes, quotes = parse_memo(memo_text)
    rows = []
    for q in quotes:
        cand, pins, urls, cited = [], [], [], []
        for fid in q["notes"]:
            n = notes.get(fid)
            if n:
                cand += n["keys"]
                pins += n["pins"]
                urls += n["urls"]
                cited.append("n.%s" % fid)
        cand = list(dict.fromkeys(cand + q["inlineKeys"]))
        pins = pins + list(q["inlinePins"])
        row = {"quote": q["quote"], "opening": " ".join(q["quote"].split()[:9]), "citedTo": ", ".join(cited) or "(no footnote)",
               "sources": [show_key(k) for k in cand[:4]], "memoPins": ["%d" % a if a == b else "%d-%d" % (a, b) for a, b in pins],
               "status": "no_source", "page": None, "checkedAgainst": None, "pin": "not judged"}
        missing = []
        for k in cand:
            src = sources.get(k, urls)
            if not src["path"]:
                missing.append("%s (%s)" % (show_key(k), src["why"]))
                continue
            r = verify(src, q["quote"], workdir)
            if row["status"] in ("no_source",):
                row["status"] = "not_found"
            if r.get("status") in ("verbatim", "normalized", "altered"):
                row.update(status=r["status"], page=r.get("page"), checkedAgainst="%s — %s" % (show_key(k), src["origin"]),
                           pageBasis=src["pages"] if r.get("pageMarks") != "none" else "no page marks in this text")
                row.pop("hint", None)
                break
            row["hint"] = (r.get("hint") or {}).get("text") if isinstance(r.get("hint"), dict) else r.get("hint")
            row["checkedAgainst"] = "%s — %s" % (show_key(k), src["origin"])
        row["missingSources"], row["_cand"] = missing, cand
        if row["status"] in ("verbatim", "normalized", "altered"):
            page = row["page"]
            if not isinstance(page, int):
                row["pin"] = "page unknown"
            elif not pins:
                row["pin"] = "no pin in the memo"
            else:
                row["pin"] = "matches" if any(a <= page <= b for a, b in pins) else "differs"
        rows.append(row)
    # A quotation not found in its own source, or with no citation attached (a table cell), is
    # looked for in the memo's other sources once all of them are in hand.
    for row in rows:
        cand = row.pop("_cand")
        if row["status"] in ("not_found", "no_source") and not (row["status"] == "no_source" and cand):
            for k, src in list(sources.cache.items()):
                if src["path"] and k not in cand:
                    r = verify(src, row["quote"], workdir)
                    if r.get("status") in ("verbatim", "normalized", "altered"):
                        row.update(status="found_elsewhere", page=r.get("page"), tier=r["status"],
                                   checkedAgainst="%s — %s" % (show_key(k), src["origin"]))
                        break
    return rows


def addendum(rows, today):
    def cell(s):
        return str(s if s not in (None, "", []) else "—").replace("|", "\\|").replace("\n", " ")

    names = {"verbatim": "Verbatim", "normalized": "Verbatim (typography only)", "altered": "Matches with the memo's marked changes",
             "found_elsewhere": "Found in a different source", "not_found": "NOT FOUND", "no_source": "Not checked (no source)", "error": "Not checked (error)"}
    checked = [r for r in rows if r["status"] not in ("no_source", "error")]
    out = [ADDENDUM_TITLE + " (%s)" % today, "",
           "Done by script (`check_memo_quotes.py`) after the memo was saved; no model read the sources. Each quotation was "
           "searched for in a copy of the source its footnote cites, using the cite-check skill's deterministic verifier. "
           "Of %d quotations, %d were checked and %d could not be, for want of a source." % (len(rows), len(checked), len(rows) - len(checked)),
           "", "A result of NOT FOUND is a prompt to look at the page, not proof of a misquotation. A page 'counted' from a local PDF "
           "is right only if the PDF begins on the report's first page. Paraphrases and the pins attached to them were not checked.", "",
           "| Quotation (opening words) | Cited to | Result | Page found | Memo's pin | Pin | Checked against |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            cell(r["opening"]), cell("; ".join([r["citedTo"]] + r["sources"][:1])), names.get(r["status"], r["status"]), cell(r["page"]),
            cell(", ".join(r["memoPins"][:4])), cell(r["pin"]), cell(r["checkedAgainst"] or "; ".join(r["missingSources"][:2]))))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("memo")
    ap.add_argument("--sources", action="append", default=[], help="folder of local case PDFs or text files (repeatable)")
    ap.add_argument("--fetch", action="store_true", help="fetch a public copy when there is no local one")
    ap.add_argument("--append", action="store_true", help="write the results into the memo as an addendum")
    ap.add_argument("--workdir", default="", help="folder for extracted source text")
    ap.add_argument("--verifier", default=str(VERIFIER), help="path to verify_quotes.py")
    a = ap.parse_args(argv)

    globals()["VERIFIER"] = Path(a.verifier)
    memo = Path(a.memo).expanduser()
    try:
        text = memo.read_text(encoding="utf-8")
    except OSError as e:
        print(json.dumps({"ok": False, "error": "cannot read the memo: %s" % e}))
        return 2
    if not Path(a.verifier).exists():
        print(json.dumps({"ok": False, "error": "verify_quotes.py not found at %s (pass --verifier)" % a.verifier}))
        return 2
    if a.append and ADDENDUM_TITLE in text:
        print(json.dumps({"ok": False, "error": "the memo already has a quotation-check addendum; remove it first to run again with --append"}))
        return 2
    workdir = a.workdir or tempfile.mkdtemp(prefix="memo-quotes-")
    Path(workdir).mkdir(parents=True, exist_ok=True)
    sources = Sources(a.sources, a.fetch, workdir)
    rows = check(text, sources, workdir)

    appended = False
    if a.append:
        block = addendum(rows, datetime.date.today().isoformat())
        at = text.rfind("\n---\n\nProduction details")
        new = (text[:at].rstrip("\n") + "\n\n" + block + text[at:]) if at >= 0 else (text.rstrip("\n") + "\n\n" + block)
        memo.write_text(new, encoding="utf-8")
        appended = True

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    brief = lambda r: {k: r.get(k) for k in ("opening", "citedTo", "sources", "status", "page", "memoPins", "pin", "checkedAgainst", "hint") if r.get(k) not in (None, [], "")}
    print(json.dumps({
        "ok": True, "memo": str(memo), "quotations": len(rows), "counts": counts, "appended": appended, "workdir": str(workdir),
        "pinDiffers": [brief(r) for r in rows if r["pin"] == "differs"],
        "notFound": [brief(r) for r in rows if r["status"] == "not_found"],
        "foundElsewhere": [brief(r) for r in rows if r["status"] == "found_elsewhere"],
        "noSource": sorted({m for r in rows if r["status"] == "no_source" for m in (r["missingSources"] or ["(no citation attached to the quotation)"])}),
        "sources": [{"cite": show_key(k), "origin": s["origin"], "pages": s["pages"]} for k, s in sources.cache.items() if s["path"]],
        "rows": [brief(r) for r in rows],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
