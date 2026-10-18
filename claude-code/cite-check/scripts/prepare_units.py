#!/usr/bin/env python3
"""Assemble quote-verification work units for the /cite-check pipeline.

Reads extract_cites.py's JSON and produces, for EVERY quotation (body and
footnote), a self-contained unit carrying the context a resolver needs to pair
the quote with the SPECIFIC source it hangs on — the practice run's five false
findings all traced to a resolver that lacked this context (DESIGN.md, lessons
4/4b/4c):

  * the quote's home footnote in FULL (never truncated);
  * for body quotes, the full surrounding body sentence (framing context);
  * the preceding non-empty footnotes (to walk a bare "Id." chain back to its
    antecedent — which may be a CASE two notes up);
  * the full text of every "supra note N" the home note redirects through;
  * a deterministic syllabus hint (a U.S. Reports pincite equal to the cite's
    first page is a syllabus page — CourtListener carries no syllabus text).

This is all deterministic (zero model tokens). The workflow's segment/resolve
agents consume these units; grouping quotes onto their unique source (so a
source cited 30 times is fetched once) happens after resolution.

Usage:
    python3 prepare_units.py <extract.json> [units.json]
    python3 prepare_units.py <extract.json> --ids START END   # print a slice
"""
import json
import re
import sys

ANTECEDENT_DEPTH = 3  # preceding non-empty notes carried for Id.-chain walking
US_PINCITE = re.compile(r"\b(\d+)\s+U\.\s?S\.\s+(\d+),\s*(\d+)")


def preceding_notes(notes, num, depth=ANTECEDENT_DEPTH):
    """Full text of up to `depth` non-empty footnotes immediately before `num`."""
    out = {}
    n = num - 1
    while n >= 1 and len(out) < depth:
        v = notes.get(str(n))
        if v and v.get("text", "").strip(". ").strip():
            out[str(n)] = v["text"]
        n -= 1
    return out


def supra_targets(notes, home, antecedents):
    """{N: full text of note N} for every supra note referenced by the home note
    OR by any antecedent note in the Id.-chain. The second case is essential:
    an "Id. at 522" whose antecedent reads "Nelson, supra note 19" only resolves
    if note 19's text is on hand (DESIGN.md lesson 4c-ii). Antecedent notes
    already carried are not duplicated here."""
    out = {}
    sources = [home] + [notes.get(k, {}) for k in antecedents]
    for src in sources:
        for s in src.get("supra", []) if src else []:
            n = str(s["note"])
            if n in antecedents:
                continue
            tgt = notes.get(n)
            if tgt:
                out[n] = tgt["text"]
    return out


def syllabus_hint(text):
    """True if the note carries a U.S. Reports cite whose pincite equals its
    first page (i.e. the syllabus page, e.g. '536 U.S. 181, 181')."""
    for m in US_PINCITE.finditer(text):
        if m.group(2) == m.group(3):
            return True
    return False


def build_units(data):
    notes = data["footnotes"]
    units = []
    uid = 0
    def add(q, loc):
        nonlocal uid
        num = q.get("footnote")
        home = notes.get(str(num), {}) if num else {}
        ante = preceding_notes(notes, num) if num else {}
        units.append({
            "id": uid,
            "loc": loc,
            "footnote": num,
            "quote": q["quote"],
            "sentence": q.get("sentence", "") if loc == "body" else "",
            "home_note": home.get("text", ""),
            "leading_id": home.get("leading_id", False),
            "antecedents": ante,
            "supra_targets": supra_targets(notes, home, ante) if home else {},
            "syllabus_hint": syllabus_hint(home.get("text", "")),
        })
        uid += 1

    for q in data.get("body_quotes", []):
        add(q, "body")
    for q in data.get("footnote_quotes", []):
        add(q, "footnote")
    return units


def main(argv):
    if not argv:
        print("usage: prepare_units.py <extract.json> [units.json | --ids A B]",
              file=sys.stderr)
        return 2
    data = json.load(open(argv[0], encoding="utf-8"))
    units = build_units(data)
    out = {
        "draft": data.get("source"),
        "unit_count": len(units),
        "case_cites": data.get("unique_case_cites", []),
        "supra_problems": data.get("supra_problem_candidates", []),
        "units": units,
    }

    if len(argv) >= 2 and argv[1] == "--ids":
        a = int(argv[2]) if len(argv) > 2 else 0
        b = int(argv[3]) if len(argv) > 3 else len(units)
        slice_ = [u for u in units if a <= u["id"] < b]
        print(json.dumps(slice_, ensure_ascii=False, indent=1))
        return 0

    if len(argv) >= 2 and argv[1] == "--pick":
        want = {int(x) for x in argv[2:]}
        slice_ = [u for u in units if u["id"] in want]
        print(json.dumps(slice_, ensure_ascii=False, indent=1))
        return 0

    if len(argv) >= 2 and argv[1] == "--footnotes":
        # a range "lo-hi" or an explicit list of footnote numbers -> unit ids
        want = set()
        for tok in argv[2:]:
            if "-" in tok:
                lo, hi = tok.split("-", 1)
                want |= set(range(int(lo), int(hi) + 1))
            else:
                want.add(int(tok))
        ids = [u["id"] for u in units if u.get("footnote") in want]
        print(json.dumps({"unit_ids": ids,
                          "footnotes": sorted(want)}, indent=1))
        return 0

    payload = json.dumps(out, ensure_ascii=False, indent=1)
    if len(argv) >= 2:
        with open(argv[1], "w", encoding="utf-8") as f:
            f.write(payload)
        print(json.dumps({"unit_count": len(units),
                          "case_cites": len(out["case_cites"]),
                          "supra_problems": len(out["supra_problems"])}, indent=2))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
