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

A quotation must cover whole source words and numbers: one that begins or ends
inside a source word or number is not in the source ("eligible" against
"ineligible", "$400" against "$400,000"). See the token-boundary section below.

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
import unicodedata

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


# ---- Token boundaries (added 2026-11-14) --------------------------------------
# The check used to be a bare substring test, so a quotation that began or ended inside a
# source word or number passed: "eligible for copyright protection" against a source that
# says "ineligible for copyright protection", "pay more than $400," against "$400,000".
# Now a quotation segment must start and end on a source-token boundary. A cut is INSIDE a
# token when it falls between two letters, two digits, or a digit and a following letter
# ("10b"), or at one of the joins that marked() records while the line breaks and case
# that identify them are still there:
#   - a single hyphen between two word halves, closed up ("non-binding" is not "binding")
#     or broken across a line ("in-\neligible", soft hyphens included); dashes and
#     "pre- and post-" are boundaries
#   - an apostrophe with a letter on each side ("can't" is not "can")
#   - a thousands comma (a comma and exactly three digits) or a decimal point in a number
# Allowed, because a flattened footnote call looks like this: a word followed directly by
# digits ("protection12"), and a number, a period, then one to three digits before a new
# sentence ("in 1871.45 The Court").
JOIN = "\x01"        # marks a join inside a token; removed again, its offsets kept
LETTER = "\x02"      # stands for any letter outside a-z, so "naïveté" stays one word
_L = r"[^\W\d_]"     # any letter
_JOINS = [
    (re.compile(r"(?<=%s)-(?=%s)" % (_L, _L)), "-" + JOIN),
    (re.compile(r"(?<=%s)-[ \t]*\n\s*(?=%s)" % (_L, _L)), "-" + JOIN + "\n"),
    (re.compile(r"(?<=%s)'(?=%s)" % (_L, _L)), "'" + JOIN),
    (re.compile(r"(?<=\d),(?=\d{3}(?!\d))"), "," + JOIN),
    (re.compile(r"(?<=\d)\.(?=\d)(?!\d{1,3}\s+['\"(\[]?[A-Z])"), "." + JOIN),
]


def marked(s: str) -> str:
    """Normalized text with a JOIN after every hyphen, apostrophe, comma or period that
    sits inside one source token."""
    s = html.unescape(s)
    s = s.replace(JOIN, "").replace(LETTER, "")
    # a soft hyphen at a line end splits one word; the space it leaves carries the join
    s = re.sub(r"(?<=%s)\u00ad[ \t]*\n\s*(?=%s)" % (_L, _L), JOIN + "\n", s)
    s = s.replace("­", "").replace("​", "").replace("﻿", "")
    if not s.isascii():
        s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[‘’‚‛′]", "'", s)
    s = re.sub(r"[“”„‟″]", '"', s)
    s = re.sub(r"[‐‑]", "-", s)         # true hyphens now; dashes after the joins
    s = s.replace(" ", " ")
    s = re.sub(r"(?m)^\s*\d+\t", "", s)          # Read tool line numbers
    s = re.sub(r"(?m)^\s*\d+→", "", s)      # cat -n style arrows in Edit echoes
    s = re.sub(r"<[^>\n]{1,200}>", " ", s)        # HTML / XML tags in raw fetches
    for pattern, repl in _JOINS:
        s = pattern.sub(repl, s)
    s = re.sub(r"[‒-―−]", "-", s)   # figure, en, em dashes, bar, minus
    s = s.lower()
    s = re.sub(r"[^\W\d_a-z]|[̀-ͯ]", LETTER, s)
    s = re.sub(r"[^a-z0-9§'\"$%&/.,;:!?()\[\]\x01\x02-]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def norm(s: str) -> str:
    return marked(s).replace(JOIN, "")


def norm_source(s: str):
    """(normalized text, offsets that sit just after a join inside a token)."""
    pieces = marked(s).split(JOIN)
    joins, at = set(), 0
    for piece in pieces[:-1]:
        at += len(piece)
        joins.add(at)
    return "".join(pieces), joins


def _kind(c: str) -> str:
    return "L" if ("a" <= c <= "z" or c == LETTER) else "D" if "0" <= c <= "9" else ""


def cuts_token(text: str, joins, i: int, at_end: bool) -> bool:
    """Whether the cut before text[i] falls inside a source word or number."""
    if i <= 0 or i >= len(text):
        return False
    left, right = _kind(text[i - 1]), _kind(text[i])
    if left and right:
        return not (at_end and left == "L" and right == "D")
    if at_end:
        # the second test is a soft hyphen at a line end: only its space is left
        return (text[i] in "-',." and (i + 1) in joins) or (text[i] == " " and i in joins)
    # the space after a hyphen at a line end carries the join ("in- eligible")
    return i in joins or (text[i - 1] == " " and (i - 1) in joins)


def occurs(seg: str, text: str, joins, free=(False, False)) -> bool:
    """seg is in text, starting and ending on token boundaries. free = edges that a
    bracketed alteration occupies ("[T]he" for "the"), which have no boundary to test."""
    at = text.find(seg)
    while at >= 0:
        if not ((not free[0] and cuts_token(text, joins, at, False)) or
                (not free[1] and cuts_token(text, joins, at + len(seg), True))):
            return True
        at = text.find(seg, at + 1)
    return False


def words(s: str) -> int:
    return len(re.findall(r"[a-z0-9\x02]+", s))


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
    return re.sub(r"^[^a-z0-9§$\x02]+|[^a-z0-9%)\x02]+$", "", s)


def segments(q: str):
    """Split a quotation at ellipses and bracketed alterations. Each item is
    (segment, (starts at a bracket, ends at a bracket))."""
    parts = re.split(r"(\.\s?\.\s?\.|…|\[[^\]]*\])", q)
    out = []
    for n in range(0, len(parts), 2):
        seg = trim(norm(parts[n]))
        if words(seg) >= SEGMENT_MIN_WORDS:
            out.append((seg, (n > 0 and parts[n - 1].startswith("["),
                              n + 1 < len(parts) and parts[n + 1].startswith("["))))
    return out


def unmatched_quotes(text, corpus, seen):
    """corpus = norm_source(...) of everything that counts as a source."""
    corpus_n, joins = corpus
    out = []
    for q, line in extract_quotes(text):
        qn = norm(q)
        if words(qn) < QUOTE_MIN_WORDS or qn in seen:
            continue
        seen.add(qn)
        if "[unverified]" in line.lower():
            continue
        segs = segments(q) or [(trim(qn), (False, False))]
        if all(occurs(s, corpus_n, joins, free) for s, free in segs):
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
    corpus_n = norm_source("\n".join(sess.corpus))

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
