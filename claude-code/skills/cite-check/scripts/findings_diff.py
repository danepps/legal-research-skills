#!/usr/bin/env python3
"""Diff two cite-check runs of the same draft so a re-run after edits leads with what changed.

The workflow returns a structured `findings` block alongside the report; SKILL.md saves it as
`<draft> — Cite Check findings.json` next to the report. On the next run, this script compares
the previous file with the new one and prints a Markdown "Since the last report" block:
findings that are NEW, findings STILL OPEN (unchanged), and findings RESOLVED (no longer
reported). Dispositions carry forward by a stable key built from the finding's own content
(the draft quote, the source, the verdict; the find-string and problem for a form finding;
the cite for an existence or history item; the claim, source and verdict for a support
item), never from the footnote number, which renumbers
every time the author adds a note.

Usage:
    python3 findings_diff.py PREVIOUS.json CURRENT.json        # Markdown block on stdout
    python3 findings_diff.py PREVIOUS.json CURRENT.json --json # machine-readable

Both files are the workflow's `findings` object: {"snapshotSha256": ..., "date": ...,
"support": {"ran": bool, "scope": "pincited"|"all", "complete": bool, "read": [{"source", "claim"}, ...]},
"items": [{"kind": ..., "footnote": ..., "key": ..., "label": ...}, ...]}. A support finding
absent from the current run is "resolved" only if the current run actually read a unit
with the same source and claim (the `read` list); otherwise it is listed as "not
rechecked", never as resolved. `key` is computed
by the workflow (and recomputed here if absent) so the two sides agree. Stdlib only.
"""
import hashlib
import json
import re
import sys


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def key_of(item):
    """Stable identity of a finding, independent of footnote numbering."""
    if item.get("key"):
        return item["key"]
    kind = item.get("kind") or ""
    if kind == "quote":
        basis = f"{norm(item.get('quote'))[:160]}|{norm(item.get('source'))[:80]}|{item.get('verdict') or ''}"
    elif kind == "form":
        basis = f"{norm(item.get('find'))}|{norm(item.get('problem'))[:60]}"
    elif kind in ("existence", "history", "treatment", "secondary"):
        basis = f"{kind}|{norm(item.get('cite') or item.get('source'))}"
    elif kind == "supra":
        basis = f"supra|{norm(item.get('claims'))}|{item.get('supraNote')}"
    elif kind in ("support", "support-confirm"):
        # a support verdict is about (claim, source, verdict); the footnote number is not identity
        basis = f"{kind}|{norm(item.get('source'))[:80]}|{norm(item.get('claim'))[:160]}|{item.get('verdict') or ''}"
    else:
        basis = f"{kind}|{norm(item.get('label'))[:160]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def load(path):
    obj = json.load(open(path, encoding="utf-8"))
    items = obj.get("items") if isinstance(obj, dict) else obj
    out = {}
    for it in items or []:
        k = key_of(it)
        it = dict(it, key=k)
        out.setdefault(k, it)
    return obj if isinstance(obj, dict) else {}, out


SUPPORT_KINDS = ("support", "support-confirm")


def diff(prev, cur, prev_meta=None, cur_meta=None):
    """`*_meta` are the findings files' top-level objects; their `support` block
    ({ran, scope}) says whether the opt-in proposition-support pass ran. A support
    finding absent from a run whose pass did not run, or ran at a different scope,
    was NOT rechecked — it is never reported as resolved."""
    cs = (cur_meta or {}).get("support") or {}
    ps = (prev_meta or {}).get("support") or {}
    read = cs.get("read") if isinstance(cs.get("read"), list) else None
    # Per item when the current run exported what it read: the prior finding was rechecked
    # only if a unit with the same source and claim was actually read this run. Without that
    # list (older findings files), fall back to "pass ran, same scope, and complete".
    fallback = bool(cs.get("ran")) and (not ps or cs.get("scope") == ps.get("scope")) and cs.get("complete", True) is not False

    def rechecked(item):
        if read is None:
            return fallback
        src, claim = norm(item.get("source"))[:80], norm(item.get("claim"))[:160]
        return any(norm(r.get("source"))[:80] == src and norm(r.get("claim"))[:160] == claim for r in read)

    new = [cur[k] for k in cur if k not in prev]
    still = [cur[k] for k in cur if k in prev]
    absent = [prev[k] for k in prev if k not in cur]
    resolved = [i for i in absent if i.get("kind") not in SUPPORT_KINDS or rechecked(i)]
    not_rechecked = [i for i in absent if i.get("kind") in SUPPORT_KINDS and not rechecked(i)]
    moved = [(prev[k], cur[k]) for k in cur if k in prev and prev[k].get("footnote") != cur[k].get("footnote")]
    return {"new": new, "still_open": still, "resolved": resolved, "not_rechecked": not_rechecked, "renumbered": moved}


def line(it):
    fn = it.get("footnote")
    loc = f"n.{fn}" if fn not in (None, "") else (it.get("location") or "?")
    return f"- {loc} [{it.get('kind')}{(': ' + it['verdict']) if it.get('verdict') else ''}] {(it.get('label') or '')[:160]}"


def render(prev_meta, cur_meta, d):
    out = ["## Since the last report", ""]
    pd, cd = prev_meta.get("date") or "?", cur_meta.get("date") or "?"
    out.append(f"Previous report: {pd} (draft SHA-256 {str(prev_meta.get('snapshotSha256') or '?')[:12]}); "
               f"this report: {cd} (draft SHA-256 {str(cur_meta.get('snapshotSha256') or '?')[:12]}).")
    out.append(f"{len(d['new'])} new, {len(d['still_open'])} still open, {len(d['resolved'])} resolved. "
               "Identity is by content (quote, source, verdict, find-string, cite), not by footnote number, "
               f"so a renumbered draft does not reset the count{'; ' + str(len(d['renumbered'])) + ' finding(s) moved to a different footnote' if d['renumbered'] else ''}.")
    if d.get("not_rechecked"):
        out.append(f"{len(d['not_rechecked'])} proposition-support finding(s) from the last report were NOT rechecked "
                   "(the support pass did not run this time, or ran at a different scope); they are neither resolved nor still open.")
        out.append("")
    sections = [("New since last report", d["new"]), ("Still open", d["still_open"]), ("Resolved (no longer reported)", d["resolved"])]
    if d.get("not_rechecked"):
        sections.append(("Not rechecked (support pass off or scope changed)", d["not_rechecked"]))
    for title, items in sections:
        out.append(f"### {title}")
        out.extend([line(i) for i in items] or ["- none"])
        out.append("")
    return "\n".join(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    want_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]
    prev_meta, prev = load(args[0])
    cur_meta, cur = load(args[1])
    d = diff(prev, cur, prev_meta, cur_meta)
    if want_json:
        json.dump({"counts": {k: len(v) for k, v in d.items()}, **d}, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        sys.stdout.write(render(prev_meta, cur_meta, d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
