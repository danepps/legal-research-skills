#!/usr/bin/env python3
"""Checks for check_memo_quotes.py (2026-11-16), offline: a small memo, local source texts named by
reporter cite, and the cite-check skill's verifier. Covers which source each quotation is checked
against (footnote, Id., short form, blockquote, table cell), the pin comparison, a quotation that
is not in its source, a citation with no source, and the addendum.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "check_memo_quotes.py"
fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


ALPHA = ("Syllabus of the case.\n\f"
         "The statute is to be read as a whole, and its words taken in their ordinary sense.\n\f"
         "We hold that the rule applies only where the text is truly unclear after every\ntool of construction has been used.\n\f"
         "Justice Roe, dissenting. The Court today rewrites the statute.\n")
BETA = "Opening matter. <<pg. 41>> A penal law is construed strictly, but not so as to defeat the plain intent. <<pg. 42>> The remedy is for Congress.\n"

MEMO = """# Title

## 1. Analysis

The Court said the statute's words are "taken in their ordinary sense."[^1] It then held that the rule "applies only where the text is truly unclear."[^2] The dissent said the Court "rewrites the statute."[^3] An older case says a penal law "is construed strictly, but not so as to defeat the plain intent."[^4] One opinion reportedly says "lenity is dead and buried in this circuit."[^1] A third case says "nothing can be known of this."[^5]

In the Court's words:[^2]

> We hold that the rule applies only where the text is truly unclear after every tool of construction has been used.

| Case | Wording |
|---|---|
| *Beta* | "The remedy is for Congress" |

[^1]: *Alpha v. Beta*, 500 U.S. 10, 11 (1991), https://example.org/alpha.
[^2]: *Id.* at 13.
[^3]: *Alpha*, 500 U.S. at 13 (Roe, J., dissenting).
[^4]: *Beta v. Gamma*, 90 U.S. 40, 41 (1875).
[^5]: *Delta v. Epsilon*, 300 U.S. 5, 6 (1937).

## Table of Authorities

| *Alpha v. Beta*, 500 U.S. 10 (1991) | "not a quotation to check" |

---

Production details: test.
"""

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "cases").mkdir()
    (d / "cases" / "Alpha v. Beta, 500 U.S. 10 (1991).txt").write_text(ALPHA, encoding="utf-8")
    (d / "cases" / "Beta v. Gamma, 90 U.S. 40 (1875).txt").write_text(BETA, encoding="utf-8")
    memo = d / "memo.md"
    memo.write_text(MEMO, encoding="utf-8")

    def run(*extra):
        p = subprocess.run([sys.executable, str(SCRIPT), str(memo), "--sources", str(d / "cases"), "--workdir", str(d / "work"), *extra], capture_output=True, text=True)
        try:
            return p.returncode, json.loads(p.stdout)
        except ValueError:
            return p.returncode, {"raw": p.stdout + p.stderr}

    code, out = run()
    rows = {r["opening"]: r for r in out.get("rows", [])}
    row = lambda start: next((r for k, r in rows.items() if k.startswith(start)), {})

    print("which source, and which page")
    check(code == 0 and out.get("quotations") == 8, "eight quotations found; the Table of Authorities is not searched (%s)" % out.get("quotations"))
    r = row("taken in their ordinary")
    check(r.get("status") == "verbatim" and r.get("page") == 11 and r.get("pin") == "matches", "a footnoted quotation: found, page from the file's page breaks, pin matches")
    r = row("applies only where")
    check(r.get("status") == "verbatim" and r.get("page") == 12 and r.get("pin") == "differs",
      "an Id. note resolves to the case above it; a closing period the source lacks does not defeat the match; a wrong pin is reported (memo 13, found 12)")
    r = row("rewrites the statute")
    check(r.get("status") == "verbatim" and r.get("page") == 13 and r.get("pin") == "matches", "a short form (500 U.S. at 13) resolves to the full cite")
    r = row("is construed strictly")
    check(r.get("status") == "verbatim" and r.get("page") == 41 and r.get("pin") == "matches", "explicit page marks in a text source give the page")
    r = row("We hold that the rule")
    check(r.get("status") == "verbatim" and r.get("page") == 12 and r.get("citedTo") == "n.2", "a blockquote takes the footnote on the line that introduces it, and matches across a line break")

    print("what is not confirmed")
    r = row("lenity is dead")
    check(r.get("status") == "not_found" and [n["opening"][:14] for n in out["notFound"]] == ["lenity is dead"], "a quotation that is not in its source is reported as not found, and it is the only one")
    r = row("nothing can be known")
    check(r.get("status") == "no_source" and any("300 U.S. 5" in m for m in out["noSource"]), "a citation with no copy available is listed, not guessed at")
    r = row("The remedy is for Congress")
    check(r.get("status") == "found_elsewhere" and "90 U.S. 40" in (r.get("checkedAgainst") or "") and r.get("page") == 42,
          "a table cell with no citation is searched for in the memo's sources and reported with where it was found")
    check(sorted(p["opening"][:12] for p in out["pinDiffers"]) == ["We hold that", "applies only"], "pinDiffers lists exactly the two quotations on the wrongly pinned page")

    print("addendum")
    code, out = run("--append")
    text = memo.read_text(encoding="utf-8")
    at, prod = text.find("## Addendum: quotation check against the sources"), text.find("\n---\n\nProduction details")
    check(code == 0 and out.get("appended") and 0 < at < prod and text.endswith("Production details: test.\n"), "the addendum goes before the Production details block, which stays last")
    check("| NOT FOUND |" in text and "| Verbatim |" in text and text.count("\n| ") >= 10, "it tabulates every quotation with its result")
    body_before, body_after = MEMO[: MEMO.find("\n---\n\nProduction details")], text[:at]
    check(body_after.rstrip("\n") == body_before.rstrip("\n"), "nothing above it is changed")
    code, out = run("--append")
    check(code == 2 and text == memo.read_text(encoding="utf-8"), "a second --append is refused and leaves the memo alone")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
