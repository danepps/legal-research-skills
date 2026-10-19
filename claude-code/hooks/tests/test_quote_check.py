#!/usr/bin/env python3
"""Self-test for the plugin's quotation hooks. Run: python3 tests/test_quote_check.py

Builds throwaway session transcripts (main file plus optional subagent files in the
layout Claude Code uses), runs the hook scripts as subprocesses the way Claude Code
does, and checks the decision. No network, no credentials.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
STOP = os.path.join(SCRIPTS, "quote_check.py")
NOTE = os.path.join(SCRIPTS, "summary_note.py")

# The developer's own machine loads a personal quote-guard mod through this variable,
# which makes the plugin hook stand down; tests must run with a clean environment.
CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in {"CLAUDE_CODE_PLUGIN_DIRS", "LEGAL_RESEARCH_QUOTE_CHECK"}}

SKILL_ON = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "sk1", "name": "Skill", "input": {"skill": "cite-check"}}]}}]


def write_jsonl(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def run(entries, last, retry=False, session="t", skill=True, subagents=None, env=None,
        script=STOP, extra_input=None):
    """subagents: {relative path under <session>/subagents/: entries}"""
    tmp = tempfile.mkdtemp()
    main = os.path.join(tmp, "sess.jsonl")
    write_jsonl(main, (SKILL_ON if skill else []) + entries)
    for rel, sub in (subagents or {}).items():
        write_jsonl(os.path.join(tmp, "sess", "subagents", rel), sub)
    inp = {"transcript_path": main, "session_id": session,
           "stop_hook_active": retry, "last_assistant_message": last}
    inp.update(extra_input or {})
    full_env = dict(CLEAN_ENV)
    full_env.update(env or {})
    p = subprocess.run([sys.executable, "-I", script], input=json.dumps(inp),
                       capture_output=True, text=True, env=full_env)
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {}, p.stderr
    except json.JSONDecodeError:
        return {"raw": p.stdout}, p.stderr


def tool_pair(name, result, tid="t1", inp=None):
    return [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tid, "name": name, "input": inp or {}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tid, "content": result}]}},
    ]


def prompt(text):
    return [{"type": "user", "message": {"content": text}}]


def write_call(path, content, tid="w1"):
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Write",
         "input": {"file_path": path, "content": content}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tid, "content": f"File created successfully at: {path}"}]}}]


STATUTE = ("In the case of any Taxpayer Advocate Directive issued by the National Taxpayer "
           "Advocate pursuant to a delegation of authority from the Commissioner of Internal Revenue")
BAD = 'He said "this quotation is not in the corpus anywhere at all".'

fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails += 1


# ---- behaviour carried over from quote-guard ----------------------------------------
out, _ = run(tool_pair("Bash", STATUTE), 'The statute says "pursuant to a delegation of authority from the Commissioner of Internal Revenue."')
check("verbatim quote from Bash output allowed", out == {})

out, _ = run(tool_pair("Bash", STATUTE), 'The statute covers a directive "issued under a delegation of authority from the Commissioner."')
check("paraphrase in quotes blocked", out.get("decision") == "block")

out, _ = run(tool_pair("WebFetch", STATUTE), 'It reads "pursuant to a delegation of authority from the Commissioner of Internal Revenue."')
check("WebFetch-only source blocked", out.get("decision") == "block")

out, _ = run(tool_pair("Read", "     1\t" + STATUTE.replace("Directive issued", "Directive\n     2\tissued"),
                       inp={"file_path": "/x/draft.txt"}),
             "> In the case of any Taxpayer Advocate Directive issued by the National Taxpayer Advocate pursuant to a delegation of authority from the Commissioner of Internal Revenue")
check("blockquote matched across Read line numbers", out == {})

out, _ = run(tool_pair("Bash", STATUTE), '"[I]n the case of any Taxpayer Advocate Directive . . . pursuant to a delegation of authority from the Commissioner"')
check("ellipsis and bracket segments matched", out == {})

out, _ = run(tool_pair("Bash", "nothing relevant"), 'Levinson calls these "votes" and "rights" strategies.')
check("short phrases ignored", out == {})

out, _ = run(prompt("please look at: Championship is also not useful only to the design of governmental institutions"),
             'You wrote "Championship is also not useful only to the design of governmental institutions."')
check("user's own words allowed", out == {})

out, _ = run(tool_pair("Bash", "x"), 'Bezos said "the customer is the most important person in the room" [unverified].')
check("[unverified] tag honored", out == {})

out, _ = run(tool_pair("Bash", "x"), 'Run this:\n```\ngrep "some long string that is not in the corpus at all"\n```')
check("fenced code ignored", out == {})

sid = "loop-test"
run(tool_pair("Bash", "x"), BAD, session=sid)
run(tool_pair("Bash", "x"), BAD, retry=True, session=sid)
out, err = run(tool_pair("Bash", "x"), BAD, retry=True, session=sid)
check("loop guard releases after repeated blocks", out == {} and "allowing" in err)

out, _ = run(tool_pair("Agent", "The court held: " + STATUTE), f'The agent reported "{STATUTE}".')
check("Agent tool result counts as a source", out == {})

# ---- the skill gate -------------------------------------------------------------------
out, _ = run(tool_pair("Bash", "x"), BAD, skill=False)
check("no plugin skill this session: not checked", out == {})

on = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "legal-research:find-cite"}}]}}]
out, _ = run(on + tool_pair("Bash", "x"), BAD, skill=False)
check("plugin-prefixed Skill call activates the check", out.get("decision") == "block")

on = prompt("<command-message>find-cite is running</command-message>\n<command-name>/legal-research:find-cite</command-name>")
out, _ = run(on + tool_pair("Bash", "x"), BAD, skill=False)
check("slash command activates the check", out.get("decision") == "block")

on = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "w", "name": "Workflow",
     "input": {"scriptPath": "/cache/legal-research/skills/cite-check/cite-check.workflow.js"}}]}}]
out, _ = run(on + tool_pair("Bash", "x"), BAD, skill=False)
check("skill workflow file activates the check", out.get("decision") == "block")

on = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": "anthropic-skills:docx"}}]}}]
out, _ = run(on + tool_pair("Bash", "x"), BAD, skill=False)
check("someone else's skill does not activate it", out == {})

# ---- subagent transcripts as sources --------------------------------------------------
sub = tool_pair("mcp__courtlistener__read_document", STATUTE, tid="a1")
out, _ = run([], f'The opinion says "{STATUTE}".', subagents={"agent-abc.jsonl": sub})
check("raw text fetched inside an Agent subagent counts", out == {})

out, _ = run([], f'The opinion says "{STATUTE}".',
             subagents={os.path.join("workflows", "wf_1", "agent-def.jsonl"): sub})
check("raw text fetched inside a Workflow agent counts", out == {})

sub = tool_pair("WebFetch", STATUTE, tid="a2")
out, _ = run([], f'The opinion says "{STATUTE}".', subagents={"agent-ghi.jsonl": sub})
check("WebFetch inside a subagent still does not count", out.get("decision") == "block")

# ---- files written in the final turn --------------------------------------------------
memo = f'# Memo\n\nThe Court explained that "{STATUTE}."\n'
out, _ = run(prompt("write the memo") + tool_pair("Bash", STATUTE) + write_call("/tmp/memo.md", memo),
             "Memo written.")
check("written memo with verified quote allowed", out == {})

out, _ = run(prompt("write the memo") + write_call("/tmp/memo.md", memo), "Memo written.")
check("written memo with unverified quote blocked, file named",
      out.get("decision") == "block" and "[memo.md]" in out.get("reason", ""))

out, _ = run(prompt("write the memo") + write_call("/tmp/memo.py", 'x = "' + STATUTE + '"'), "Done.")
check("non-text file types are not checked", out == {})

earlier = prompt("first task") + write_call("/tmp/old.md", memo, tid="w0")
out, _ = run(earlier + prompt("second task") + tool_pair("Bash", "ok"), "Second task done.")
check("file written in an earlier turn is not re-checked", out == {})

# ---- Claude's own writes are not sources ----------------------------------------------
out, _ = run(prompt("go") + write_call("/tmp/memo.md", memo)
             + tool_pair("Read", "     1\t" + memo, tid="r1", inp={"file_path": "/tmp/memo.md"}),
             f'As the memo says, "{STATUTE}".')
check("Read of a file Claude wrote does not vouch for it", out.get("decision") == "block")

edit = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "e1", "name": "Edit",
     "input": {"file_path": "/tmp/notes.md", "old_string": "a", "new_string": STATUTE}}]}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "e1",
         "content": "The file has been updated. Here's the result:\n     1→" + STATUTE}]}}]
out, _ = run(prompt("go") + tool_pair("Bash", "y") + edit, f'The notes say "{STATUTE}".')
check("Edit result echo does not vouch for it", out.get("decision") == "block")

# ---- switches -------------------------------------------------------------------------
out, _ = run(tool_pair("Bash", "x"), BAD, env={"LEGAL_RESEARCH_QUOTE_CHECK": "off"})
check("LEGAL_RESEARCH_QUOTE_CHECK=off disables the hook", out == {})

out, _ = run(tool_pair("Bash", "x"), BAD, env={"CLAUDE_CODE_PLUGIN_DIRS": "/x/mods/quote-guard:/y"})
check("stands down when the quote-guard mod is loaded", out == {})

# ---- the PostToolUse note -------------------------------------------------------------
out, _ = run(tool_pair("WebFetch", "summary"), "", script=NOTE, extra_input={"tool_name": "WebFetch"})
check("summary note added while a skill is active",
      "additionalContext" in out.get("hookSpecificOutput", {}))

out, _ = run(tool_pair("WebFetch", "summary"), "", script=NOTE, skill=False,
             extra_input={"tool_name": "WebFetch"})
check("summary note silent when no skill is active", out == {})

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
