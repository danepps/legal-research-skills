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
check("soft hyphen never blocks a match",
      rep["results"][0]["status"] in ("verbatim", "normalized"))

print("invisible characters + normalization form (regression 2026-10-19)")
rc, rep = run(SOURCE, ["the injury that\u200b forms the basis of the claim"])
check("zero-width space in the draft quote is ignored",
      rep["results"][0]["status"] in ("verbatim", "normalized"))
rc, rep = run("Cafe\u0301 society under \u00a7 1983 is well known.", ["Caf\u00e9 society under \u00a7 1983"])
check("NFD source vs NFC draft (decomposed accent) still matches",
      rep["results"][0]["status"] in ("verbatim", "normalized"))

print("dash forms (regression 2026-10-19)")
CLOSED = "The plaintiff knows\u2014or reasonably should know\u2014of the injury that forms the claim."
for label, q in (("spaced em dash", "knows \u2014 or reasonably should know \u2014 of the injury"),
                 ("double hyphen", "knows--or reasonably should know--of the injury"),
                 ("closed em dash", "knows\u2014or reasonably should know\u2014of the injury"),
                 ("spaced en dash", "knows \u2013 or reasonably should know \u2013 of the injury")):
    rc, rep = run(CLOSED, [q])
    check("closed-up em dash in the source matches a draft's %s" % label,
          rep["results"][0]["status"] in ("verbatim", "normalized"))
rc, rep = run("It is well-settled that the rule applies.", ["It is wellsettled that the rule applies"])
check("a real hyphen still joins its halves", rep["results"][0]["status"] == "normalized")

print("inline hyphens (CLAUDE-03 regression)")
HY = ("The contract was re-signed by the parties after the estab-\n"
      "lished deadline had passed, and it was estab-lished practice.\n")
rc, rep = run(HY, ["The contract was resigned by the parties"])
r = rep["results"][0]
check("meaningful hyphen: source 're-signed' vs draft 'resigned' -> not_found",
      r["status"] == "not_found")
check("...and word_diff surfaces it as a changed word",
      any(c.get("draft") == "resigned" and c.get("source") == "re signed"
          for c in r.get("word_diff", {}).get("changed", [])))
rc, rep = run(HY, ["The contract was re-signed by the parties"])
check("same hyphen on both sides -> verbatim", rep["results"][0]["status"] == "verbatim")
rc, rep = run(HY, ["after the established deadline had passed"])
check("hyphen at a line wrap still joins (normalized), no inline warning",
      rep["results"][0]["status"] == "normalized"
      and not any("inline_hyphen" in w for w in rep["results"][0]["warnings"]))
rc, rep = run(HY, ["it was established practice"])
r = rep["results"][0]
check("inline wrap hyphen 'estab-lished' vs draft 'established' -> normalized, flagged",
      r["status"] == "normalized" and any("inline_hyphen_joined(established)" in w for w in r["warnings"]))
rc, rep = run("The pre-trial order was entered.", ["The pretrial order was entered"])
check("prefix hyphen ('pre-trial' vs 'pretrial') is a word boundary -> not_found",
      rep["results"][0]["status"] == "not_found")
rc, rep = run("The pre-trial order was entered.", ["The pre-trial order was entered"])
check("prefix hyphen identical on both sides -> verbatim", rep["results"][0]["status"] == "verbatim")

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

rc, rep = run(SOURCE, ["the limitations period does not begin to run . . . ."])
check("quote with only a TRAILING ellipsis -> altered, not not_found (regression 2026-10-19)",
      rep["results"][0]["status"] == "altered")
rc, rep = run(SOURCE, [". . . until the plaintiff knows"])
check("quote with only a LEADING ellipsis -> altered",
      rep["results"][0]["status"] == "altered")
rc, rep = run(SOURCE, ["the limitations period does not stop . . . ."])
check("trailing-ellipsis quote whose text differs is still not_found",
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

print("repeated passage + pincite (CLAUDE-09 regression)")
REPEAT = ("<<pg. 10>>\nThe rule is clear and settled here.\n"
          "<<pg. 12>>\nUnrelated page.\n"
          "<<pg. 15>>\nAgain the rule is clear and settled here.\n")
PINS = [{"id": "p15", "quote": "rule is clear and settled", "pincite": "15"},
        {"id": "p10", "quote": "rule is clear and settled", "pincite": "10"},
        {"id": "p12", "quote": "rule is clear and settled", "pincite": "12"},
        {"id": "range", "quote": "rule is clear and settled", "pincite": "14-16"},
        {"id": "nopin", "quote": "rule is clear and settled"}]
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as jf:
    json.dump(PINS, jf)
    jpath = jf.name
rc, rep = run(REPEAT, ["--json", jpath])
os.unlink(jpath)
by_id = {r["id"]: r for r in rep["results"]}
check("pinned to the SECOND occurrence's page -> that page, pincite_ok true",
      by_id["p15"].get("page") == 15 and by_id["p15"].get("pincite_ok") is True)
check("pinned to the first -> page 10, pincite_ok true",
      by_id["p10"].get("page") == 10 and by_id["p10"].get("pincite_ok") is True)
check("pinned to a page with no occurrence -> first reported, pincite_ok false, warning says none inside",
      by_id["p12"].get("page") == 10 and by_id["p12"].get("pincite_ok") is False
      and any("none falls inside the pincite" in w for w in by_id["p12"]["warnings"]))
check("a pincite RANGE covering the second occurrence picks it",
      by_id["range"].get("page") == 15 and by_id["range"].get("pincite_ok") is True)
check("occurrences counted and their pages listed for every repeated match",
      all(by_id[k].get("occurrences") == 2 and by_id[k].get("occurrence_pages") == [10, 15]
          for k in by_id))
check("without a pincite: first occurrence, warning lists both pages",
      by_id["nopin"].get("page") == 10
      and any("pages [10, 15]" in w for w in by_id["nopin"]["warnings"]))

print("token boundaries (regression 2026-11-14: substring matches passed as verbatim)")
def _status(source, quote, extra=()):
    rc, rep = run(source, [quote] + list(extra))
    return rep["results"][0]

for label, source, quote in (
    ("dropped negative prefix (ineligible)", "It is ineligible for copyright protection.",
     "eligible for copyright protection"),
    ("dropped negative prefix (unreasonable)",
     "It was unreasonable to exclude county and state nursing home facilities.",
     "reasonable to exclude county and state nursing home facilities"),
    ("truncated amount, quote ends at the comma", "They must pay more than $400,000 now.",
     "pay more than $400,"),
    ("truncated amount, no comma", "They must pay more than $400,000 now.", "pay more than $400"),
    ("truncated decimal", "The fee rose to $3.5 million last year.", "The fee rose to $3"),
    ("number cut at its start", "They must pay more than $400,000 now.", "000 now"),
    ("word cut at its end", "The agency acted reasonably in this case.", "The agency acted reason"),
    ("truncated digits", "under section 1983 of the Act", "under section 198"),
    ("identifier cut before its letter", "liability under Rule 10b-5 is strict", "liability under Rule 10"),
    ("contraction cut at the apostrophe", "The defendant can't be retried here.", "The defendant can"),
    ("possessive cut at a curly apostrophe", "It reviewed the court’s findings.", "reviewed the court"),
    ("hyphenated negative prefix", "That is non-binding precedent in this circuit.",
     "binding precedent in this circuit"),
    ("first half of a hyphenated compound", "the decision-making process was flawed", "the decision"),
    ("prefix broken across a line", "The work is in-\neligible for copyright protection.",
     "eligible for copyright protection"),
    ("prefix broken across a page", "The work is in-\n\feligible for copyright protection.",
     "eligible for copyright protection"),
    ("soft hyphen inside the source word", "The work is in\u00adeligible for copyright protection.",
     "eligible for copyright protection"),
    ("accented letter before the match", "Their naïveté was plain.", "veté was plain"),
    ("combining mark after the match", "The x\u0302 term governs here.", "The x"),
    ("statute cite cut one digit short", "It was made under N.J.S.A. 47:1A-11 of the Act.",
     "made under N.J.S.A. 47:1A-1"),
    ("prefix split off by a soft hyphen at a line end",
     "The rule is un\u00ad\nnecessary because the amendment covers it.",
     "necessary because the amendment covers it"),
    ("first half before a soft hyphen at a line end",
     "We hold the rule is un\u00ad\nnecessary because the amendment covers it.", "We hold the rule is un"),
):
    r = _status(source, quote)
    check("%s -> not_found, partial_token_match reported" % label,
          r["status"] == "not_found" and r.get("partial_token_match")
          and "INSIDE a longer" in r.get("reason", ""))

r = _status("It is ineligible for copyright protection.", "eligible for copyright protection")
check("the partial match names the source's own word",
      "ineligible" in r["partial_token_match"]
      and any(c["draft"] == "eligible" and "ineligible" in c["source"]
              for c in r.get("word_diff", {}).get("changed", [])))

for label, source, quote, want in (
    ("identical text", "eligible for copyright protection", "eligible for copyright protection", "verbatim"),
    ("whole amount", "They must pay more than $400,000 now.", "pay more than $400,000", "verbatim"),
    ("whole word before a comma", "In 2020, 15 states acted.", "In 2020", "verbatim"),
    ("whole word before a period", "It was eligible. The rest follows.", "It was eligible", "verbatim"),
    ("whole hyphenated compound", "That is non-binding precedent.", "non-binding precedent", "verbatim"),
    ("word after a closed-up em dash", "The plaintiff knows—or should know—of it.",
     "or should know", "verbatim"),
    ("word after a typed double hyphen", "The plaintiff knows--or should know--of it.",
     "or should know", "verbatim"),
    ("word after a suspended hyphen", "the pre- and post-trial motions", "and post-trial motions", "verbatim"),
    ("page range cut at its hyphen", "See id. at 516-17 for the rule.", "See id. at 516", "verbatim"),
    ("possessive kept whole", "It reviewed the court's findings.", "the court's findings", "verbatim"),
    ("quoted word inside single quotes", "the 'reasonable' test applies", "reasonable", "verbatim"),
    ("whole word across a wrap hyphen", "The work is in-\neligible for protection.",
     "ineligible for protection", "normalized"),
):
    r = _status(source, quote)
    check("%s still matches (%s)" % (label, want), r["status"] == want and not r["warnings"])

r = _status("It is ineligible for protection here. Later it became eligible for protection again.",
            "eligible for protection")
check("a whole-token occurrence after a partial one is the match",
      r["status"] == "verbatim" and r.get("occurrences") == 1
      and r["match_excerpt"] == "eligible for protection")

TWO_PAGES = ("<<pg. 10>> It is ineligible for protection. It is eligible for protection.\n"
             "<<pg. 15>> Again, eligible for protection. And ineligible for protection.")
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as jf:
    json.dump([{"id": "p15", "quote": "eligible for protection", "pincite": "15"}], jf)
try:
    rc, rep = run(TWO_PAGES, ["--json", jf.name])
finally:
    os.unlink(jf.name)
r = rep["results"][0]
check("occurrence counting and pincite selection skip partial hits",
      r["status"] == "verbatim" and r.get("occurrences") == 2
      and r.get("occurrence_pages") == [10, 15] and r.get("page") == 15 and r.get("pincite_ok") is True)

r = _status("The work is “in\u00adeligible” for copy\u00adright protection.",
            "eligible' for copyright protection")
check("folded matching applies the same rule", r["status"] == "not_found")

r = _status("The statute is clearly ineligible for protection under the Act.",
            "The statute is . . . eligible for protection")
check("an ellipsis segment may not start inside a word", r["status"] == "not_found")
r = _status("The statute is clearly eligible for protection under the Act.",
            "The statute is . . . eligible for protection")
check("a whole-token ellipsis segment still matches", r["status"] == "altered")
r = _status("The court said the statute was unreasonable to apply.",
            "[T]he statute was . . . reasonable to apply")
check("a segment after an ellipsis is checked even when another starts with a bracket",
      r["status"] == "not_found")
r = _status("Yesterday the court held that the claim fails.", "[T]he court held that the claim fails")
check("a bracketed first letter still matches mid-word", r["status"] == "altered")
r = _status("It said the agency was unreasonable in its view.", "the agency [is] reasonable in its view")
check("a bracket does not excuse the segment's other edge",
      _status("It said the agency was reasonable in its views.",
              "the agency [is] reasonable in its view")["status"] == "not_found"
      and r["status"] in ("altered", "not_found"))

r = _status("The work receives copyright protection12 under the statute.", "receives copyright protection")
check("a flattened footnote call after a word matches, with a warning",
      r["status"] == "verbatim" and any(w.startswith("match_abuts_digits") for w in r["warnings"]))
r = _status("The Act was passed in 1871.45 The Court later read it broadly.", "The Act was passed in 1871.")
check("a footnote call after a sentence-ending number matches, with a warning",
      r["status"] == "verbatim" and any(w.startswith("match_abuts_digits") for w in r["warnings"]))
r = _status("Under section 1983,45 plaintiffs may sue.", "Under section 1983")
check("a footnote call after a comma is not a thousands separator",
      r["status"] == "verbatim" and any(w.startswith("match_abuts_digits") for w in r["warnings"]))

rc, rep = run(SOURCE, [])
check("no quotes -> usage error rc 2", rc == 2)

rc, rep = run(SOURCE, ["the injury that forms the basis"])
check("report carries source sha256 + char count",
      len(rep.get("sha256", "")) == 64 and rep.get("chars", 0) > 0)

print()
if failures:
    print(f"{failures} FAILURES")
    sys.exit(1)
print("--page mode (support pass, 2026-10-24)")
import tempfile as _tf
def _page(text, args):
    with _tf.TemporaryDirectory() as td:
        path = os.path.join(td, "src.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        p = subprocess.run([sys.executable, SCRIPT, path] + args, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr
rc, out, err = _page("intro *431 four thirty-one *432 four thirty-two *433 four thirty-three", ["--page", "432"])
check("star pagination: --page prints that page only", rc == 0 and "four thirty-two" in out and "four thirty-one" not in out and "marker: star" in out)
rc, out, err = _page("intro *431 four thirty-one *432 four thirty-two *433 four thirty-three", ["--page", "431-32"])
check("a range '431-32' expands and prints both pages", rc == 0 and "four thirty-one" in out and "four thirty-two" in out and "four thirty-three" not in out)
rc, out, err = _page("page one\fpage two\fpage three", ["--page", "816", "--first-page", "815"])
check("form feeds: --first-page maps printed numbers", rc == 0 and "page two" in out and "page one" not in out)
rc, out, err = _page("page one\fpage two\fpage three", ["--page", "900", "--first-page", "815"])
check("a page outside the file exits 1 and names the range", rc == 1 and "815" in err and "817" in err)
rc, out, err = _page("intro text on the first page *431 four thirty-one *432 four thirty-two *433 x", ["--page", "430"])
check("the text before the first star marker is page first-1, readable with --page", rc == 0 and "intro text" in out and "four thirty-one" not in out)
rc, out, err = _page("no markers here at all", ["--page", "5"])
check("no page boundaries -> exit 1 with advice", rc == 1 and "no page boundaries" in err)

print("all tests passed")
