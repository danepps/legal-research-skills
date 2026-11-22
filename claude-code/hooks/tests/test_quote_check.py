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

# Files written in the final turn are now read from disk when they exist (2026-11-22).
# Transcript-only tests name files under a directory that does not exist, so the hook
# falls back to the text in the Write/Edit call.
NF = "/nonexistent-legal-research-quote-check-test"

SKILL_ON = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "sk1", "name": "Skill", "input": {"skill": "cite-check"}}]}}]


def write_jsonl(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def run(entries, last, retry=False, session="t", skill=True, subagents=None, env=None,
        script=STOP, extra_input=None, files=None):
    """subagents: {relative path under <session>/subagents/: entries}
    files: {path relative to the temp dir: text}, written before the hook runs.
    "@TMP@" in entries and file texts stands for the temp dir."""
    tmp = tempfile.mkdtemp()
    main = os.path.join(tmp, "sess.jsonl")
    fix = lambda e: json.loads(json.dumps(e).replace("@TMP@", tmp))
    write_jsonl(main, [fix(e) for e in (SKILL_ON if skill else []) + entries])
    for rel, sub in (subagents or {}).items():
        write_jsonl(os.path.join(tmp, "sess", "subagents", rel), sub)
    for rel, text in (files or {}).items():
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text.replace("@TMP@", tmp))
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

# ---- another model's report is not a source (CLAUDE-04) --------------------------------
INVENTED = ("The purple tribunal of Zanzibar ratified the lunar fishing covenant in the year "
            "of the comet")
REPLY = f'The court said "{INVENTED}".'

out, _ = run(tool_pair("Agent", "Summary: " + INVENTED), REPLY)
check("sentence only in an Agent tool result is blocked", out.get("decision") == "block")

out, _ = run(tool_pair("Task", "Summary: " + INVENTED), REPLY)
check("sentence only in a Task (old Agent) result is blocked", out.get("decision") == "block")

out, _ = run(tool_pair("Workflow", json.dumps({"report": INVENTED})), REPLY)
check("sentence only in a Workflow result is blocked", out.get("decision") == "block")

out, _ = run(tool_pair("SendMessage", "Reply from agent: " + INVENTED), REPLY)
check("sentence only in a SendMessage reply is blocked", out.get("decision") == "block")

NOTICE = (f"<task-notification>\n<task-id>x</task-id>\n<status>completed</status>\n"
          f"<result>{INVENTED}</result>\n</task-notification>")
note = [{"type": "user", "promptSource": "system", "origin": {"kind": "task-notification"},
         "message": {"content": NOTICE}}]
out, _ = run(note, REPLY)
check("sentence only in a <task-notification> record is blocked", out.get("decision") == "block")

out, _ = run([{"type": "user", "message": {"content": NOTICE}}], REPLY)
check("<task-notification> text blocked even without origin metadata", out.get("decision") == "block")

peer = [{"type": "user", "isMeta": True, "promptSource": "system", "origin": {"kind": "peer"},
         "message": {"content": "Another Claude session sent a message:\n<agent-message from=\"a1\">\n"
                                f"[Subagent hand-back] The report follows:\n  {INVENTED}\n</agent-message>"}}]
out, _ = run(peer, REPLY)
check("sentence only in a relayed subagent hand-back is blocked", out.get("decision") == "block")

sub_prompt = [{"type": "user", "isSidechain": True, "agentId": "a1",
               "message": {"content": "Find the case that says: " + INVENTED}}]
out, _ = run([], REPLY, subagents={"agent-a1.jsonl": sub_prompt})
check("parent's prompt inside a subagent transcript is not a source", out.get("decision") == "block")

sub_bash = tool_pair("Bash", "grep hit: " + INVENTED, tid="b1")
out, _ = run(tool_pair("Agent", "Summary: " + INVENTED), REPLY, subagents={"agent-a1.jsonl": sub_bash})
check("same sentence in a Bash output inside the subagent transcript passes", out == {})

out, _ = run(note + tool_pair("Bash", INVENTED), REPLY)
check("human-free session with raw Bash output still passes", out == {})

memo_i = f'# Memo\n\n"{INVENTED}"\n'
out, _ = run(prompt("write it") + write_call(NF + "/memo.md", memo_i) + note, "Memo written.")
check("a <task-notification> does not start a new turn (memo before it still checked)",
      out.get("decision") == "block" and "[memo.md]" in out.get("reason", ""))

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
out, _ = run(prompt("write the memo") + tool_pair("Bash", STATUTE) + write_call(NF + "/memo.md", memo),
             "Memo written.")
check("written memo with verified quote allowed", out == {})

out, _ = run(prompt("write the memo") + write_call(NF + "/memo.md", memo), "Memo written.")
check("written memo with unverified quote blocked, file named",
      out.get("decision") == "block" and "[memo.md]" in out.get("reason", ""))

out, _ = run(prompt("write the memo") + write_call(NF + "/memo.py", 'x = "' + STATUTE + '"'), "Done.")
check("non-text file types are not checked", out == {})

earlier = prompt("first task") + write_call(NF + "/old.md", memo, tid="w0")
out, _ = run(earlier + prompt("second task") + tool_pair("Bash", "ok"), "Second task done.")
check("file written in an earlier turn is not re-checked", out == {})

# ---- Claude's own writes are not sources ----------------------------------------------
out, _ = run(prompt("go") + write_call(NF + "/memo.md", memo)
             + tool_pair("Read", "     1\t" + memo, tid="r1", inp={"file_path": NF + "/memo.md"}),
             f'As the memo says, "{STATUTE}".')
check("Read of a file Claude wrote does not vouch for it", out.get("decision") == "block")

edit = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "e1", "name": "Edit",
     "input": {"file_path": NF + "/notes.md", "old_string": "a", "new_string": STATUTE}}]}},
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

# ---- token boundaries (2026-11-14) -----------------------------------------------------
# The check was a bare substring test, so a quotation that began or ended inside a source
# word or number passed.
def reply(q):
    return 'The opinion says "%s" and nothing more.' % q

for name, source, quote in (
    ("dropped negative prefix (ineligible)", "the work is ineligible for copyright protection under federal law",
     "eligible for copyright protection under federal law"),
    ("dropped negative prefix (unreasonable)", "it was unreasonable to exclude county and state facilities",
     "reasonable to exclude county and state facilities"),
    ("amount cut at its thousands comma", "the obligation is to pay more than $400,000",
     "the obligation is to pay more than $400,"),
    ("amount cut at its decimal point", "the fee rose to more than $3.5 million last year",
     "the fee rose to more than $3"),
    ("number cut at its start", "they must pay more than $400,000 in damages right now",
     "000 in damages right now"),
    ("word cut at its end", "in this case the agency acted reasonably", "in this case the agency acted reason"),
    ("digits cut short", "liability arises under section 1983 of the act", "liability arises under section 198"),
    ("identifier cut before its letter", "the liability under rule 10b-5 is strict", "the liability under rule 10"),
    ("contraction cut at the apostrophe", "in that case the defendant can't be retried", "in that case the defendant can"),
    ("possessive cut at a curly apostrophe", "the panel then reviewed the court’s findings",
     "the panel then reviewed the court"),
    ("hyphenated negative prefix", "that holding is non-binding precedent in this circuit",
     "binding precedent in this circuit"),
    ("split form of a word broken by a soft hyphen at a line end",
     "the rule is un\u00ad\nnecessary because the amendment already covers it",
     "the rule is un necessary because the amendment"),
    ("prefix dropped across a bracketed page marker", "the statute is in-\n[*516]\neligible for protection here and now",
     "eligible for protection here and now"),
    ("quote ends with the hyphen of a compound", "that holding in this circuit is non-binding precedent",
     "that holding in this circuit is non-"),
    ("quote ends with a hyphen at a line end", "we hold that the work is in-\neligible for protection",
     "we hold that the work is in-"),
    ("first half of a hyphenated compound", "the flaw lay in the decision-making process",
     "the flaw lay in the decision"),
    ("prefix broken across a line", "the work is in-\neligible for copyright protection under federal law",
     "eligible for copyright protection under federal law"),
    ("first half of a word broken across a line", "we hold that the work is in-\neligible for protection",
     "we hold that the work is in"),
    ("statute cite cut one digit short", "the request was made under n.j.s.a. 47:1a-11 of the act",
     "the request was made under n.j.s.a. 47:1a-1"),
    ("prefix split off by a soft hyphen at a line end",
     "the rule is un\u00ad\nnecessary because the amendment already covers it",
     "necessary because the amendment already covers it"),
    ("first half before a soft hyphen at a line end",
     "we hold that the rule is un\u00ad\nnecessary because the amendment covers it",
     "we hold that the rule is un"),
    ("accented letter before the match", "everyone saw that their naïveté was plain to see", "veté was plain to see"),
    ("ellipsis segment starting inside a word", "the statute is clearly ineligible for protection under the act",
     "the statute is . . . eligible for protection under the act"),
    ("bracket does not excuse the other edge", "it said the agency was reasonable in its views of the matter",
     "the agency [is] reasonable in its view"),
):
    out, _ = run(tool_pair("Bash", source), reply(quote))
    check("partial token blocked: " + name, out.get("decision") == "block")

for name, source, quote in (
    ("whole amount", "the obligation is to pay more than $400,000", "the obligation is to pay more than $400,000"),
    ("quote ends before the source's final period", "the rule here applies under section 1983.",
     "the rule here applies under section 1983"),
    ("quote ends before the source's final quote mark", "it called the whole scheme 'entirely reasonable'",
     "called the whole scheme 'entirely reasonable"),
    ("quote starts at the source's first character", "eligible for protection under the act, it said",
     "eligible for protection under the act"),
    ("word broken by a soft hyphen at a line end, quoted whole",
     "the rule is un\u00ad\nnecessary because the amendment already covers it",
     "the rule is unnecessary because the amendment already covers it"),
    ("re-flowed word (soft hyphen, then a space), quoted whole",
     "the rule is un\u00ad necessary because the amendment already covers it",
     "the rule is unnecessary because the amendment already covers it"),
    ("quote crossing a bracketed star-page marker", "the court held that the [*516] statute applies here",
     "the court held that the statute applies here"),
    ("quote crossing a parallel-reporter marker", "the court held that the [**12] statute applies here",
     "the court held that the statute applies here"),
    ("bracketed words then a whole word", "the old mayor may issue an order whenever needed",
     "the [official] may issue an order whenever needed"),
    ("year before a comma and a number", "in the year 2020, 15 states acted on it", "in the year 2020"),
    ("whole word before a period", "the work was plainly eligible. the rest follows", "the work was plainly eligible"),
    ("whole hyphenated compound", "that holding is non-binding precedent in this circuit",
     "holding is non-binding precedent in this circuit"),
    ("word after a closed-up em dash", "the plaintiff knows—or reasonably should know—of the injury",
     "or reasonably should know—of the injury"),
    ("word after a typed double hyphen", "the plaintiff knows--or reasonably should know--of the injury",
     "or reasonably should know--of the injury"),
    ("word after a suspended hyphen", "the pre- and post-trial motions were all denied", "and post-trial motions were all denied"),
    ("page range cut at its hyphen", "see the discussion in id. at 516-17 for the rule", "see the discussion in id. at 516"),
    ("possessive kept whole", "the panel then reviewed the court's findings", "the panel then reviewed the court's findings"),
    ("accented word kept whole", "everyone saw that their naïveté was plain", "saw that their naïveté was plain"),
    ("whole-token hit after a partial one",
     "it is ineligible for protection under the act. later it became eligible for protection under the act",
     "eligible for protection under the act"),
    ("bracketed first letter", "yesterday the court held that the claim fails", "[T]he court held that the claim fails"),
    ("whole-token ellipsis segment", "the statute is clearly eligible for protection under the act",
     "the statute is . . . eligible for protection under the act"),
    ("footnote call after a word", "the work receives copyright protection12 under the statute",
     "the work receives copyright protection"),
    ("footnote call after a sentence-ending number", "The Act was first passed in 1871.45 The Court later read it broadly",
     "The Act was first passed in 1871."),
    ("footnote call after a comma", "Plaintiffs suing under section 1983,45 may recover fees",
     "Plaintiffs suing under section 1983"),
):
    out, _ = run(tool_pair("Bash", source), reply(quote))
    check("whole tokens allowed: " + name, out == {})

# ---- this plugin's own workflow result counts (2026-11-22, defect A) -------------------
# Observed in a headless /proofread run: the workflow's report reached the session as a
# <task-notification>, the session saved it with Write, and the hook blocked the saved
# report twice for quoting the workflow's own result.
PLUGIN_WF = os.path.realpath(os.path.join(HERE, "..", "..", "skills", "proofread",
                                          "proofread.workflow.js"))
OTHER_WF = "/cache/legal-research/skills/proofread/proofread.workflow.js"
# The research workflows return memos that quote cases and articles; their results must
# never vouch for those quotations, even though the scripts are this plugin's own.
LR_WF = os.path.realpath(os.path.join(HERE, "..", "..", "skills", "legal-research",
                                      "legal-research.workflow.js"))
CC_WF = os.path.realpath(os.path.join(HERE, "..", "..", "skills", "cite-check",
                                      "cite-check.workflow.js"))


def xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wf_launch(script, tid="wf1", run_id="wf_t1", task_id="wtask1", inp=None):
    """A background Workflow call and its launch notice, as the transcript records them."""
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Workflow",
         "input": inp or {"scriptPath": script, "args": {"outDir": "/x"}}}]}},
        {"type": "user", "toolUseResult": {"status": "async_launched", "taskId": task_id,
                                           "runId": run_id, "scriptPath": script},
         "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content":
                                  "Workflow launched in background. Task ID: %s\nScript file: %s\n"
                                  "Run ID: %s\n\nYou will be notified when it completes."
                                  % (task_id, script, run_id)}]}}]


def wf_notice(result_body, tid="wf1", task_id="wtask1", out_file="@TMP@/tasks/wtask1.output",
              summary="Dynamic workflow \"Proofread\" completed"):
    """The completion notice; result_body is the text between <result> tags, unescaped."""
    content = ("<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>%s</tool-use-id>\n"
               "<output-file>%s</output-file>\n<status>completed</status>\n<summary>%s</summary>\n"
               "<result>%s</result>\n<usage><agent_count>6</agent_count></usage>\n"
               "</task-notification>" % (task_id, tid, out_file, xml_escape(summary),
                                         xml_escape(result_body)))
    return [{"type": "user", "promptSource": "system",
             "origin": {"kind": "task-notification", "producer": "session-task"},
             "message": {"content": content}}]


def truncated(result_json, keep, path="@TMP@/tasks/wtask1.output"):
    return result_json[:keep] + "\n... (truncated %d chars, full result in %s)" % (
        len(result_json) - keep, path)


# A trimmed copy of the report the proofread workflow returned in that run (invented prose).
REPORT = """# Proofread — fixture

> Snapshot 2026-11-22 15:01:01 CST, SHA-256 302d3cc86966b156e6e21e9b04206e95cf424cca482b7b43667ce4233a8d1186; plain-text pass.

_TL;DR: 6 errors, 4 judgment calls, 1 typeface item, 0 citation-mechanics items, 0 author queries. The most important catch is the broken cross-reference "supra note 9" in Part III, which points to a note that does not exist (the draft has 3 footnotes)._

## Errors (fix these)

- **I. Records and Reasons, ≈18% in** — `The rule requires the clerk each refusal in the register.` — A verb is missing, so the sentence does not parse. Fix: "The rule requires the clerk to record each refusal in the register."
- **I. Records and Reasons, ≈27% in** — `The resulting comparision remains provisional` — Misspelling. Fix: "The resulting comparison remains provisional".
- **II. Comparing Entries, ≈45% in** — `three written explanations was placed` — Subject-verb agreement: the subject "explanations" is plural but the verb is singular. Fix: "three written explanations were placed".
- **note 3** — `The distinction between evidence and judgment remain central` — Subject-verb agreement: the subject "distinction" is singular but the verb is plural. Fix: "The distinction between evidence and judgment remains central".

## Judgment calls (probably fix)

- **I. Records and Reasons, ≈9% in** — `…sily as a careful one. The argument concerns the the relationship between recording and accountab…` — Repeated word: "the the". Fix: delete one "the".
- **II. Comparing Entries, ≈55% in** — `Yet the decisionmaking process might remain unchanged` — Inconsistent spelling; the draft writes "decision-making" elsewhere. Fix: "Yet the decision-making process might remain unchanged".
- **II. Comparing Entries, ≈64% in** — `…ter summaries should preserve those features as as well. Without that discipline, a summary can…` — Repeated word: "as as". Fix: delete one "as".
- **III. Limits and Implications, ≈82% in** — `set out in supra note 9.` — Bad cross-reference. The draft has no note 9, and the "limited premise" is stated in note 1. Fix: "set out in supra note 1."

## Document-wide conventions

| Issue | Draft's dominant form | Deviations | Recommendation |
|---|---|---|---|
| decision-making vs. decisionmaking | decision-making (2 instances) | decisionmaking (1 instance), e.g. `Yet the decisionmaking process might remain unchanged` | Use hyphenated "decision-making" throughout. |
"""
RESULT = json.dumps({"report": REPORT, "counts": {"candidates": 11, "confirmed": 11},
                     "exitState": "complete", "degradation": [], "rejectedFindings": []},
                    ensure_ascii=False)
# What the session saved: the report with its own header lines and production details.
SAVED = REPORT.replace("# Proofread — fixture\n\n", "# Proofread — fixture\n\nTopic: Proofread of "
                       "fixture\nDate: 2026-11-22 15:01 CST\nBy: Claude\n\n", 1) + \
    "\n---\nProduction details: Claude Code /proofread (Standard, style off)\n"
SAVED_PATH = "@TMP@/work/fixture — Proofread.md"
PROOF_ON = [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "sk2", "name": "Skill", "input": {"skill": "legal-research:proofread"}}]}}]


def proof_run(launch, notice, saved=SAVED, extra_files=None):
    files = {"work/fixture — Proofread.md": saved}
    files.update(extra_files or {})
    return run(prompt("proofread fixture.docx") + PROOF_ON + tool_pair("Bash", "snapshot taken")
               + launch + notice + write_call(SAVED_PATH, saved), "The report is saved.",
               files=files)


out, _ = proof_run(wf_launch(PLUGIN_WF), wf_notice(RESULT))
check("regression: saved proofread report that repeats the plugin workflow's result is allowed",
      out == {})

out, _ = proof_run(wf_launch(OTHER_WF), wf_notice(RESULT))
reason = out.get("reason", "")
check("regression: same report from a workflow outside this plugin is blocked",
      out.get("decision") == "block" and "Snapshot 2026-11-22" in reason
      and "The rule requires the clerk to record each refusal" in reason)
check("regression: no flagged span runs from one list item into the next (defect B)",
      "**II." not in reason and "Comparing Entries" not in reason and "\n- " not in reason)

for name, wf in (("legal-research", LR_WF), ("cite-check", CC_WF)):
    check(name + " workflow script exists where the test expects it", os.path.isfile(wf))
    memo_lr = f'# Memo\n\nThe court held that "{INVENTED}".\n'
    res_lr = json.dumps({"memo": memo_lr, "report": memo_lr})
    out, _ = run(prompt("research it") + [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "skx", "name": "Skill", "input": {"skill": name}}]}}]
                 + wf_launch(wf) + wf_notice(res_lr) + write_call("@TMP@/work/m.md", memo_lr),
                 "Memo saved.", files={"work/m.md": memo_lr})
    check("saved memo quoting only the %s workflow's result is blocked" % name,
          out.get("decision") == "block" and "purple tribunal" in out.get("reason", ""))

extra = SAVED + '\nNote: the clerk said "an invented rewording that the workflow never proposed".\n'
out, _ = proof_run(wf_launch(PLUGIN_WF), wf_notice(RESULT), saved=extra)
check("text the session added to the saved report is still checked",
      out.get("decision") == "block" and "an invented rewording" in out.get("reason", "")
      and "Snapshot" not in out.get("reason", ""))

out, _ = proof_run(wf_launch(PLUGIN_WF), wf_notice(RESULT, tid="someone-else"))
check("notice for a different tool call does not count", out.get("decision") == "block")

out, _ = proof_run(wf_launch(PLUGIN_WF, inp={"scriptPath": PLUGIN_WF, "script": "export default 1"}),
                   wf_notice(RESULT))
check("plugin scriptPath with an inline script does not count", out.get("decision") == "block")

out, _ = proof_run(write_call(PLUGIN_WF, "// rewritten", tid="w9") + wf_launch(PLUGIN_WF),
                   wf_notice(RESULT))
check("plugin workflow script Claude rewrote this session does not count",
      out.get("decision") == "block")

out, _ = proof_run(wf_launch(PLUGIN_WF), wf_notice(json.dumps({"report": "short"}), summary=REPORT))
check("text only in the notice's summary, not its result, does not count",
      out.get("decision") == "block")

ONLY_IN_FULL = json.dumps({"report": "x" * 300 + " " + INVENTED + "."})
OUT_FILE = json.dumps({"summary": "s", "logs": [], "result": json.loads(ONLY_IN_FULL)})
memo_inv = f'# Report\n\nThe draft says "{INVENTED}".\n'


def inv_run(launch, notice, files):
    files = dict(files)
    files["work/r.md"] = memo_inv
    return run(prompt("go") + PROOF_ON + launch + notice + write_call("@TMP@/work/r.md", memo_inv),
               "Saved.", files=files)


out, _ = inv_run(wf_launch(PLUGIN_WF), wf_notice(truncated(ONLY_IN_FULL, 100)),
                 {"tasks/wtask1.output": OUT_FILE})
check("cut-off notice: full result read from the output file it names", out == {})

out, _ = inv_run(wf_launch(PLUGIN_WF), wf_notice(truncated(ONLY_IN_FULL, 100)),
                 {"sess/workflows/wf_t1.json": json.dumps(
                     {"runId": "wf_t1", "taskId": "wtask1", "scriptPath": PLUGIN_WF,
                      "result": json.loads(ONLY_IN_FULL)})})
check("cut-off notice, no output file: result read from the run record", out == {})

out, _ = inv_run(wf_launch(PLUGIN_WF), wf_notice(truncated(ONLY_IN_FULL, 100)),
                 {"sess/workflows/wf_t1.json": json.dumps(
                     {"runId": "wf_t1", "taskId": "wtask1", "scriptPath": OTHER_WF,
                      "result": json.loads(ONLY_IN_FULL)})})
check("run record naming another script does not count", out.get("decision") == "block")

out, _ = inv_run(wf_launch(PLUGIN_WF), wf_notice(truncated(ONLY_IN_FULL, 100)),
                 {"sess/workflows/wf_t1.json": json.dumps(
                     {"runId": "wf_t1", "taskId": "wtask1", "scriptPath": LR_WF,
                      "result": json.loads(ONLY_IN_FULL)})})
check("run record naming the legal-research workflow does not count", out.get("decision") == "block")

out, _ = inv_run(wf_launch(LR_WF), wf_notice(truncated(ONLY_IN_FULL, 100)),
                 {"tasks/wtask1.output": OUT_FILE})
check("cut-off legal-research notice: its output file does not count", out.get("decision") == "block")

out, _ = inv_run(wf_launch(PLUGIN_WF),
                 wf_notice(truncated(ONLY_IN_FULL, 100), out_file="@TMP@/tasks/other.output"),
                 {"tasks/other.output": OUT_FILE})
check("output file not named for the task does not count", out.get("decision") == "block")

out, _ = inv_run(wf_launch(PLUGIN_WF), wf_notice(truncated(ONLY_IN_FULL, 100)), {})
check("cut-off notice with nothing else: text past the cut does not count",
      out.get("decision") == "block")

BEFORE_CUT = json.dumps({"report": INVENTED + ".", "rest": "y" * 300})
out, _ = inv_run(wf_launch(PLUGIN_WF), wf_notice(truncated(BEFORE_CUT, 200)), {})
check("cut-off notice with nothing else: text before the cut counts", out == {})

# ---- quotation marks pair within one paragraph, item or cell (2026-11-22, defect B) ------
for name, text in (
    ("closing mark of a short quotation opening a span into the next list item",
     '- Repeated word: "the the". Fix: delete one "the".\n'
     '- Inconsistent spelling; the draft writes "decision-making" elsewhere.\n'),
    ("closing mark of a short quotation opening a span on the same line",
     'Fix: delete one "the". Then the court wrote more words here and "as" too.'),
    ("unclosed mark in one list item pairing with the next item",
     '- He said "this was unfinished and\n- The next item has "short" words'),
    ("unclosed mark in a heading pairing with the paragraph below",
     '## The "Part\nThe rule is stated in four words" here.'),
    ("mark in one table cell pairing with the next cell",
     '| uses "alpha | and then five more words here" |'),
    ("mark in a numbered item pairing with the next item",
     '1. He said "this was unfinished and\n2. The next item has "short" words'),
    ("mark before a blockquote pairing with a mark inside it",
     'He said "this was unfinished and more\n> has "x"'),
):
    out, _ = run(tool_pair("Bash", "nothing relevant"), text)
    check("no cross-unit pairing: " + name, out == {})

out, _ = run(tool_pair("Bash", "x"), 'The court said "this quotation is wrapped\nacross two lines of one paragraph" today.')
check("quotation wrapped over two lines of one paragraph is still checked", out.get("decision") == "block")

out, _ = run(tool_pair("Bash", STATUTE), 'The statute says "pursuant to a delegation of\nauthority from the Commissioner of Internal Revenue."')
check("wrapped quotation found in the source passes", out == {})

out, _ = run(tool_pair("Bash", "x"), '- The court said "this quotation is wrapped\n  across the item continuation line" today.')
check("quotation over a list item's continuation line is still checked", out.get("decision") == "block")

out, _ = run(tool_pair("Bash", STATUTE), "> In the case of any Taxpayer Advocate Directive issued\n"
             "> by the National Taxpayer Advocate pursuant to a delegation")
check("two-line blockquote found in the source passes", out == {})

out, _ = run(tool_pair("Bash", "x"), "> In the case of any Taxpayer Advocate Directive issued\n"
             "> by the National Taxpayer Advocate pursuant to a delegation")
check("two-line blockquote not in the source is blocked", out.get("decision") == "block")

out, _ = run(tool_pair("Bash", "x"), '> He said "this invented sentence runs\n> over two quoted lines here" yes.')
check("quotation marks over two blockquote lines are still paired",
      "“this invented sentence runs" in out.get("reason", ""))

out, _ = run(tool_pair("Bash", "x"), '| Fix | Use "an invented phrase of six words" here |')
check("quotation inside one table cell is still checked", out.get("decision") == "block")

out, _ = run(tool_pair("Bash", "x"), 'A 12" ruler and "this invented sentence is not in any source" here.')
check("stray inch mark does not hide a later quotation in the paragraph",
      "this invented sentence is not in any source" in out.get("reason", ""))

# ---- a file written this turn is checked as it is now (2026-11-22, defect C) -------------
# Observed: after a block the model removed every quotation mark from the file with sed,
# and the hook flagged the same passages again from the text of the original Write call.
bad_memo = '# Memo\n\nHe said "this quotation is not in the corpus anywhere at all".\n'
fixed_memo = "# Memo\n\nHe said this quotation is not in the corpus anywhere at all.\n"
other_bad = '# Memo\n\nShe said "another sentence that no source contains at all".\n'
MEMO = "@TMP@/memo.md"


def edit_call(path, new, tid="e7"):
    return [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Edit",
         "input": {"file_path": path, "old_string": "a", "new_string": new}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "The file has been updated."}]}}]


out, _ = run(prompt("go") + write_call(MEMO, bad_memo), "Done.", files={"memo.md": fixed_memo})
check("written file fixed on disk since the Write is allowed", out == {})

out, _ = run(prompt("go") + write_call(MEMO, bad_memo), "Done.", retry=True, session="c-retry",
             files={"memo.md": fixed_memo})
check("retry after a shell fix checks the file on disk", out == {})

out, _ = run(prompt("go") + write_call(MEMO, bad_memo), "Done.", files={"memo.md": bad_memo})
check("written file still holding the quotation is blocked", out.get("decision") == "block")

out, _ = run(prompt("go") + write_call(MEMO, fixed_memo), "Done.", files={"memo.md": other_bad})
check("written file changed on disk to a new unverified quotation is blocked",
      out.get("decision") == "block" and "another sentence" in out.get("reason", ""))

out, _ = run(prompt("go") + write_call(MEMO, bad_memo), "Done.")
check("written file gone from disk: the Write's text is checked", out.get("decision") == "block")

q_edit = 'He said "this quotation is not in the corpus anywhere at all".'
out, _ = run(prompt("go") + edit_call(MEMO, q_edit), "Done.", files={"memo.md": fixed_memo})
check("edited file whose added quotation was removed since is allowed", out == {})

out, _ = run(prompt("go") + edit_call(MEMO, q_edit), "Done.", files={"memo.md": bad_memo})
check("edited file still holding the added quotation is blocked", out.get("decision") == "block")

out, _ = run(prompt("go") + edit_call(MEMO, "a plain added sentence"), "Done.",
             files={"memo.md": bad_memo})
check("edited file: a quotation this turn did not add is not checked", out == {})

# ---- the PostToolUse note -------------------------------------------------------------
out, _ = run(tool_pair("WebFetch", "summary"), "", script=NOTE, extra_input={"tool_name": "WebFetch"})
check("summary note added while a skill is active",
      "additionalContext" in out.get("hookSpecificOutput", {}))

out, _ = run(tool_pair("WebFetch", "summary"), "", script=NOTE, skill=False,
             extra_input={"tool_name": "WebFetch"})
check("summary note silent when no skill is active", out == {})

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
