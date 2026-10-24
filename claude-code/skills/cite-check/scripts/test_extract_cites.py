#!/usr/bin/env python3
"""Self-test for extract_cites.py — run: python3 test_extract_cites.py

Builds a raw-OOXML .docx in a temp directory (no python-docx) with the
markup that bit real runs, runs the extractor as a subprocess, and locks in:
custom-mark author notes, deleted (w:del) footnote references, w:moveFrom,
w:br / w:noBreakHyphen, an sdt-wrapped footnote, a block quotation, a
single-quote quotation, the sentence split at a footnote marker, quote ->
footnote pairing, an unreferenced footnote, and the endnote warning. Plain
asserts, no pytest. Must pass on Python 3.9 and 3.12.
"""
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from xml.sax.saxutils import escape as esc

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "extract_cites.py")
WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
TC = 'w:author="Test" w:date="2026-10-19T00:00:00Z"'


# ---- raw OOXML builder -------------------------------------------------------
def r(text, italic=False):
    rpr = "<w:rPr><w:i/></w:rPr>" if italic else ""
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, esc(text))


def fn(fid):
    return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
            '<w:footnoteReference w:id="%d"/></w:r>' % fid)


def custom_fn(fid, mark):
    # Word: customMarkFollows="1" and the mark glyph is the run's own text
    return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
            '<w:footnoteReference w:customMarkFollows="1" w:id="%d"/>'
            '<w:t>%s</w:t></w:r>' % (fid, esc(mark)))


def ins(inner):
    return '<w:ins w:id="900" %s>%s</w:ins>' % (TC, inner)


def dele(text):
    return ('<w:del w:id="901" %s><w:r><w:delText xml:space="preserve">%s'
            '</w:delText></w:r></w:del>' % (TC, esc(text)))


def del_fn(fid):
    return ('<w:del w:id="902" %s><w:r><w:footnoteReference w:id="%d"/></w:r></w:del>'
            % (TC, fid))


def move_from(text):
    return ('<w:moveFrom w:id="903" %s><w:r><w:t xml:space="preserve">%s</w:t></w:r>'
            '</w:moveFrom>' % (TC, esc(text)))


def move_to(text):
    return ('<w:moveTo w:id="904" %s><w:r><w:t xml:space="preserve">%s</w:t></w:r>'
            '</w:moveTo>' % (TC, esc(text)))


def p(*runs, style=None, ind=None):
    ppr = ""
    if style:
        ppr += '<w:pStyle w:val="%s"/>' % style
    if ind:
        ppr += '<w:ind w:left="%d" w:right="%d"/>' % ind
    ppr = "<w:pPr>%s</w:pPr>" % ppr if ppr else ""
    return "<w:p>%s%s</w:p>" % (ppr, "".join(runs))


def note(fid, inner, wrap_sdt=False):
    para = ('<w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>'
            '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteRef/></w:r>'
            '<w:r><w:t xml:space="preserve"> </w:t></w:r>%s</w:p>' % inner)
    if wrap_sdt:
        para = "<w:sdt><w:sdtPr/><w:sdtContent>%s</w:sdtContent></w:sdt>" % para
    return '<w:footnote w:id="%d">%s</w:footnote>' % (fid, para)


BODY = [
    # Title with a custom-mark author note (not numbered by Word)
    p(r("The Taxing Power"), custom_fn(2, "*")),
    # n.1 (id 10), n.2 (id 11): sentence split at a marker; pairing to the
    # marker after the quote's END
    p(r("The Court held that “the power to tax involves the power to destroy” in a landmark case."), fn(10),
      r(" Scholars have called this “a remarkably durable principle of constitutional law that endures.”"), fn(11)),
    # id 12 inside w:ins (kept, n.3); id 13 inside w:del (NOT numbered); n.4 (id 14)
    p(r("This sentence has "), ins(r("inserted text with a footnote") + fn(12)),
      r(" and "), dele("deleted text with a footnote"), del_fn(13), r(" at the end."), fn(14)),
    # moveFrom / moveTo: the moved sentence must appear once
    p(move_from("A moved sentence that appears once."), r(" Stable text."), fn(15)),
    p(move_to("A moved sentence that appears once."), r(" After the move."), fn(16)),
    # br + noBreakHyphen inside the quote; n.7 (id 17)
    p(r("She wrote that “the well"), "<w:r><w:noBreakHyphen/></w:r>", r("settled rule"),
      "<w:r><w:br/></w:r>", r("has proven remarkably durable over two centuries.”"), fn(17)),
    # quote spanning a marker (id 18 mid-quote; id 19 supports it): n.8, n.9
    p(r("He added that “the doctrine"), fn(18), r(" has proven remarkably durable over two full centuries.”"), fn(19)),
    # single-quote quotation with apostrophes nearby; n.10 (id 20)
    p(r("The plaintiff’s brief said ‘this is a single quoted phrase of eight words’ and rested."), fn(20)),
    # block quote by style (no quotation marks); n.11 (id 21)
    p(r("This is a block quotation of considerable length that carries no quotation marks at all and must still be checked."), fn(21), style="BlockQuote"),
    # block quote by indentation; n.12 (id 22)
    p(r("A second block quotation set off only by indentation on both sides also counts as a quotation here."), fn(22), ind=(720, 720)),
    # marker BEFORE the quote in the same sentence (pairs backwards): n.13 (id 23)
    p(r("As Smith argued,"), fn(23), r(" “the framers never intended the clause to reach this far at all.”")),
]
DOCUMENT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document %s><w:body>%s<w:sectPr/></w:body></w:document>' % (WNS, "".join(BODY)))

NOTES = {
    2: note(2, r("Professor of Law. Thanks to colleagues.")),
    10: note(10, r("McCulloch v. Maryland, 17 U.S. (4 Wheat.) 316, 431 (1819).")),
    11: note(11, r("Jane Doe, ") + r("The Taxing Power Reconsidered", italic=True) + r(", 110 Harv. L. Rev. 815, 820 (1997).")),
    12: note(12, r("See, e.g., ") + r("id.", italic=True) + r(" at 5.")),
    13: note(13, r("Deleted-reference footnote: Roe v. Wade, 410 U.S. 113 (1973).")),
    14: note(14, r("Id.", italic=True) + r(" at 436."), wrap_sdt=True),
    15: note(15, r("Doe, ") + r("supra", italic=True) + r(" note 2, at 821.")),
    16: note(16, r("Wu, ") + r("supra", italic=True) + r(" note 1, at 7.")),
    17: note(17, r("Id.", italic=True) + r(" at 437.")),
    18: note(18, r("Merrill, Landscape, ") + r("supra", italic=True) + r(" note 2, at 914.")),
    19: note(19, r("Id.", italic=True) + r(" at 915.")),
    20: note(20, r("Brief for Petitioner at 12, Smith v. Jones, 536 U.S. 181 (2002).")),
    21: note(21, r("Smith v. Jones, 536 U.S. 181, 190 (2002).")),
    22: note(22, r("Id.", italic=True) + r(" at 191.")),
    23: note(23, r("Vol. 3 A. 5 (1990); 150 A. 300 (Pa. 1930); 5 Wall. 100; 2020 WL 123456.")),
    30: note(30, r("Orphan footnote never referenced in the body.")),
}
FOOTNOTES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes %s>'
             '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
             '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
             '%s</w:footnotes>' % (WNS, "".join(NOTES[i] for i in sorted(NOTES, reverse=True))))
ENDNOTES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:endnotes %s>'
            '<w:endnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:endnote>'
            '<w:endnote w:id="1"><w:p><w:r><w:t>A real endnote.</w:t></w:r></w:p></w:endnote>'
            '</w:endnotes>' % WNS)
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles %s>'
          '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="BlockQuote"><w:name w:val="Block Quote"/><w:basedOn w:val="Normal"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="FootnoteText"><w:name w:val="footnote text"/></w:style>'
          '<w:style w:type="character" w:styleId="FootnoteReference"><w:name w:val="footnote reference"/>'
          '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style></w:styles>' % WNS)
CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
                 '<Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                 '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')
DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>')


def build_docx(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", DOCUMENT)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/footnotes.xml", FOOTNOTES)
        z.writestr("word/endnotes.xml", ENDNOTES)
        z.writestr("word/styles.xml", STYLES)


# ---- run ---------------------------------------------------------------------
failures = 0


def check(name, cond):
    global failures
    print("  [%s] %s" % ("ok" if cond else "FAIL", name))
    if not cond:
        failures += 1


with tempfile.TemporaryDirectory() as td:
    docx = os.path.join(td, "draft.docx")
    out = os.path.join(td, "extract.json")
    build_docx(docx)
    proc = subprocess.run([sys.executable, SCRIPT, docx, out], capture_output=True, text=True)
    check("extract_cites.py exits 0", proc.returncode == 0)
    if proc.returncode != 0:
        print(proc.stderr)
        sys.exit(1)
    summary = json.loads(proc.stdout)
    data = json.load(open(out, encoding="utf-8"))
    fmt_path = data["form_checks"].get("fulltext_fmt")
    fmt = open(fmt_path, encoding="utf-8").read() if fmt_path else ""

notes = data["footnotes"]
by_num = {int(k): v for k, v in notes.items()}
by_xml = {v["xml_id"]: int(k) for k, v in notes.items()}
quotes = data["body_quotes"]
by_para = {}
for q in quotes:
    by_para.setdefault(q["para"], []).append(q)

print("numbering")
check("13 numbered footnotes (custom mark, deleted ref and orphan excluded)",
      data["footnote_count"] == 13 and sorted(by_num) == list(range(1, 14)))
check("xml ids map to body order: id 10 -> n.1, id 14 -> n.4, id 23 -> n.13",
      by_xml.get("10") == 1 and by_xml.get("14") == 4 and by_xml.get("23") == 13)
check("deleted footnote reference (id 13) is not numbered and is listed",
      "13" not in by_xml and data["deleted_footnote_ids"] == ["13"])
check("its text is not in unique_case_cites", "410 U.S. 113" not in data["unique_case_cites"])
check("custom-mark author note kept apart with number None and its mark",
      len(data["custom_mark_footnotes"]) == 1
      and data["custom_mark_footnotes"][0]["number"] is None
      and data["custom_mark_footnotes"][0]["custom_mark"] == "*"
      and data["custom_mark_footnotes"][0]["xml_id"] == "2"
      and "Professor of Law" in data["custom_mark_footnotes"][0]["text"])
check("custom-mark reference is not in the footnotes dict", "2" not in by_xml)
check("unreferenced footnote (id 30) listed, not numbered",
      data["unreferenced_footnote_ids"] == ["30"] and "30" not in by_xml)
check("sdt-wrapped footnote (n.4) is not empty",
      by_num[4]["text"] == "Id. at 436." and data["empty_footnote_ids"] == [])
check("endnotes trigger a loud warning in the summary",
      summary["endnote_count"] == 1 and any("ENDNOTES NOT CHECKED" in w for w in summary["warnings"]))
check("tracked insertions/deletions reported", data["tracked_insertions"] and data["tracked_deletions"])
check("signal-prefixed Id. ('See, e.g., id.') is a leading Id.", by_num[3]["leading_id"] is True)

print("footnote anchors (support pass, 2026-10-24)")
a1, a13, a11 = by_num[1]["anchor"], by_num[13]["anchor"], by_num[11]["anchor"]
check("n.1 anchor = its sentence, marker at sentence end",
      a1["position"] == "sentence-end" and a1["sentence"].startswith("The Court held that") and a1["clause"] == "")
check("n.2 anchor carries the preceding sentence (n.1's)", by_num[2]["anchor"]["previous"].startswith("The Court held that"))
check("marker BEFORE the quote (n.13) is mid-sentence with the clause before it",
      a13["position"] == "mid-sentence" and a13["clause"] == "As Smith argued," and "framers" in a13["sentence"])
check("block-quote paragraph (n.11) is flagged on its anchor", a11["block_quote"] is True)
check("no footnote without an anchor", summary.get("footnotes_without_anchor") == 0)

print("body text")
check("deleted text is gone, inserted text stays, deleted marker not rendered",
      "deleted text with a footnote" not in fmt and "inserted text with a footnote[[FN:12]]" in fmt
      and "[[FN:13]]" not in fmt)
check("moved text appears once (moveFrom skipped, moveTo kept)",
      fmt.count("A moved sentence that appears once.") == 1)
check("custom mark renders as [[FN:*]], never as a number", "[[FN:*]]" in fmt and "[[FN:2]]" not in fmt)
check("form layer still aligns every footnote and paragraph after the walker change",
      data["form_checks"]["available"] and data["form_checks"]["unaligned"] == 0
      and data["form_checks"]["aligned"] == 16 and fmt.count("[¶") == 11)

print("quotes")
q1 = by_para[1]
check("two quotes in the first body paragraph", len(q1) == 2)
check("sentence split at the footnote marker: each quote gets only its own sentence",
      q1[0]["sentence"] == "The Court held that “the power to tax involves the power to destroy” in a landmark case."
      and q1[1]["sentence"].startswith("Scholars have called this"))
# --- pair_footnote: paragraph-level fallback carries a basis flag -------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_cites as ec  # noqa: E402
_p = "Congress may “lay and collect Taxes.” It is a great power.[[FN:7]] More follows."
_sent = ec.sentence_span(_p, _p.index("“"), _p.index("”") + 1)
check("no marker in the sentence: falls back to the paragraph's next marker, flagged as a guess",
      ec.pair_footnote(_p, _sent, _p.index("“"), _p.index("”") + 1) == ("7", "paragraph-after"))
_p2 = "Earlier text.[[FN:3]] Congress may “lay and collect Taxes.” It is a great power."
_sent2 = ec.sentence_span(_p2, _p2.index("“"), _p2.index("”") + 1)
check("no marker after anywhere: falls back to the last marker before, flagged as a guess",
      ec.pair_footnote(_p2, _sent2, _p2.index("“"), _p2.index("”") + 1) == ("3", "paragraph-before"))
check("no marker in the paragraph at all: (None, None)",
      ec.pair_footnote("Congress may “lay and collect Taxes.” Plain.", (0, 44), 13, 37) == (None, None))

check("quote pairs with the marker after its END (n.1, n.2)",
      q1[0]["footnote"] == 1 and q1[1]["footnote"] == 2)
q5 = by_para[5][0]
check("w:noBreakHyphen -> '-' and w:br -> space inside a quote",
      q5["quote"] == "the well-settled rule has proven remarkably durable over two centuries.")
q6 = by_para[6][0]
check("marker INSIDE the quote is not the supporting note; the one after the close is (n.9), inside listed",
      q6["footnote"] == 9 and q6["footnotes_in_quote"] == [8])
q7 = by_para[7][0]
check("single-quote quotation extracted despite a nearby apostrophe",
      q7["quote"] == "this is a single quoted phrase of eight words" and q7["quote_marks"] == "single"
      and q7["footnote"] == 10)
q8 = by_para[8][0]
check("block quote by paragraph style -> block_quote true, pinned to its last marker (n.11)",
      q8["block_quote"] is True and q8["quote_marks"] == "none" and q8["footnote"] == 11
      and q8["quote"].startswith("This is a block quotation"))
check("block quote framing = last sentence of the preceding paragraph",
      "single quoted phrase" in q8["sentence"])
q9 = by_para[9][0]
check("block quote by both-sides indentation (n.12)", q9["block_quote"] is True and q9["footnote"] == 12)
q10 = by_para[10][0]
check("no marker after the quote: pairs with the marker before it in the same sentence (n.13)",
      q10["footnote"] == 13)
check("block_quote_count in summary", summary["block_quote_count"] == 2 and data["block_quote_count"] == 2)

print("case cites")
cites = data["unique_case_cites"]
check("parallel nominative cite yields the official form only",
      "17 U.S. 316" in cites and not any("Wheat" in c for c in cites))
check("'Vol. 3 A. 5' is not a cite; '150 A. 300', '5 Wall. 100', '2020 WL 123456' are",
      "3 A. 5" not in cites and {"150 A. 300", "5 Wall. 100", "2020 WL 123456"} <= set(cites))

print("supra")
claims = {(s["footnote"], s["claims"], s["supra_note"]) for s in data["supra_problem_candidates"]}
check("'Wu, supra note 1' (two-letter surname) is checked and flagged (n.1 is McCulloch)",
      (6, "Wu", 1) in claims)
check("'Doe, supra note 2' is NOT flagged (n.2 is Doe)", not any(c[0] == 5 for c in claims))
check("supra candidates carry the full target text", all("target_text" in s for s in data["supra_problem_candidates"]))

print()
if failures:
    print("%d FAILURES" % failures)
    sys.exit(1)
print("all tests passed")
