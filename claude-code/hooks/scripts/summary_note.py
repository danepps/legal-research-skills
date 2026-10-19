#!/usr/bin/env python3
"""PostToolUse hook for WebFetch and WebSearch, active only while a legal-research
skill is in use this session.

Both tools return prose written by a small model, not the page. Anything that
prose puts in quotation marks may be a paraphrase. This hook appends a note to
the tool result so the model never treats such text as verbatim.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quote_common import disabled_reason, iter_records, read_stdin, skill_active  # noqa: E402


def main():
    if disabled_reason():
        return
    data = read_stdin(sys.stdin)
    transcript = data.get("transcript_path", "")
    if not transcript or not skill_active(iter_records(transcript)):
        return
    tool = data.get("tool_name", "WebFetch")
    note = (
        f"legal-research quotation check: this {tool} result is a summary written by a "
        "small model, not the source. Nothing in it is verbatim, including text it put in "
        "quotation marks. Before quoting the source, get its raw text and confirm the exact "
        "string: fetch the page to a local file (fetch_page.py in the legal-research skill, "
        "or curl) and grep for the phrase; for opinions use CourtListener read_document or "
        "search_document; for local files use Read. The plugin's Stop hook blocks a reply or "
        "written report that quotes five or more words with no verbatim match in raw tool "
        "output this session."
    )
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note},
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the session on a hook bug
        sys.stderr.write(f"legal-research summary_note error: {e}\n")
