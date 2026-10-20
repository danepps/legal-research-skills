#!/usr/bin/env python3
"""Stop hook: while a legal-research skill is in use, every quotation in the final
reply, and in any Markdown/text file written during the final turn, must exist
verbatim in raw tool output from this session.

Sources (the corpus): tool results in the session transcript and in every
subagent transcript stored beside it (Agent and Workflow runs), the user's own
messages, and any "Full output saved to:" files that Bash results point at.
Not sources: WebFetch and WebSearch results (model summaries), the report an
Agent/Workflow run hands back (another model's prose, whether it arrives as the
tool result, as a <task-notification>, or as a relayed hand-back message), the
prompt the parent wrote to a subagent, the acknowledgements of Write/Edit calls,
and a Read of a file Claude itself wrote or edited this session (otherwise a
memo could vouch for itself). Text a subagent fetched counts because its raw
tool results are read from the subagent's own transcript.

A quotation is text in straight or curly double quotes, or a Markdown
blockquote, of QUOTE_MIN_WORDS or more words. Fenced code is ignored. Ellipses
and bracketed alterations split a quotation into segments; each segment of
SEGMENT_MIN_WORDS or more words must match. A quotation whose line carries
"[unverified]" is skipped, so the model can flag an honest recollection without
pretending it was checked.

Gate: nothing happens unless one of the plugin's skills was invoked this session
(see quote_common.skill_active). Off switch: LEGAL_RESEARCH_QUOTE_CHECK=off. The
hook also stands down when Dan's quote-guard mod is loaded, which does the same
check on every reply.

Loop guard: on a stop that is already a retry after this hook's block, the hook
allows the reply after MAX_BLOCKS consecutive blocks in the same session.
"""
import html
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quote_common import (  # noqa: E402
    EXCLUDED_RESULT_TOOLS, block_text, disabled_reason, harness_record, iter_records,
    read_stdin, skill_active, strip_agent_blocks, subagent_transcripts,
)

QUOTE_MIN_WORDS = 5
SEGMENT_MIN_WORDS = 3
MAX_BLOCKS = 2
CHECKED_EXT = {".md", ".markdown", ".txt", ".html", ".htm"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}


def norm(s: str) -> str:
    s = html.unescape(s)
    s = s.replace("­", "").replace("​", "").replace("﻿", "")
    s = re.sub(r"[‘’‚‛′]", "'", s)
    s = re.sub(r"[“”„‟″]", '"', s)
    s = re.sub(r"[‐-―−]", "-", s)
    s = s.replace(" ", " ")
    s = re.sub(r"(?m)^\s*\d+\t", "", s)          # Read tool line numbers
    s = re.sub(r"(?m)^\s*\d+→", "", s)      # cat -n style arrows in Edit echoes
    s = re.sub(r"<[^>\n]{1,200}>", " ", s)        # HTML / XML tags in raw fetches
    s = s.lower()
    s = re.sub(r"[^a-z0-9§'\"$%&/.,;:!?()\[\]-]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def words(s: str) -> int:
    return len(re.findall(r"[a-z0-9]+", s))


def is_prompt(o) -> bool:
    """A user record that is the person's own message: not a tool result, and not a
    notice the harness or a subagent put in the transcript."""
    msg = o.get("message")
    if o.get("type") != "user" or not isinstance(msg, dict) or harness_record(o):
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(strip_agent_blocks(content).strip())
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return False
        return bool(strip_agent_blocks(block_text(content)).strip())
    return False


class Session:
    """Everything the check needs, pulled from the main and subagent transcripts."""

    def __init__(self, transcript_path):
        self.main = list(iter_records(transcript_path)) if transcript_path else []
        self.subs = [list(iter_records(p)) for p in subagent_transcripts(transcript_path)]
        self.written = set()           # paths Claude wrote or edited, any transcript
        self.corpus = []
        self.last_assistant = ""
        self.turn_files = []           # (path, text) written in the final turn
        self._scan_writes()
        for recs in [self.main] + self.subs:
            self._collect(recs)
        self._final_turn()

    def _scan_writes(self):
        for recs in [self.main] + self.subs:
            for o in recs:
                msg = o.get("message")
                if o.get("type") != "assistant" or not isinstance(msg, dict):
                    continue
                for b in msg.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" \
                            and b.get("name") in WRITE_TOOLS:
                        inp = b.get("input") or {}
                        p = inp.get("file_path") if isinstance(inp, dict) else None
                        if p:
                            self.written.add(os.path.normpath(str(p)))

    def _collect(self, recs):
        tool_names, read_paths, saved = {}, {}, []
        for o in recs:
            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            typ = o.get("type")
            if typ == "assistant":
                texts = []
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_use":
                            tool_names[b.get("id")] = b.get("name", "")
                            inp = b.get("input") or {}
                            if b.get("name") == "Read" and isinstance(inp, dict) and inp.get("file_path"):
                                read_paths[b.get("id")] = os.path.normpath(str(inp["file_path"]))
                        elif b.get("type") == "text":
                            texts.append(b.get("text", ""))
                elif isinstance(content, str):
                    texts.append(content)
                if texts and recs is self.main:
                    self.last_assistant = "\n".join(texts)
            elif typ == "user":
                # Plain text in a user record is the person's own words only in the
                # main transcript and only when the harness did not write it; in a
                # subagent transcript it is the parent model's prompt. Tool results
                # count in both.
                own = recs is self.main and not harness_record(o)
                if isinstance(content, str):
                    if own:
                        self.corpus.append(strip_agent_blocks(content))
                elif isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text":
                            if own:
                                self.corpus.append(strip_agent_blocks(b.get("text", "")))
                        elif b.get("type") == "tool_result":
                            tid = b.get("tool_use_id")
                            name = tool_names.get(tid, "")
                            if name in EXCLUDED_RESULT_TOOLS:
                                continue
                            if name == "Read" and read_paths.get(tid) in self.written:
                                continue
                            txt = block_text(b.get("content"))
                            self.corpus.append(txt)
                            for m in re.finditer(r"Full output saved to:\s*(\S+)", txt):
                                saved.append(m.group(1))
        for p in saved:
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    self.corpus.append(fh.read())
            except OSError:
                pass

    def _final_turn(self):
        start = 0
        for i, o in enumerate(self.main):
            if is_prompt(o):
                start = i
        for o in self.main[start:]:
            msg = o.get("message")
            if o.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            for b in msg.get("content") or []:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp = b.get("input") or {}
                if not isinstance(inp, dict):
                    continue
                p = str(inp.get("file_path") or "")
                if os.path.splitext(p)[1].lower() not in CHECKED_EXT:
                    continue
                name = b.get("name")
                if name == "Write":
                    self.turn_files.append((p, str(inp.get("content") or "")))
                elif name == "Edit":
                    self.turn_files.append((p, str(inp.get("new_string") or "")))
                elif name == "MultiEdit":
                    for e in inp.get("edits") or []:
                        if isinstance(e, dict):
                            self.turn_files.append((p, str(e.get("new_string") or "")))


def strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", " ", text)


def extract_quotes(text: str):
    """Yield (quote, line) pairs from quotation marks and blockquotes."""
    text = strip_code(text)
    found = []
    block, block_line = [], ""
    for line in text.split("\n"):
        if line.lstrip().startswith(">"):
            block.append(line.lstrip()[1:].strip())
            block_line = block_line or line
        else:
            if block:
                found.append((" ".join(block), block_line))
                block, block_line = [], ""
    if block:
        found.append((" ".join(block), block_line))
    for m in re.finditer(r"[\"“]([^\"“”]{10,}?)[\"”]", text):
        q = m.group(1)
        if "\n\n" in q:
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start: line_end if line_end != -1 else len(text)]
        found.append((q, line))
    return found


def trim(s: str) -> str:
    return re.sub(r"^[^a-z0-9§$]+|[^a-z0-9%)]+$", "", s)


def segments(q: str):
    parts = re.split(r"\.\s?\.\s?\.|…|\[[^\]]*\]", q)
    return [p for p in (trim(norm(p)) for p in parts) if words(p) >= SEGMENT_MIN_WORDS]


def unmatched_quotes(text, corpus_n, seen):
    out = []
    for q, line in extract_quotes(text):
        qn = norm(q)
        if words(qn) < QUOTE_MIN_WORDS or qn in seen:
            continue
        seen.add(qn)
        if "[unverified]" in line.lower():
            continue
        segs = segments(q) or [trim(qn)]
        if all(s in corpus_n for s in segs):
            continue
        out.append(q.strip())
    return out


def state_path(session_id: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"legal-research-quote-check-{session_id or 'na'}.count")


def main():
    if disabled_reason():
        return
    data = read_stdin(sys.stdin)
    transcript = data.get("transcript_path", "")
    session_id = data.get("session_id", "")
    retry = bool(data.get("stop_hook_active"))
    if not transcript:
        return
    sess = Session(transcript)
    if not skill_active(sess.main):
        return
    last = data.get("last_assistant_message") or sess.last_assistant or ""
    if not last.strip() and not sess.turn_files:
        return
    corpus_n = norm("\n".join(sess.corpus))

    seen = set()
    problems = []                                   # (where, quote)
    problems += [("reply", q) for q in unmatched_quotes(last, corpus_n, seen)]
    for path, text in sess.turn_files:
        problems += [(os.path.basename(path), q) for q in unmatched_quotes(text, corpus_n, seen)]

    sp = state_path(session_id)
    if not problems:
        try:
            os.remove(sp)
        except OSError:
            pass
        return

    count = 0
    if retry:
        try:
            count = int(open(sp).read().strip() or 0)
        except Exception:
            count = 0
    if retry and count >= MAX_BLOCKS:
        sys.stderr.write(
            "legal-research quotation check: still unverified after %d retries; allowing the "
            "reply. Unverified: %s\n" % (count, " | ".join(q for _, q in problems[:5]))
        )
        try:
            os.remove(sp)
        except OSError:
            pass
        return
    try:
        open(sp, "w").write(str(count + 1))
    except OSError:
        pass

    ell = "…"
    items = "\n".join(
        "%d. [%s] “%s%s”" % (i + 1, where, q[:220], ell if len(q) > 220 else "")
        for i, (where, q) in enumerate(problems[:8])
    )
    more = f"\n(and {len(problems) - 8} more)" if len(problems) > 8 else ""
    reason = (
        "legal-research quotation check: your reply, or a file you wrote this turn, presents "
        "text in quotation marks or a blockquote that no raw tool output in this session "
        "contains verbatim. WebFetch and WebSearch results are model summaries and do not "
        "count as sources; neither does a file you wrote yourself.\n" + items + more +
        "\nFor each one, either (a) fetch the raw text (fetch_page.py or curl into a local "
        "file and grep for the phrase; CourtListener read_document/search_document for "
        "opinions; Read for the user's own files) and reproduce the exact wording, or (b) "
        "remove the quotation marks and say you are paraphrasing. If you genuinely cannot "
        "check it, keep the quotation marks only with the tag [unverified] on the same line. "
        "Fix the written file too, then resend the reply."
    )
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the session on a hook bug
        sys.stderr.write(f"legal-research quote_check error: {e}\n")
