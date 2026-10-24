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
"items": [{"kind": ..., "footnote": ..., "key": ..., "label": ...}, ...]}. `key` is computed
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


def diff(prev, cur):
    new = [cur[k] for k in cur if k not in prev]
    still = [cur[k] for k in cur if k in prev]
    resolved = [prev[k] for k in prev if k not in cur]
    moved = [(prev[k], cur[k]) for k in cur if k in prev and prev[k].get("footnote") != cur[k].get("footnote")]
    return {"new": new, "still_open": still, "resolved": resolved, "renumbered": moved}


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
    out.append("")
    for title, items in (("New since last report", d["new"]), ("Still open", d["still_open"]), ("Resolved (no longer reported)", d["resolved"])):
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
    d = diff(prev, cur)
    if want_json:
        json.dump({"counts": {k: len(v) for k, v in d.items()}, **d}, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        sys.stdout.write(render(prev_meta, cur_meta, d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
