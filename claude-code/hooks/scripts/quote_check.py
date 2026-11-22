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

One exception (added 2026-11-22): the returned result of this plugin's proofread
workflow (a Workflow call whose scriptPath is skills/proofread/proofread.workflow.js
in this plugin, with no inline script, and whose script file Claude did not write or
edit this session). The skill tells the session to save that result as the report,
so a saved report must not be blocked for repeating it. Its report quotes only the
draft's own words and proposed rewordings. The legal-research and cite-check
workflows are NOT trusted: their memos quote cases and articles, which is exactly
what this hook must check (see quote_common.TRUSTED_WORKFLOWS). The result is read from the
<task-notification> that carries the call's tool-use id; the notification cuts a
long result at about 8,000 characters, so the full result is then read from the
output file the notification names, or from the run record beside the transcript.

Files written this turn are checked as they are on disk when the hook runs (a
Write's text is used only if the file is gone), so a file fixed after a block is
re-checked as fixed. For a file only edited this turn, a quotation on disk is
checked if one of this turn's edits introduced it.

A quotation is text in straight or curly double quotes, or a Markdown
blockquote, of QUOTE_MIN_WORDS or more words. Quotation marks pair in order
within one paragraph, list item, heading or table cell, never across them.
Fenced code is ignored. Ellipses
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
    read_stdin, skill_active, strip_agent_blocks, subagent_transcripts, trusted_workflow_script,
)

QUOTE_MIN_WORDS = 5
SEGMENT_MIN_WORDS = 3
MAX_BLOCKS = 2
CHECKED_EXT = {".md", ".markdown", ".txt", ".html", ".htm"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}
MAX_FILE_BYTES = 20 * 1024 * 1024


# ---- The proofread workflow's result (added 2026-11-22) -------------------------------
# Only scripts in quote_common.TRUSTED_WORKFLOWS (proofread alone) are trusted; see there.
# A background Workflow's result reaches the session as a <task-notification> record:
#   <tool-use-id>ID</tool-use-id> <output-file>PATH</output-file> ... <result>JSON</result>
# The JSON is XML-escaped (&gt; &lt; &amp;) and, past about 8,000 characters, cut off with
# "... (truncated N chars, full result in PATH)". The output file is the runtime's JSON
# {"result": ...}; the run record <session>/workflows/<runId>.json also holds the result
# and the scriptPath.
_NOTICE_RE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S | re.I)
_JSON_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _tag(body, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), body, re.S)
    return m.group(1).strip() if m else ""


def _leaves(obj, out):
    """Every string value inside a JSON value."""
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _leaves(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _leaves(v, out)
    return out


def _read_json(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def plugin_workflow(inp, written) -> bool:
    """A Workflow call that runs a trusted script of this plugin (the proofread workflow),
    unchanged by Claude."""
    if not isinstance(inp, dict) or inp.get("script"):
        return False
    sp = str(inp.get("scriptPath") or "")
    if not sp:
        return False
    if not trusted_workflow_script(sp):
        return False
    real = os.path.realpath(sp)
    return os.path.normpath(sp) not in written and real not in {os.path.realpath(p) for p in written}


def workflow_result_texts(body, run_dir, run_id):
    """Strings in the result a <task-notification> body reports, or []."""
    raw = _tag(body, "result")
    try:
        return [html.unescape(s) for s in _leaves(json.loads(raw), [])]
    except ValueError:
        pass
    task_id = _tag(body, "task-id")
    out_file = _tag(body, "output-file")
    if out_file and task_id and os.path.basename(out_file) == task_id + ".output":
        d = _read_json(out_file)
        if isinstance(d, dict) and "result" in d:
            return _leaves(d["result"], [])
    if run_id and run_dir:
        d = _read_json(os.path.join(run_dir, "workflows", os.path.basename(run_id) + ".json"))
        if isinstance(d, dict) and "result" in d and (not task_id or d.get("taskId") == task_id) \
                and trusted_workflow_script(d.get("scriptPath")):
            return _leaves(d["result"], [])
    if not raw:
        return []
    # Last resort: the string literals in the part of the result the notice kept. The
    # last one is cut off, so it is dropped.
    raw = re.sub(r"\n\.\.\. \(truncated \d+ chars.*$", "", raw, flags=re.S)
    out = []
    for m in _JSON_STR_RE.finditer(raw):
        try:
            out.append(html.unescape(json.loads(m.group(0))))
        except ValueError:
            pass
    return out


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
    s = re.sub(r"\[\*{1,3}\d{1,4}\]", " ", s)   # a reporter's page marker ([*516]) is never text
    # a soft hyphen at a line end splits one word (re-flowed text leaves a space after
    # it); rejoin the halves and keep the join
    s = re.sub(r"(?<=%s)\u00ad\s+(?=%s)" % (_L, _L), JOIN, s)
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
        return text[i] in "-',." and (i + 1) in joins
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
        self.run_dir = transcript_path[: -len(".jsonl")] \
            if transcript_path and transcript_path.endswith(".jsonl") else ""
        self.written = set()           # paths Claude wrote or edited, any transcript
        self.corpus = []
        self.last_assistant = ""
        self.turn_files = []           # (path, text, only) checked for the final turn
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

    def _plugin_results(self, text, own_workflows):
        """Add the result of a trusted (proofread) workflow reported in a notice."""
        for m in _NOTICE_RE.finditer(text or ""):
            body = m.group(1)
            tid = _tag(body, "tool-use-id")
            if tid and tid in own_workflows:
                self.corpus.extend(workflow_result_texts(body, self.run_dir, own_workflows[tid]))

    def _collect(self, recs):
        tool_names, read_paths, saved = {}, {}, []
        own_workflows = {}             # tool-use id -> run id, for trusted (proofread) workflows
        for o in recs:
            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            typ = o.get("type")
            if typ == "user":
                self._plugin_results(content if isinstance(content, str) else block_text(
                    [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    if isinstance(content, list) else None), own_workflows)
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
                            if b.get("name") == "Workflow" and plugin_workflow(inp, self.written):
                                own_workflows[b.get("id")] = ""
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
                            if tid in own_workflows:
                                # the launch notice; remember the run id for the run record
                                tur = o.get("toolUseResult")
                                rid = tur.get("runId") if isinstance(tur, dict) else None
                                if not rid:
                                    m = re.search(r"Run ID:\s*(\S+)", block_text(b.get("content")))
                                    rid = m.group(1) if m else ""
                                own_workflows[tid] = str(rid or "")
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
        # path -> {"write": text of the last Write or None, "edits": [new_string, ...]}
        files = {}
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
                f = files.setdefault(p, {"write": None, "edits": []})
                if name == "Write":
                    f["write"], f["edits"] = str(inp.get("content") or ""), []
                elif name == "Edit":
                    f["edits"].append(str(inp.get("new_string") or ""))
                elif name == "MultiEdit":
                    for e in inp.get("edits") or []:
                        if isinstance(e, dict):
                            f["edits"].append(str(e.get("new_string") or ""))
        # Check each file as it is now (added 2026-11-22). The model may have fixed it
        # after a block, with Edit or with a shell command; re-checking the text of the
        # original Write call flagged quotations that were no longer in the file.
        for p, f in files.items():
            disk = read_text(p)
            if disk is None:                         # gone or unreadable: what the calls wrote
                if f["write"] is not None:
                    self.turn_files.append((p, f["write"], None))
                for e in f["edits"]:
                    self.turn_files.append((p, e, None))
            elif f["write"] is not None:             # written this turn: the whole file
                self.turn_files.append((p, disk, None))
            else:                                    # only edited: what this turn's edits added
                only = {norm(q) for e in f["edits"] for q, _ in extract_quotes(e)}
                if only:
                    self.turn_files.append((p, disk, only))


def read_text(path):
    """A file's current text, or None if it is missing, too large or unreadable."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", " ", text)


# ---- Where a quotation can run (added 2026-11-22) ----------------------------------------
# Quotation marks used to be paired by one pattern over the whole text that skipped pairs
# under ten characters, so after a short quotation ("the the") its closing mark opened a
# new "quotation" that ran to the next mark, across the end of a list item. Marks now pair
# in order (see _pairs), and only within one unit: a paragraph (lines up to a blank line), a list item
# with its continuation lines, a heading, a table cell, or a run of blockquote lines. A
# quotation wrapped over several lines of one paragraph is still one quotation.
_UNIT_START = re.compile(r"(?:[-*+]|\d{1,3}[.)])\s|#{1,6}\s")
_RULE = re.compile(r"([-*_])(?:\s*\1){2,}\s*$")


def _pairs(text: str, start: int, end: int):
    """(open, close) offsets of quotation-mark pairs in text[start:end], paired in order.
    A straight mark opens or closes by its neighbours, so a stray mark (an inch mark, the
    outer close of a nested quotation) does not open a phantom quotation. Same rule as
    the owner's quote-guard mod (2026-10-31 and 2026-11-10)."""
    open_at = None
    for m in re.finditer(r"[\"“”]", text[start:end]):
        i = start + m.start()
        ch = text[i]
        prev = text[i - 1] if i > start else ""
        nxt = text[i + 1] if i + 1 < end else ""
        can_open = ch == "“" or (ch == '"' and nxt and not nxt.isspace()
                                 and (not prev or prev.isspace() or prev in "([{—–-/*_'‘“>:|"))
        can_close = ch == "”" or (ch == '"' and prev and not prev.isspace()
                                  and not nxt.isalnum())
        if open_at is None:
            if can_open:
                open_at = i + 1
            continue
        if ch == "“" or not can_close:
            if can_open:                            # a new opener before any close
                open_at = i + 1
            continue
        yield open_at, i
        open_at = None


def _units(text: str):
    """(start, end) offsets of the units quotation marks may not cross."""
    out, cur, prev_bq, pos = [], None, None, 0
    for line in text.split("\n"):
        ls, le = pos, pos + len(line)
        pos = le + 1
        stripped = line.lstrip()
        bq = stripped.startswith(">")
        body = stripped
        while body.startswith(">"):
            body = body[1:].lstrip()
        if not body.strip() or _RULE.match(body):
            cur, prev_bq = None, None
            continue
        if body.startswith("|"):                    # table row: each cell on its own
            cur, prev_bq = None, None
            at = ls + (len(line) - len(body))
            for cell in re.finditer(r"(?:\\\||[^|])+", body):
                out.append([at + cell.start(), at + cell.end()])
            continue
        if cur is None or bq != prev_bq or _UNIT_START.match(body):
            cur = [ls, le]
            out.append(cur)
        else:
            cur[1] = le
        prev_bq = bq
        if re.match(r"#{1,6}\s", body):             # a heading is one line
            cur = None
    return out


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
    for start, end in _units(text):
        for q_start, q_end in _pairs(text, start, end):
            q = text[q_start:q_end]
            if len(q) < 10:
                continue
            line_start = text.rfind("\n", 0, q_start) + 1
            line_end = text.find("\n", q_end)
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


def unmatched_quotes(text, corpus, seen, only=None):
    """corpus = norm_source(...) of everything that counts as a source. only = if given,
    the normalized quotations to check (those this turn's edits introduced)."""
    corpus_n, joins = corpus
    out = []
    for q, line in extract_quotes(text):
        qn = norm(q)
        if words(qn) < QUOTE_MIN_WORDS or qn in seen or (only is not None and qn not in only):
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
    for path, text, only in sess.turn_files:
        problems += [(os.path.basename(path), q)
                     for q in unmatched_quotes(text, corpus_n, seen, only)]

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
