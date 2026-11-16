#!/usr/bin/env python3
"""Save a finished legal-research run's memo to a Markdown file without retyping it.

The workflow assembles the final memo itself (the draft plus applied edits plus the appendix
sections) and returns it in its result. The run's completion notification names an
<output-file> holding that result as JSON. This script copies the memo out of that file into the
destination, so the orchestrating session never has to emit the memo's text a second time: on a
session model whose use is metered, retyping a finished memo is the largest avoidable cost of
delivering it, and a retyped memo can drift from the one that was cite-checked.

    save_memo.py <task output file> <destination.md> [--header TEXT] [--footer TEXT]

--header TEXT  inserted directly under the memo's first "# " title line (the Topic/Date/By block).
               A "Label: value" line the memo already carries there under a label the header
               also gives (the draft sometimes writes its own "By:" line) is replaced, not
               duplicated; the summary lists each line replaced.
--footer TEXT  appended at the very end after a "---" rule (the Production details block)

It never overwrites: if the destination exists it stops with exit status 2. It prints a JSON
summary (path, size, exitState, counts, how Finalize ran, edits still to apply by hand) and
nothing of the memo itself. Exit status 1 means no memo could be found in the output file, in
which case fall back to writing the memo from the notification's inline result.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def find_result(data):
    """The workflow's return value: under "result" in the task output (as an object or as a JSON
    string), or the whole document when the file is the bare result."""
    seen = 0
    while isinstance(data, (dict, str)) and seen < 4:
        seen += 1
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                return None
            continue
        if isinstance(data.get("memo"), str):
            return data
        data = data.get("result")
    return None


LABEL = re.compile(r"^([A-Za-z][A-Za-z ]{0,30}):(\s|$)")


def with_header_footer(memo: str, header: str, footer: str):
    """Returns (text, the memo's own header lines that the header replaced)."""
    text = memo.rstrip("\n") + "\n"
    replaced = []
    if header.strip():
        lines = text.split("\n")
        at = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
        block = header.strip("\n").split("\n")
        if at is None:
            lines = block + [""] + lines
        else:
            rest = lines[at + 1:]
            while rest and not rest[0].strip():
                rest = rest[1:]
            # The memo's own "Label: value" lines directly under the title: one whose label the
            # header also gives is dropped (first live run, 2026-11-16: the draft wrote its own
            # "By:" line and the saved memo had two); the others stay, below the header.
            given = {m.group(1).strip().lower() for m in map(LABEL.match, block) if m}
            kept = []
            while rest and LABEL.match(rest[0]):
                line = rest.pop(0)
                (replaced if LABEL.match(line).group(1).strip().lower() in given else kept).append(line)
            while rest and not rest[0].strip():
                rest = rest[1:]
            lines = lines[: at + 1] + [""] + block + ([""] + kept if kept else []) + [""] + rest
        text = "\n".join(lines)
    if footer.strip():
        text = text.rstrip("\n") + "\n\n---\n\n" + footer.strip("\n") + "\n"
    return text, replaced


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("output_file", help="the <output-file> path from the workflow's completion notification")
    ap.add_argument("destination", help="the .md file to create (must not exist)")
    ap.add_argument("--header", default="", help="text to insert under the title line")
    ap.add_argument("--footer", default="", help="text to append after a --- rule")
    a = ap.parse_args(argv)

    src = Path(a.output_file).expanduser()
    dest = Path(a.destination).expanduser()
    try:
        raw = src.read_text(encoding="utf-8")
    except OSError as e:
        print(json.dumps({"saved": False, "error": "cannot read the output file: %s" % e}))
        return 1
    try:
        result = find_result(json.loads(raw))
    except ValueError:
        result = None
    if not result or not result["memo"].strip():
        print(json.dumps({"saved": False, "error": "no memo found in the output file; write it from the notification's inline result instead"}))
        return 1
    if dest.exists():
        print(json.dumps({"saved": False, "error": "destination already exists; choose another name: %s" % dest}))
        return 2

    text, replaced = with_header_footer(result["memo"], a.header, a.footer)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "x", encoding="utf-8") as fh:
        fh.write(text)

    fin = result.get("finalize") or {}
    unapplied = fin.get("unappliedEdits") or []
    print(json.dumps({
        "saved": True,
        "path": str(dest),
        "characters": len(text),
        "lines": text.count("\n"),
        "replacedHeaderLines": replaced,
        "exitState": result.get("exitState"),
        "degradation": result.get("degradation") or [],
        "counts": result.get("counts") or {},
        "finalizeModel": fin.get("model"),
        "callIn": fin.get("callIn"),
        "callInAuthorities": fin.get("callInAuthorities") or [],
        "unappliedEdits": unapplied,
        "next": ("apply the %d unapplied edit(s) to the saved file by hand, then remove the "
                 "'Changes not made automatically' note from its Limits section" % len(unapplied)) if unapplied else "",
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
