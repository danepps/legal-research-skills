# legal-research-skills

Research assistants for legal scholars, built as skills for [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) (Anthropic) and [Codex](https://developers.openai.com/codex) (OpenAI). They cite-check a law-review draft footnote by footnote, find verified authorities for a proposition, proofread a long manuscript, build a Zotero library with real records, write research memos, and assemble the brief set for a Supreme Court case.

Written by [Daniel Epps](https://law.wustl.edu/faculty-staff-directory/profile/daniel-epps/), Howard and Caroline Cayne Distinguished Professor of Law at Washington University in St. Louis and co-host of the *Divided Argument* podcast, who builds and uses these in his own scholarship every day. Released as-is under the MIT license. Questions and bug reports go to the [issues page](https://github.com/danepps/legal-research-skills/issues); see also his [Bluebook citation style](https://danepps.github.io/bluebook/) and [Zotero plugins](https://danepps.github.io/zotero/) for law reviews.

## Why not just use the chat window?

If you have asked ChatGPT or Claude for a citation, you know the problem: the answer sounds right and the case may not exist. Chat assistants answer from memory. They also cannot open your Word file, cannot see your footnotes as footnotes, and lose the thread somewhere around the fortieth citation.

Claude Code and Codex are the same models in a different setting. Instead of a chat window, they work on your own computer, where the model can open files, run small checking programs, and keep working for an hour without you. You can use them from the Terminal app, or from a regular desktop app: the [Claude desktop app](https://code.claude.com/docs/en/desktop) has a Code tab for this on Mac and Windows, and OpenAI ships a [Codex app](https://learn.chatgpt.com/docs/build-skills) for Mac and Windows. Either way, the model gains the same abilities, and that changes what you can ask for:

| | Chat window | Claude Code or Codex with these skills |
|---|---|---|
| Reading your draft | You paste chunks; footnotes arrive as a jumble | Opens the .docx itself, footnotes and all, and takes a snapshot so edits mid-run don't confuse it |
| Checking a citation | Tells you what it remembers | Looks the case up on CourtListener, opens the opinion, and compares your quotation to the actual text |
| Scale | A handful of cites before it drifts | Every footnote in a 300-footnote article, split among many parallel agents, then re-checked by a separate verifier |
| What you get back | A reply you have to act on from memory | A report file, problems first, each with the exact words to Cmd+F in Word |
| Consistency | Different each time | The same extraction and comparison scripts every run; the model is used only where judgment is needed |

The skills in this repository are the instructions and scripts that make the model behave this way. Installing them is a one-time copy-and-paste, after which they are available in both the Terminal and the desktop app.

## What you can ask for

Once installed, you open the folder that holds your draft, in the Terminal or in the desktop app, and ask in plain English.

- **"Cite-check my draft."** It extracts every citation and quotation, resolves the *Id.* and *supra* chains, checks each case against CourtListener and the official reporter, checks each article against your Zotero library and then the open web, and returns a graded, footnote-by-footnote report. A "needs your attention" section comes first. It says what it checked, against what, and what it could not open.
- **"Find me a cite for the proposition that…"** A few verified authorities, each with a pincite and a parenthetical, preferring the Supreme Court and flagship journals. A footnote-filler, not a memo.
- **"Proofread this."** Typos, doubled words, editing residue, and inconsistencies in hyphenation, capitalization, defined terms, and cross-references, with a find-string for each. It handles the prose; cite-check handles the authorities.
- **"Build a Zotero collection on…"** Finds the sources, creates proper records through Zotero's own interface, attaches open-access PDFs, checks the whole library for duplicates first, and runs a verification pass over everything it added.
- **"Write me a research memo on…"** Several agents research in parallel across free legal sources, every authority is verified, and you get a memo with working links.
- **"Prep *Smith v. Arizona*."** Pulls the questions presented, the lower-court opinion, the cert-stage and merits briefs, the Solicitor General's amicus, and the argument transcript, and loads them onto a reMarkable tablet in reading order.

## Honest limits

- **It finds problems; you decide.** This is a first pass that catches what a tired human misses, not a replacement for your own read or the journal's cite-check. The verifier pass removes many false alarms, not all of them.
- **It cannot log in for you.** HeinOnline, Westlaw, and publisher paywalls are off limits to the automation. The report lists what it could not open, and you can download a PDF yourself and hand it over.
- **It costs money and time.** A full cite-check of a long article runs for a while and uses a meaningful amount of your Claude or ChatGPT plan. Start with a short piece.
- **It is not the chat window.** You will paste a few commands once to install. After that you type requests in English, in the Terminal or in the desktop app, whichever you prefer.

## Getting started

Pick whichever of these three feels least intimidating. They all end in the same place.

**Option A: let the assistant install itself.** Open the Claude desktop app's Code tab (or Codex), choose any folder, and paste this sentence:

> Install the skills from https://github.com/danepps/legal-research-skills by running its installer: `curl -fsSL https://danepps.github.io/legal-research-skills/install.sh | sh`

It will ask your permission to run the command, do the install, and tell you what it did. Then start a new session.

**Option B: one line in Terminal.** Open the Terminal app (on a Mac, press Cmd-Space and type "Terminal"), paste this, and press Return:

```sh
curl -fsSL https://danepps.github.io/legal-research-skills/install.sh | sh
```

The installer downloads the skills to a folder called `legal-research-skills` in your home directory and links them where Claude Code and Codex look. It detects which tool you have and never overwrites anything already there. Run the same line again later to update. (If the Mac says git is missing, accept its offer to install the command-line tools, then run the line again.)

**Option C: by hand.** The copy-and-paste blocks are in the [Install for Claude Code](#install-for-claude-code) and [Install for Codex](#install-for-codex) sections below.

Before or after installing, two short setup steps:

1. **Install one of the two tools, if you haven't.** [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) needs a Claude Pro or Max plan or an Anthropic API key; the [Claude desktop app](https://code.claude.com/docs/en/desktop) includes it under its Code tab. [Codex](https://developers.openai.com/codex) needs a ChatGPT Plus or Pro plan or an OpenAI API key, and comes as a command-line tool or a desktop app.

   **On a Claude Pro plan, one extra switch.** Cite-check, proofread, and legal-research run as multi-agent "dynamic workflows," which Claude turns on by default for Max and Team plans but not for Pro. In Claude Code, type `/config`, find the **Dynamic workflows** row, and turn it on ([docs](https://code.claude.com/docs/en/workflows)). Without it, those three skills will fail at the fan-out step and the other three work normally. A reader hit exactly this, so check it before your first cite-check.
2. **Get a free CourtListener account** and copy an API token from [courtlistener.com/profile/api-token](https://www.courtlistener.com/profile/api-token/). This is how the skills confirm that a case exists. Add this line to the end of the file `~/.zshrc` (Mac) with the token pasted in, then open a new Terminal window or restart the app:

   ```sh
   export COURTLISTENER_API_TOKEN="paste-your-token-here"
   ```

   Optional: if you keep sources in Zotero, create a key at [zotero.org/settings/keys](https://www.zotero.org/settings/keys) and set `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` the same way. Without it, cite-check still works; it just checks articles against the open web only.

Then open the folder with a short draft, in the Terminal or the desktop app, and type "cite-check this draft." Read the "needs your attention" section first.

Everything below this line is for readers who want the details.

---

## Layout

Two parallel implementations live here, one per runtime. They share a design philosophy but are **separate codebases**, not ports of each other.

| Folder | Runtime | Default install location |
|---|---|---|
| [`claude-code/`](claude-code/) | Claude Code (Anthropic) | `~/.claude/skills/<skill>/` |
| [`codex/`](codex/) | Codex CLI (OpenAI) | `~/.agents/skills/<skill>/` |

## What the skills share

The skills differ in detail but follow the same house rules, which came out of real failures on real drafts:

- **Verify against primary sources, not model memory.** Cases are checked against [CourtListener](https://www.courtlistener.com/) and official reporters; scholarship against the user's Zotero library and then the open web. Nothing is reported as verified without saying *on what basis*.
- **Deterministic scripts for structure, models for judgment.** Footnote extraction, `Id.`/`supra` resolution, quote matching, and schema validation are plain Python, so they are repeatable and cannot invent a source. Model agents handle the parts that need reading. (Scripts can still have bugs, and invoking them still costs some context.)
- **Verify the verifier.** Multi-agent runs end with an independent pass over the findings before anything reaches the user, because the first pass produces confident false positives.
- **Limits enforced where a script can enforce them.** Fetch sizes, page counts, and chunk sizes are hard caps in code, and run validators check recorded usage against budgets. Token, browsing, and time limits also depend on what the runtime measures and on the lead agent's supervision.
- **Report for a reader in Word.** Findings carry verbatim find-strings and footnote numbers rather than internal paragraph ids, so each one can be located with Cmd+F.

Passing a validator confirms the structural and workflow requirements it specifies. It does not establish that a model read an authority correctly; the lead agent remains responsible for source support, interpretation, and disclosed limits.

## Claude Code skills (`claude-code/`)

| Skill | What it does |
|---|---|
| **legal-research** | Multi-agent legal research that fans out across free legal sources, verifies every authority, and returns a memo. Modes: case law, scholarship, or both. Also the shared toolbox: `check_cite.py` (CourtListener citation lookup), `cl_case_tools.py` (opinion PDFs), `fetch_page.py` (hard-capped fetcher), `citeform.py` (reads italics and small caps out of .docx runs), `md2docx.py` (stdlib Markdown to .docx). |
| **cite-check** | Takes an article draft (.docx with footnotes), extracts every citation and quotation, resolves the cross-reference web, verifies each against the real source, and returns a graded footnote-by-footnote report with a "needs your attention" section first. `DESIGN.md` records the design and the lessons from the first full practice run, including where the cost estimate was wrong and what changed. |
| **proofread** | Prose-only proofreading of a long draft: typos, doubled words, editing residue, and internal consistency (hyphenation, capitalization, defined terms, cross-references). Owns the prose; cite-check owns the authorities. |
| **find-cite** | Quick, verified citation-finding for one proposition. A footnote-filler, not a memo. Prefers Supreme Court cites and flagship-journal scholarship, each with a pincite and a parenthetical, verified before delivery. |
| **build-library** | Builds or extends a Zotero collection of verified sources via the Zotero Web API, then runs a deterministic check (`check_source.py`) that every added item must pass. Includes a whole-library inventory script, because delegating the duplicate check to a subagent produced duplicates. |
| **case-prep** | Gathers the full document set for a Supreme Court case (questions presented, lower-court opinion, cert-stage and merits briefs, SG amicus, argument transcript), crops margins, and loads it onto a reMarkable tablet in a per-case folder. |

### Install for Claude Code

```sh
git clone https://github.com/danepps/legal-research-skills.git
cd legal-research-skills
mkdir -p ~/.claude/skills
for s in legal-research cite-check proofread find-cite build-library case-prep; do
  if [ -e ~/.claude/skills/$s ] && [ ! "$(readlink ~/.claude/skills/$s)" = "$PWD/claude-code/$s" ]; then
    echo "skipping $s: ~/.claude/skills/$s already exists"
  else
    ln -sfn "$PWD/claude-code/$s" ~/.claude/skills/$s
  fi
done
```

The links track the checkout, so `git pull` updates the installed skills. The skills reference each other at `~/.claude/skills/<skill>/...` (cite-check, proofread, find-cite, and case-prep all import from legal-research), so install the set together at that path. Start a new Claude Code session and type `/` to confirm the six names appear.

The Claude desktop app's **Code** tab runs local sessions from this same folder, so one install serves the Terminal and the app ([docs](https://code.claude.com/docs/en/desktop)). Two exceptions: the app's Cowork tab takes its skills from your claude.ai account settings, not from this folder, and cloud sessions at claude.ai/code load account skills instead of local ones.

Runtime notes specific to Claude Code:

- cite-check, proofread, and legal-research use Claude Code's `Workflow` tool (the `.workflow.js` files) for multi-agent fan-out. Dynamic workflows must be enabled: they are on by default for Max, Team, and Enterprise plans and for API access, but **a Pro plan has to turn them on from the Dynamic workflows row in `/config`** ([docs](https://code.claude.com/docs/en/workflows)). Each run also asks for approval before it starts; in the desktop app that is an approval card with Once, Always, and Deny.
- cite-check and find-cite assume a Zotero MCP server for library search; the scripts also read Zotero credentials from the `zotero` MCP server entry in `~/.claude.json`.
- build-library's HeinOnline section assumes an institutional library proxy; replace `<proxy-host>` with yours.
- case-prep assumes a reMarkable MCP server; the download-and-crop steps work without one.

`NOTES.md` session-handoff files and practice-run test data are not included.

## Codex skills (`codex/`)

Independent implementations for Codex CLI. These skills combine source review with deterministic extraction, evidence records, and completion checks. Each workflow supplies the helpers appropriate to its task: cite-check, internal-proofread, and build-zotero-library use an `init_run.py` / `validate_run.py` pair; legal-research-memo uses `init_research_run.py` / `validate_research_run.py`; find-cite validates an evidence packet with `validate_packet.py`; deep-research drives a run through subcommands of `research_run.py`. A run is not reported complete until its validator passes.

| Skill | What it does |
|---|---|
| **legal-research-memo** | Verified legal or scholarly memos: doctrinal synthesis, historical research, literature reviews, resumable investigations. References cover source protocol, subagent orchestration, autonomous runs, and a review checklist. |
| **cite-check** | Verifies citations, quotations, pincites, proposition support, cross-references, source versions, and URLs in a draft, with a documented verification protocol and schema-validated run output. |
| **internal-proofread** | Proofreads long drafts for internal textual defects using deterministic whole-document checks, bounded subagent review, independent recall and verification passes, and machine-enforced completion gates. Comparison against an externally supplied "challenger" report is optional. |
| **find-cite** | A small set of verified, footnote-ready authorities for one proposition, delivered as a validated evidence packet. |
| **build-zotero-library** | Builds or extends a verified Zotero collection, including full-text PDFs. Open-access PDFs are fetched directly; anything behind a paywall or login is attached from a file the user downloads, with provenance recorded. Nothing automates institutional access. |
| **deep-research** | A resumable, source-grounded investigation runner for the CLI, with cost controls and anti-spiral rules. General-purpose rather than legal, but used by the legal skills. |

### Install for Codex

Codex loads user-level skills from `~/.agents/skills/` and follows symlinked skill folders ([OpenAI docs](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)). An existing `~/.codex/skills/` installation keeps working; point the links wherever your Codex reads them.

```sh
git clone https://github.com/danepps/legal-research-skills.git
cd legal-research-skills
mkdir -p ~/.agents/skills
for s in legal-research-memo cite-check internal-proofread find-cite build-zotero-library deep-research; do
  if [ -e ~/.agents/skills/$s ] && [ ! "$(readlink ~/.agents/skills/$s)" = "$PWD/codex/$s" ]; then
    echo "skipping $s: ~/.agents/skills/$s already exists"
  else
    ln -sfn "$PWD/codex/$s" ~/.agents/skills/$s
  fi
done
```

The loop leaves any existing file, directory, or differently-pointed link in place and reports it. The links track the checkout, so `git pull` updates the installed skills. Start or refresh Codex and confirm the six skill names appear in its skill list.

OpenAI's docs list the user-level folder as shared by the Codex CLI, the Codex desktop app, and the IDE extension, with symlinked folders followed ([docs](https://learn.chatgpt.com/docs/build-skills)). If the desktop app does not show them, use its reload-skills command or restart it; earlier app builds had a discovery bug with this folder.

## Prerequisites and configuration

| Capability | What you need |
|---|---|
| Script execution | Python 3.11 or newer (the test suite runs on 3.11, 3.12, and 3.13). The scripts use only the standard library and sibling modules in the same skill folder. |
| Current external research | Live web access or an authorized connected source in your runtime. Installing the skills does not supply this; deep-research says so explicitly when it is missing. |
| Case identity screening | Your own `COURTLISTENER_API_TOKEN` (free, from [courtlistener.com](https://www.courtlistener.com/profile/api-token/)); `COURTLISTENER_TOKEN` and the file `~/.config/courtlistener/token` are read as fallbacks. The helper confirms a citation exists and resolves to the named case. Whether it supports the proposition still requires reading it. |
| Zotero operations | Your own `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` (`user` or `group`), from [zotero.org/settings/keys](https://www.zotero.org/settings/keys). On macOS the Codex scripts also accept a Keychain generic-password entry under the service name `codex-zotero-mcp` (accounts `api-key` and `library-id`). |
| Word output | None beyond Python. Markdown is the canonical deliverable; the .docx helpers write OOXML with the standard library. |
| PDF text extraction | `pdftotext` (poppler) where a helper reads a PDF, such as the memo skill's quantifier audit. Not needed for every task. |
| Parallel review | A runtime that exposes subagents. The named custom roles and models in the orchestration references are preferences, not requirements; each skill falls back to the agents and models your runtime actually has and records the routing it used. |

Keep credentials, library identifiers, and account exports out of the repository and out of issues.

## Tests

One offline command covers both folders. It runs every `test_*.py` entry point as its own process (several are standalone assertion scripts, not `unittest` cases), parses every Python file, checks every relative Markdown link, and validates each skill's frontmatter and Codex UI metadata. It needs no credentials or network.

```sh
python3 run_tests.py
```

The same command runs in GitHub Actions on Python 3.11, 3.12, and 3.13.

## Status

These are working tools, not a product. They are written for a specific workflow (law-review drafts in Word, a Zotero library, free legal sources) and will need adapting elsewhere. Date-stamped notes in the skill files record why a rule exists; they are left in deliberately.

## License

MIT. See [LICENSE](LICENSE).
