"""Shared helpers for the legal-research plugin's quotation hooks.

Both hook scripts run as `python3 -I <script>` and add their own directory to
sys.path before importing this module, so no package install is needed.
"""
import glob
import json
import os
import re

# Skill folders under claude-code/skills/. The hooks act only in a session where
# one of these has been invoked (Skill tool, slash command, or its workflow file).
PLUGIN_SKILLS = {
    "legal-research", "cite-check", "find-cite", "proofread", "build-library", "case-prep",
}

# Tool results that never count as a source: model-written summaries (a WebFetch
# digest, or the report an Agent/Task/Workflow run or a SendMessage reply hands
# back, which is another model's prose, not the text it fetched), and the
# acknowledgements of Claude's own writes (an Edit result echoes the edited text).
# What a subagent actually fetched is read from its own transcript instead.
EXCLUDED_RESULT_TOOLS = {
    "WebFetch", "WebSearch", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Agent", "Task", "Workflow", "SendMessage", "ReadNotifications", "SubagentHandback",
}

# A background agent's completion notice (a Workflow's result rides inside it) and a
# subagent's hand-back relayed as a peer message both arrive as user-typed records.
_AGENT_BLOCK_RE = re.compile(
    r"<task-notification>.*?</task-notification>|<agent-message\b[^>]*>.*?</agent-message>",
    re.S | re.I,
)

ENV_SWITCH = "LEGAL_RESEARCH_QUOTE_CHECK"


def disabled_reason():
    """Why the hook should stand down, or None."""
    v = os.environ.get(ENV_SWITCH, "").strip().lower()
    if v in {"off", "0", "false", "no"}:
        return f"{ENV_SWITCH}={v}"
    # Dan's personal quote-guard mod performs the same check on every reply, in every
    # session; running both would block the same reply twice with the same list.
    if "quote-guard" in os.environ.get("CLAUDE_CODE_PLUGIN_DIRS", ""):
        return "quote-guard plugin loaded"
    return None


def read_stdin(stream):
    try:
        raw = stream.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def iter_records(path):
    """Yield parsed JSONL records; skip anything unparsable."""
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if isinstance(o, dict):
                yield o


def subagent_transcripts(transcript_path):
    """Transcripts of Agent and Workflow subagents, stored beside the session file:
    <session>/subagents/agent-*.jsonl and <session>/subagents/workflows/<run>/agent-*.jsonl."""
    if not transcript_path or not transcript_path.endswith(".jsonl"):
        return []
    base = transcript_path[: -len(".jsonl")]
    pattern = os.path.join(base, "subagents", "**", "*.jsonl")
    return sorted(p for p in glob.glob(pattern, recursive=True) if os.path.isfile(p))


def harness_record(o):
    """True for a user-typed record that the harness or another model wrote rather than
    the person: a subagent's hand-back or completion notice, hook feedback, a skill's
    injected context. The person's own prompts carry promptSource typed/queued and
    origin.kind human (or, in older transcripts, no such fields at all)."""
    if o.get("isMeta"):
        return True
    if o.get("promptSource") == "system":
        return True
    origin = o.get("origin")
    return isinstance(origin, dict) and origin.get("kind") in {"task-notification", "peer"}


def strip_agent_blocks(text):
    """Remove agent notices from a user record's text, for transcripts whose records
    carry no origin metadata."""
    return _AGENT_BLOCK_RE.sub(" ", text or "")


def block_text(content):
    """Flatten a message content field to text."""
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                t = b.get("type")
                if t == "text":
                    out.append(b.get("text", ""))
                elif t == "tool_result":
                    out.append(block_text(b.get("content")))
            elif isinstance(b, str):
                out.append(b)
    return "\n".join(out)


def _skill_name(raw):
    """'legal-research:cite-check' -> 'cite-check'; '/find-cite' -> 'find-cite'."""
    s = str(raw or "").strip().lstrip("/")
    return s.rsplit(":", 1)[-1].strip()


_CMD_RE = re.compile(r"<command-name>\s*/?(?:[\w.-]+:)?([\w-]+)\s*</command-name>", re.I)


def skill_active(records):
    """True if one of this plugin's skills was invoked anywhere in the records."""
    for o in records:
        msg = o.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if o.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name = b.get("name", "")
                inp = b.get("input") or {}
                if not isinstance(inp, dict):
                    continue
                if name == "Skill" and _skill_name(inp.get("skill")) in PLUGIN_SKILLS:
                    return True
                if name == "Workflow":
                    sp = str(inp.get("scriptPath") or "")
                    if any(f"/skills/{s}/" in sp or f"\\skills\\{s}\\" in sp for s in PLUGIN_SKILLS):
                        return True
        elif o.get("type") == "user":
            txt = content if isinstance(content, str) else block_text(content)
            for m in _CMD_RE.finditer(txt):
                if m.group(1) in PLUGIN_SKILLS:
                    return True
    return False
