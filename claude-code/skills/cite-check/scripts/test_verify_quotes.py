#!/usr/bin/env python3
"""Self-test for verify_quotes.py — run: python3 test_verify_quotes.py

Plain asserts, no pytest dependency. Each case states the behavior it locks
in; several encode real failure modes from cite-check runs (NOTES items 10-12).
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "verify_quotes.py")

# A synthetic "pdftotext" source: page 461 then 462 (form feeds), with curly
# quotes, an em dash, a line-break hyphenation, a soft hyphen, a ligature,
# and a repeated phrase for the multiple-match warning.
PAGE1 = (
    "THE YALE LAW JOURNAL\n\n"
    "It is a settled principle that “the limitations period does not begin\n"
    "to run until the plaintiff knows — or reasonably should know — of the\n"
    "injury that forms the basis of the claim.” This doctrine, the well-\n"
    "settled discovery rule, reflects ﬁdelity to fairness. The de­fendant\n"
    "bears the burden. A settled principle indeed.\n"
)
PAGE2 = (
    "462\n\n"
    "The court held that “equitable tolling is reserved for extraordinary\n"
    "circumstances beyond the litigant’s control, and mere excusable\n"
    "neglect will not suffice.” A settled principle, twice repeated here:\n"
    "a settled principle.\n"
)
SOURCE = PAGE1 + "\f" + PAGE2


def run(source_text, args):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(source_text)
        path = f.name
    try:
        proc = subprocess.run([sys.executable, SCRIPT, path] + args,
                              capture_output=True, text=True, timeout=60)
        report = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc.returncode, report
    finally:
        os.unlink(path)


def case(name, cond):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


failures = 0

def check(name, cond):
    global failures
    if not case(name, cond):
        failures += 1


print("verbatim / normalized tiers")
rc, rep = run(SOURCE, ["the injury that forms the basis of the claim"])
r = rep["results"][0]
check("plain text across a line wrap -> verbatim, rc 0",
      rc == 0 and r["status"] == "verbatim")

rc, rep = run(SOURCE, ['"the limitations period does not begin to run until the '
                       'plaintiff knows--or reasonably should know--of the injury'])
r = rep["results"][0]
check("straight quotes + double-hyphen vs curly + em dash -> normalized",
      r["status"] == "normalized")

rc, rep = run(SOURCE, ["the well-settled discovery rule, reflects fidelity to fairness"])
r = rep["results"][0]
check("line-break hyphenation + ligature fold -> normalized",
      r["status"] == "normalized")

rc, rep = run(SOURCE, ["the wellsettled discovery rule"])
check("intra-word hyphen optional in both directions",
      rep["results"][0]["status"] == "normalized")

rc, rep = run(SOURCE, ["The defendant bears the burden"])
check("soft hyphen never blocks a match", rep["results"][0]["status"] == "normalized")

print("marked alterations")
rc, rep = run(SOURCE, ["the limitations period does not begin to run . . . of the "
                       "injury that forms the basis of the claim"])
r = rep["results"][0]
check("spaced Bluebook ellipsis, segments in order -> altered", r["status"] == "altered")

rc, rep = run(SOURCE, ["[T]he limitations period does not begin to run until the plaintiff knows"])
check("bracketed capitalization alteration -> altered",
      rep["results"][0]["status"] == "altered")

rc, rep = run(SOURCE, ["of the injury ... does not begin to run"])
check("out-of-order ellipsis segments do NOT match",
      rep["results"][0]["status"] == "not_found")

print("not_found + hint (the dropped-word trap)")
rc, rep = run(SOURCE, ["equitable tolling is reserved for circumstances beyond the "
                       "litigant's control, and mere excusable neglect will suffice"])
r = rep["results"][0]
check("dropped 'extraordinary' + dropped 'not' -> not_found, rc 1",
      rc == 1 and r["status"] == "not_found")
check("hint carries the source's actual words",
      "extraordinary" in r.get("hint", "") and "will not suffice" in r.get("hint", ""))

check("word_diff marks the dropped words as substantive (source_only)",
      "extraordinary" in r.get("word_diff", {}).get("source_only", [])
      and "not" in r.get("word_diff", {}).get("source_only", []))

OCR = ("It is settled that the prosecution may not use statements, whether "
       "exculpatory .or inculpatory, stemming from custodial interrogation "
       "of the defendant in any criminal proceeding whatsoever.")
rc, rep = run(OCR, ["the prosecution may not use statements, whether exculpatory "
                    "or inculpatory, stemming from custodial interrogation"])
r = rep["results"][0]
check("OCR stray punctuation -> not_found but diff is cosmetic only",
      r["status"] == "not_found"
      and r.get("word_diff", {}).get("cosmetic")
      and not r.get("word_diff", {}).get("draft_only")
      and not r.get("word_diff", {}).get("source_only")
      and not r.get("word_diff", {}).get("changed"))

rc, rep = run(SOURCE, ["the quick brown fox jumps over the lazy dog"])
check("unrelated text -> not_found with no misleading hint",
      rep["results"][0]["status"] == "not_found" and not rep["results"][0].get("hint"))

print("pages and pincites (form feed + --first-page)")
QUOTES = [
    {"id": 1, "quote": "the injury that forms the basis of the claim", "pincite": "461"},
    {"id": 2, "quote": "equitable tolling is reserved for extraordinary circumstances",
     "pincite": "462"},
    {"id": 3, "quote": "equitable tolling is reserved for extraordinary circumstances",
     "pincite": "461"},
]
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as jf:
    json.dump(QUOTES, jf)
    jpath = jf.name
rc, rep = run(SOURCE, ["--json", jpath, "--first-page", "461"])
os.unlink(jpath)
by_id = {r["id"]: r for r in rep["results"]}
check("page-1 match reported on printed page 461",
      by_id[1].get("page") == 461 and by_id[1].get("pincite_ok") is True)
check("page-2 match reported on printed page 462 (no footer off-by-one)",
      by_id[2].get("page") == 462 and by_id[2].get("pincite_ok") is True)
check("wrong pincite judged false, not silently passed",
      by_id[3].get("pincite_ok") is False)
check("boundary metadata reported",
      rep["page_boundaries"]["marker"] == "form-feed" and rep["page_boundaries"]["count"] == 1)

print("<<pg. N>> markers")
MARKED = "<<pg. 979>>\nAlpha beta gamma delta epsilon.\n<<pg. 980>>\nZeta eta theta iota kappa.\n"
rc, rep = run(MARKED, ["Zeta eta theta iota kappa"])
check("explicit markers carry their own printed numbers",
      rep["results"][0].get("page") == 980)
rc, rep = run(MARKED, ["Alpha beta gamma delta"])
check("text after the first marker is on that marker's page",
      rep["results"][0].get("page") == 979)

print("star pagination (CAP/CourtListener official-reporter text)")
STARRED = ("Opinion opening text on the first page. *182Second page text about "
           "equitable principles. *183Third page text about remedies for breach. "
           "*184Closing text of the opinion.")
rc, rep = run(STARRED, ["Third page text about remedies"])
check("ascending *N markers accepted; text after *183 is on page 183",
      rep["page_boundaries"]["marker"] == "star" and rep["results"][0].get("page") == 183)
rc, rep = run(STARRED, ["Opinion opening text on the first page"])
check("text before the first star marker is on the prior page",
      rep["results"][0].get("page") == 181)
NOISY = "A footnote *4 and later *2 and then *9 — not pagination."
rc, rep = run(NOISY, ["not pagination"])
check("non-ascending asterisk numbers rejected (marker none)",
      rep["page_boundaries"]["marker"] == "none")

print("ambiguity + hygiene")
rc, rep = run(SOURCE, ["A settled principle"])
r = rep["results"][0]
check("repeated phrase flags multiple_matches",
      any("multiple_matches" in w for w in r.get("warnings", [])))

rc, rep = run(SOURCE, [])
check("no quotes -> usage error rc 2", rc == 2)

rc, rep = run(SOURCE, ["the injury that forms the basis"])
check("report carries source sha256 + char count",
      len(rep.get("sha256", "")) == 64 and rep.get("chars", 0) > 0)

print()
if failures:
    print(f"{failures} FAILURES")
    sys.exit(1)
print("all tests passed")
