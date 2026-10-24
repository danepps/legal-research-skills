#!/usr/bin/env python3
"""Assemble PROPOSITION-SUPPORT work units for the /cite-check opt-in support pass.

Added 2026-10-24. The quote path verifies quotations; the existence path confirms that
unquoted sources exist. Nothing read an unquoted cite for whether it actually supports the
sentence it hangs on — the ledger called those instances "existence-only". This script
builds, for EVERY unquoted citation instance in the ledger, a self-contained unit carrying
what a reader needs to judge support, deterministically and at zero model tokens:

  * the proposition: the body sentence the footnote marker sits in (extract_cites.py's
    `anchor`), the preceding sentence, and — for a mid-sentence marker — the clause before
    the marker, which is usually what the note actually supports;
  * the footnote in FULL (never truncated), plus any prose clauses of the note itself,
    because the proposition is often stated in the footnote ("For the contrary view, see");
  * the instance's Bluebook signal (a "but see" cite claims CONTRARY authority; a "cf."
    cite claims analogy; a "see generally" cite claims background — the verdict is relative
    to the signal, never to bare "does the source say this");
  * the cite as printed, the source it resolves to (an Id./supra/short form walked to its
    full citation), its pincite / locator (own, or inherited down an Id. chain), the
    proposition parenthetical ("holding that ..."), and any separate-opinion note the
    draft itself gives ("Thomas, J., concurring"); a bare "Id." inherits its antecedent's
    page, a bare "Author, supra note N" does not (it is the whole work);
  * a SCOPE: `pincited` (a page/section/URL to read) or `whole-work` (a bare cite to an
    entire opinion, article or book — reading a whole work for support is expensive and
    artifact-prone, so the workflow reads these only when told to).

Excluded on purpose: quoted instances (the quote path covers them, with its own
fragment-framing judgment), nested "(quoting X)" cites (they support the quoted cite,
not the draft), unresolved cross-references (reported elsewhere as renumbering breaks),
prose and internal cross-references.

Usage:
    python3 prepare_support_units.py <extract.json> [support_units.json]
    python3 prepare_support_units.py <extract.json> --compact        # workflow args form
    python3 prepare_support_units.py <extract.json> --ids START END  # a slice, full detail
    python3 prepare_support_units.py <extract.json> --pick ID [ID …]
    python3 prepare_support_units.py <extract.json> --footnotes 45-80 12
    python3 prepare_support_units.py <extract.json> --note 12        # readable, one note
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from citation_ledger import XREF_KINDS, build_ledger  # noqa: E402

SKIP_KINDS = ("text", "internal")
# A locator the agent can open directly: a section is a locator, a URL is a page.
LOCATED_KINDS = ("statute", "internet")


def _walk_pincite(instances, x):
    """The page this instance points at. Its own "at N" wins. A bare "Id." means
    "same page as the antecedent", so an Id. without a page walks back through
    Id.s to the first non-Id. instance and takes THAT instance's page (which may
    itself be "" — "see generally Doe, supra note 3" then "Id." is the whole work
    twice). A bare "Author, supra note N" or a full cite with no page is the whole
    work: it never inherits the page cited in note N."""
    if x.get("pincite"):
        return x["pincite"], "own"
    if x["kind"] != "id":
        return "", ""
    seen, cur = set(), x
    while cur["kind"] == "id" and cur.get("xref_target") is not None and cur["i"] not in seen:
        seen.add(cur["i"])
        cur = instances[cur["xref_target"]]
        if cur.get("pincite"):
            return cur["pincite"], "inherited"
    return "", ""


def build_units(data):
    ledger = build_ledger(data)
    instances = ledger["instances"]
    notes = data["footnotes"]
    by_note = {}
    for x in instances:
        by_note.setdefault(x["note"], []).append(x)
    units = []
    for x in instances:
        if x["kind"] in SKIP_KINDS or x.get("nested") or x["quoted"]:
            continue
        if x["kind"] in XREF_KINDS:
            if x["xref_status"] != "resolved" or x.get("xref_final") is None:
                continue
            tgt = instances[x["xref_final"]]
            if tgt["kind"] in SKIP_KINDS or tgt["kind"] in XREF_KINDS:
                continue
        else:
            tgt = x
        pin, pin_basis = _walk_pincite(instances, x)
        parenthetical = x.get("parenthetical") or ""
        kind = tgt["kind"]
        scope = "pincited" if (pin or parenthetical or kind in LOCATED_KINDS) else "whole-work"
        note = notes.get(str(x["note"]), {})
        anchor = note.get("anchor") or {}
        units.append({
            "id": len(units),
            "i": x["i"],
            "note": x["note"],
            "kind": kind,
            "signal": x.get("signal", ""),
            "cite": x["text"],
            "source": tgt["text"],
            "key": tgt["key"],
            "case_cite": tgt.get("case_cite"),
            "resolved_from": None if tgt is x else "n.%d" % tgt["note"],
            "pincite": pin,
            "pincite_basis": pin_basis,
            "parenthetical": parenthetical,
            "opinion_note": x.get("opinion_note") or "",
            "scope": scope,
            "anchor": {
                "sentence": anchor.get("sentence", ""),
                "previous": anchor.get("previous", ""),
                "clause": anchor.get("clause", ""),
                "position": anchor.get("position", "unknown"),
                "paragraph_end": anchor.get("paragraph_end"),
                "block_quote": anchor.get("block_quote", False),
            },
            "note_text": note.get("text", ""),
            "note_prose": [y["text"] for y in by_note.get(x["note"], []) if y["kind"] == "text"],
            "siblings": sum(1 for y in by_note.get(x["note"], [])
                            if y["kind"] not in SKIP_KINDS and not y.get("nested")),
        })
    return units


def compact(units):
    return [{"id": u["id"], "i": u["i"], "n": u["note"], "k": u["kind"], "key": u["key"],
             "src": u["source"][:200], "pin": u["pincite"], "sig": u["signal"],
             "scope": u["scope"],
             # the claim, for report lines (full context is loaded by --pick at run time)
             "claim": (u["anchor"]["clause"] or u["anchor"]["sentence"])[:260]} for u in units]


def summary(units):
    by_kind, keys, keys_in = {}, set(), set()
    for u in units:
        by_kind[u["kind"]] = by_kind.get(u["kind"], 0) + 1
        keys.add(u["key"])
        if u["scope"] == "pincited":
            keys_in.add(u["key"])
    return {
        "unit_count": len(units),
        "in_scope_pincited": sum(1 for u in units if u["scope"] == "pincited"),
        "whole_work": sum(1 for u in units if u["scope"] == "whole-work"),
        "by_kind": by_kind,
        "unique_sources": len(keys),
        "unique_sources_pincited": len(keys_in),
        "units_without_anchor": sum(1 for u in units if not u["anchor"]["sentence"]),
        "unit_notes": [[u["id"], u["note"]] for u in units],
    }


def main(argv):
    if not argv:
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    data = json.load(open(argv[0], encoding="utf-8"))
    units = build_units(data)
    if len(argv) >= 2 and argv[1] == "--compact":
        print(json.dumps({"units": compact(units)}, ensure_ascii=False))
        return 0
    if len(argv) >= 2 and argv[1] == "--ids":
        a = int(argv[2]) if len(argv) > 2 else 0
        b = int(argv[3]) if len(argv) > 3 else len(units)
        print(json.dumps([u for u in units if a <= u["id"] < b], ensure_ascii=False, indent=1))
        return 0
    if len(argv) >= 2 and argv[1] == "--pick":
        want = {int(x) for x in argv[2:]}
        print(json.dumps([u for u in units if u["id"] in want], ensure_ascii=False, indent=1))
        return 0
    if len(argv) >= 2 and argv[1] == "--footnotes":
        want = set()
        for tok in argv[2:]:
            if "-" in tok:
                lo, hi = tok.split("-", 1)
                want |= set(range(int(lo), int(hi) + 1))
            else:
                want.add(int(tok))
        ids = [u["id"] for u in units if u["note"] in want]
        print(json.dumps({"unit_ids": ids, "footnotes": sorted(want)}, indent=1))
        return 0
    if len(argv) >= 2 and argv[1] == "--note":
        n = int(argv[2])
        for u in units:
            if u["note"] == n:
                print("[%d] %-8s %-12s %s%s  -> %s%s" % (
                    u["id"], u["kind"], u["signal"] or "(direct)", u["cite"][:100],
                    "" if u["resolved_from"] is None else " [via %s]" % u["resolved_from"],
                    ("at " + u["pincite"]) if u["pincite"] else "(whole work)",
                    "  ‖ " + (u["anchor"]["clause"] or u["anchor"]["sentence"])[:120]))
        return 0
    payload = json.dumps({"draft": data.get("source"), "unit_count": len(units),
                          "units": units}, ensure_ascii=False, indent=1)
    if len(argv) >= 2:
        with open(argv[1], "w", encoding="utf-8") as f:
            f.write(payload)
        print(json.dumps(summary(units), indent=2))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
