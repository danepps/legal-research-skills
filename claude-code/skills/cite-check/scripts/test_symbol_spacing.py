#!/usr/bin/env python3
"""Self-test for the space-after-§-and-¶ check in extract_cites.py's form layer.
Run: python3 test_symbol_spacing.py

The detector itself is tested with /proofread (proofread/scripts/test_symbol_spacing.py);
this locks in that cite-check runs it and reports it as ONE convention row with counts.
Synthetic OOXML in a temp directory; plain asserts, no pytest.
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
NBSP = " "
ISSUE = "space after § and ¶"


def r(text):
    return '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % esc(text)


def fn(fid):
    return '<w:r><w:footnoteReference w:id="%d"/></w:r>' % fid


def zotero(display):
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION {} </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + r(display) +
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def extract(body, notes):
    root = tempfile.mkdtemp(prefix="cite-check-symbol-spacing-")
    docx, out = os.path.join(root, "draft.docx"), os.path.join(root, "extract.json")
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document %s><w:body>%s</w:body></w:document>" % (WNS, body))
        z.writestr("word/footnotes.xml", "<w:footnotes %s>%s</w:footnotes>" % (WNS, notes))
        z.writestr("word/styles.xml", "<w:styles %s/>" % WNS)
    proc = subprocess.run([sys.executable, SCRIPT, docx, out], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    with open(out, encoding="utf-8") as f:
        return json.loads(proc.stdout), json.load(f)


failures = 0


def check(name, cond):
    global failures
    print("  [%s] %s" % ("ok" if cond else "FAIL", name))
    failures += 0 if cond else 1


print("a draft with ordinary spaces")
summary, data = extract(
    "<w:p>%s%s</w:p><w:p>%s%s</w:p>" % (
        r("Section 1983 liability under 42 U.S.C. § 1983 is settled."), fn(2),
        r("So is §" + NBSP + "1985."), fn(3)),
    '<w:footnote w:id="2"><w:p>%s</w:p></w:footnote><w:footnote w:id="3"><w:p>%s</w:p></w:footnote>' % (
        r("See Compl. ¶ 12; id. ¶" + NBSP + "14."), zotero("Example, A Title § 2 (2020).")))
form = data["form_checks"]
spacing = form["symbol_spacing"]
check("counts: 5 symbols, 2 non-breaking, 2 ordinary outside fields, 1 ordinary inside a Zotero field",
      (spacing["total"], spacing["nonbreaking"], spacing["ordinary"], spacing["ordinary_in_fields"]) == (5, 2, 2, 1))
check("examples carry a reader-facing place and a find string",
      spacing["examples"] == [{"location": "", "find": "liability under 42 U.S.C. § 1983"},
                              {"location": "note 1", "find": "See Compl. ¶ 12;"}])
rows = [c for c in form["conventions"] if c["issue"] == ISSUE]
check("one convention row, and it names the Word replacement and the Zotero caution",
      len(rows) == 1 and "^s" in rows[0]["recommendation"] and "unlinked" in rows[0]["recommendation"])
check("no per-symbol finding", not [f for f in form["findings"] if "§" in f.get("problem", "") and "break" in f.get("problem", "")])
check("summary line", summary.get("symbols_with_ordinary_space") == 2
      and summary.get("symbols_with_ordinary_space_in_fields") == 1)
check("the footnote text the checkers read is unchanged (one ordinary space)",
      data["footnotes"]["1"]["text"] == "See Compl. ¶ 12; id. ¶ 14.")

print("a clean draft")
summary, data = extract("<w:p>%s%s</w:p>" % (r("Under §" + NBSP + "1983."), fn(2)),
                        '<w:footnote w:id="2"><w:p>%s</w:p></w:footnote>' % r("Id. ¶" + NBSP + "3."))
form = data["form_checks"]
check("no row, zero counts",
      not [c for c in form["conventions"] if c["issue"] == ISSUE]
      and form["symbol_spacing"]["ordinary"] == 0 and summary.get("symbols_with_ordinary_space") == 0)

print()
if failures:
    print("%d FAILURES" % failures)
    sys.exit(1)
print("all tests passed")
