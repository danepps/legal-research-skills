# legal-research-skills

Research assistants for legal scholars, packaged as plugins for [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) (Anthropic) and [Codex](https://developers.openai.com/codex) (OpenAI). They cite-check a law-review draft footnote by footnote, find verified authorities for a proposition, proofread a long manuscript, build a Zotero library with real records, write research memos, and assemble the brief set for a Supreme Court case.

Written by [Daniel Epps](https://law.wustl.edu/faculty-staff-directory/profile/daniel-epps/), Howard and Caroline Cayne Distinguished Professor of Law at Washington University in St. Louis and co-host of the *Divided Argument* podcast, who builds and uses these in his own scholarship every day. Released as-is under the MIT license. Questions and bug reports go to the [issues page](https://github.com/danepps/legal-research-skills/issues) or to [epps@wustl.edu](mailto:epps@wustl.edu); see also his [Bluebook citation style](https://danepps.github.io/bluebook/) and [Zotero plugins](https://danepps.github.io/zotero/) for law reviews.

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

The skills in this repository are the instructions and scripts that make the model behave this way. Installing them is one command, after which they are available in both the Terminal and the desktop app, and updates arrive the way app updates do.

## What you can ask for

Once installed, you open the folder that holds your draft, in the Terminal or in the desktop app, and ask in plain English.

- **"Cite-check my draft."** It extracts every citation and quotation, resolves the *Id.* and *supra* chains, checks each case against CourtListener and the official reporter, checks each article against the open web (and against your Zotero library first, if you use Zotero), and returns a graded, footnote-by-footnote report. A "needs your attention" section comes first. It says what it checked, against what, and what it could not open.
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

Everything happens inside Claude Code, in conversation. You will not open the Terminal, edit a file, or set an environment variable. (Codex users: see [Other ways to install](#other-ways-to-install) below.)

**Step 1. Open Claude Code.** The easiest way is the [Claude desktop app](https://claude.ai/download) for Mac or Windows, which needs a Claude Pro or Max plan. Install it, sign in, and click the **Code** tab at the top of the window. In the row under the prompt box, choose the top entry under **Local** as the environment, then click the folder control next to it and open any folder; the one that holds a draft you want checked is a good choice. (If you already use Claude Code in the Terminal, open the folder there and type `claude`; the steps below are the same.)

**Step 2. Install the plugin.** Paste this into the prompt box and press Return:

```text
/plugin install legal-research --marketplace danepps/legal-research-skills
```

What to expect: Claude Code fetches this repository and may show a panel describing the plugin; accept the defaults (install for your user, not just this folder). When it says the plugin is installed, start a new session, or type `/reload-plugins`. Two things that can get in the way:

- If Claude Code says it does not understand the command, it is older than version 2.1.275. Type `/plugin marketplace add danepps/legal-research-skills`, press Return, then `/plugin install legal-research@danepps`. That second command opens a details panel; choose **Install** there.
- Fetching the plugin uses a program called git. Most Macs have it; if a dialog offers to install the "command line developer tools," click **Install**, wait for it to finish, and paste the line again. On Windows, install [Git for Windows](https://git-scm.com/download/win) first, then restart the app.

**Step 3. Let Claude Code set itself up.** Type this and press Return:

```text
/legal-research:setup
```

Claude Code now walks you through the rest in plain English and does the work itself. It checks that Python is present, asks you to create a free [CourtListener](https://www.courtlistener.com/) account and paste in the token from your profile page (it saves the token to a private file on your computer and tests it against a real case), pre-approves web lookups so a long run never stops to ask, turns on multi-agent workflows (a switch Claude leaves off for Pro plans), and asks whether you use Zotero. Zotero is optional: if you do not use it, say skip and everything else works the same, with articles checked against the open web. It tells you where it put each thing. Nothing here requires you to find a file. If you would rather see exactly what it does first, the instructions it follows are in [`claude-code/skills/setup/SKILL.md`](claude-code/skills/setup/SKILL.md).

**Step 4. Try it.** Start a new session so the settings take effect, open the folder with a short draft (a few pages with footnotes is ideal for a first run), and type:

```text
cite-check this draft
```

The first time, Claude Code asks for approval before it launches the multi-agent run; choose **Always** so it stops asking. Read the "needs your attention" section of the report first.

That is the whole installation. Updates arrive through Claude Code's plugin mechanism; see [Keeping up to date](#keeping-up-to-date). If anything in these four steps did not work as described, please say so at the [issues page](https://github.com/danepps/legal-research-skills/issues) or by email; a confusing instruction is a bug.

### Other ways to install

**Codex: two commands in Terminal.** Open the Terminal app (on a Mac, press Cmd-Space and type "Terminal"), paste these, and press Return:

```sh
codex plugin marketplace add danepps/legal-research-skills
codex plugin add legal-research@danepps-legal-research-codex
```

That installs the `legal-research` plugin, which holds the six Codex skills. Start a new Codex session (restart the desktop app if it was open) and they appear under Plugins as **Legal Research Skills**. The [Codex plugin guide](codex/README.md) has the skill names, updates, and removal. Codex has no setup skill, so give it the CourtListener token one of two ways: if you also have Claude Code, run `/legal-research:setup` there, which writes the token to a file (`~/.config/courtlistener/token`) that the Codex scripts read too; otherwise create that file yourself, or add this line to the end of `~/.zshrc` (Mac) and open a new Terminal window:

```sh
export COURTLISTENER_API_TOKEN="paste-your-token-here"
```

**A script that does the Claude Code and Codex installs for you.** Paste this one line into Terminal. It runs the same plugin commands as above for whichever tools it finds (and, if your Codex is too old for plugins, clones this repository and links its skills in). It never overwrites anything already there.

```sh
curl -fsSL https://danepps.github.io/legal-research-skills/install.sh | sh
```

**By hand.** The details are in the [Install for Claude Code](#install-for-claude-code) and [Install for Codex](#install-for-codex) sections below.

## Keeping up to date

New releases are listed in [CHANGELOG.md](CHANGELOG.md).

- **Claude Code** checks for updates the way it does for any plugin. To have new releases arrive on their own, type `/plugin`, open **Marketplaces**, select **danepps**, and choose **Enable auto-update**. Otherwise type `/plugin marketplace update danepps` whenever you want to check. Nothing changes without a release: you get a new copy only when the version number in the changelog moves.
- **Codex** refreshes the catalog and installs the current version with `codex plugin marketplace upgrade danepps-legal-research-codex` followed by `codex plugin add legal-research@danepps-legal-research-codex`. If you used the installer's plain-copy fallback instead, run the installer line again.

Everything below this line is for readers who want the details. It uses some technical vocabulary; nothing in it is needed to install or use the skills.

---

## Layout

Two parallel implementations live here, one per runtime. They share a design philosophy but are **separate codebases**, not ports of each other.

| Folder | Runtime | How it installs |
|---|---|---|
| [`claude-code/`](claude-code/) | Claude Code (Anthropic) | A plugin named `legal-research`, listed by the marketplace catalog at [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json); Claude Code copies it into its plugin cache |
| [`codex/`](codex/) | Codex CLI (OpenAI) | A plugin named `legal-research`, listed by the catalog at [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json); Codex caches it. Manual symlinks from `~/.agents/skills/` still work |

## What the skills share

The skills differ in detail but follow the same house rules, which came out of real failures on real drafts:

- **Verify against primary sources, not model memory.** Cases are checked against [CourtListener](https://www.courtlistener.com/) and official reporters; scholarship against the user's Zotero library, if there is one, and then the open web. Nothing is reported as verified without saying *on what basis*.
- **Deterministic scripts for structure, models for judgment.** Footnote extraction, `Id.`/`supra` resolution, quote matching, and schema validation are plain Python, so they are repeatable and cannot invent a source. Model agents handle the parts that need reading. (Scripts can still have bugs, and invoking them still costs some context.)
- **Verify the verifier.** Multi-agent runs end with an independent pass over the findings before anything reaches the user, because the first pass produces confident false positives.
- **Limits enforced where a script can enforce them.** Fetch sizes, page counts, and chunk sizes are hard caps in code, and run validators check recorded usage against budgets. Token, browsing, and time limits also depend on what the runtime measures and on the lead agent's supervision.
- **Report for a reader in Word.** Findings carry verbatim find-strings and footnote numbers rather than internal paragraph ids, so each one can be located with Cmd+F.

Passing a validator confirms the structural and workflow requirements it specifies. It does not establish that a model read an authority correctly; the lead agent remains responsible for source support, interpretation, and disclosed limits.

## Claude Code plugin (`claude-code/`)

The folder is a complete Claude Code plugin: a manifest at `.claude-plugin/plugin.json`, six research skills and a setup helper under `skills/`, which load as `/legal-research:<skill>`. The skills reference one another through `${CLAUDE_PLUGIN_ROOT}`, the variable Claude Code substitutes with the plugin's install directory, so they work wherever the plugin is cached and need no fixed path.

| Skill | What it does |
|---|---|
| **legal-research** | Multi-agent legal research that fans out across free legal sources, verifies every authority, and returns a memo. Modes: case law, scholarship, or both. Also the shared toolbox: `check_cite.py` (CourtListener citation lookup), `cl_case_tools.py` (opinion PDFs), `fetch_page.py` (hard-capped fetcher), `citeform.py` (reads italics and small caps out of .docx runs), `md2docx.py` (stdlib Markdown to .docx). |
| **cite-check** | Takes an article draft (.docx with footnotes), extracts every citation and quotation, resolves the cross-reference web, verifies each against the real source, and returns a graded footnote-by-footnote report with a "needs your attention" section first. `DESIGN.md` records the design and the lessons from the first full practice run, including where the cost estimate was wrong and what changed. |
| **proofread** | Prose-only proofreading of a long draft: typos, doubled words, editing residue, and internal consistency (hyphenation, capitalization, defined terms, cross-references). Owns the prose; cite-check owns the authorities. |
| **find-cite** | Quick, verified citation-finding for one proposition. A footnote-filler, not a memo. Prefers Supreme Court cites and flagship-journal scholarship, each with a pincite and a parenthetical, verified before delivery. |
| **build-library** | Builds or extends a Zotero collection of verified sources via the Zotero Web API, then runs a deterministic check (`check_source.py`) that every added item must pass. Includes a whole-library inventory script, because delegating the duplicate check to a subagent produced duplicates. |
| **case-prep** | Gathers the full document set for a Supreme Court case (questions presented, lower-court opinion, cert-stage and merits briefs, SG amicus, argument transcript), crops margins, and loads it onto a reMarkable tablet in a per-case folder. |
| **setup** | One-time, conversational configuration. `setup.py status` reports what is present; its other subcommands save and test the CourtListener token (`~/.config/courtlistener/token`, mode 600), merge `WebFetch`/`WebSearch` into `permissions.allow` and set `enableWorkflows` in `~/.claude/settings.json`, and register a `uvx zotero-mcp` server in `~/.claude.json`. Every write backs up the file first and never removes a key it did not add. |

### Install for Claude Code

Inside a Claude Code session:

```text
/plugin install legal-research --marketplace danepps/legal-research-skills
```

or, on versions before 2.1.275, the two-step form:

```text
/plugin marketplace add danepps/legal-research-skills
/plugin install legal-research@danepps
```

Inside a session the two-step form opens the plugin's details panel, where you choose a scope and confirm; it does not install on its own. The same works from a shell with `claude plugin marketplace add danepps/legal-research-skills` and `claude plugin install legal-research@danepps`. Install at user scope (the default) and the plugin is available in every project. To try the plugin from a clone without installing it, run `claude --plugin-dir ./claude-code` from the repository root. To check what loaded, `claude plugin details legal-research` lists the seven skills.

Updates follow Claude Code's plugin mechanism: `/plugin marketplace update danepps` fetches the catalog and installs a new version when the version in `plugin.json` has changed, and **Enable auto-update** on the marketplace (under `/plugin` > Marketplaces) does that at session start. Releases are versioned in [CHANGELOG.md](CHANGELOG.md).

A plugin installed at user scope serves the Terminal, the desktop app's **Code** tab, and the VS Code extension on that computer, since all three read the same settings ([docs](https://code.claude.com/docs/en/plugins/install)). Two exceptions: the app's Cowork tab takes its plugins from your claude.ai account settings, and cloud sessions at claude.ai/code do not load local plugins.

Runtime notes specific to Claude Code:

- cite-check, proofread, and legal-research use Claude Code's `Workflow` tool (the `.workflow.js` files) for multi-agent fan-out. Dynamic workflows must be enabled: they are on by default for Max, Team, and Enterprise plans and for API access, but **a Pro plan has to turn them on**: `/legal-research:setup` does this (it sets `enableWorkflows` in `~/.claude/settings.json`, the same key the Dynamic workflows row in `/config` writes; [docs](https://code.claude.com/docs/en/workflows)). Each run also asks for approval before it starts; in the desktop app that is an approval card with Once, Always, and Deny.
- Zotero is optional throughout. cite-check and find-cite search a Zotero MCP server when one is configured and otherwise go straight to the web; `/legal-research:setup` registers one on request, and cite-check works out which library a project uses from the `zotero` server entries in `~/.claude.json`. build-library's `check_source.py` reads Zotero credentials from the environment variables above, falling back to that same entry.
- build-library's HeinOnline section assumes an institutional library proxy; replace `<proxy-host>` with yours.
- case-prep assumes a reMarkable MCP server; the download-and-crop steps work without one.

### Quotation check (hook)

The plugin also installs two hooks (`hooks/hooks.json`), active only in a session where one of its six research skills has been invoked (setup does not count). They do nothing in your other sessions.

- After every `WebFetch` or `WebSearch` call, a note is attached to the result saying it is a summary written by a small model and nothing in it is verbatim, so the model fetches the raw text before quoting.
- When the model finishes a turn, `quote_check.py` reads the session transcript and checks every quotation of five or more words in the reply, and in any `.md`, `.txt`, or `.html` file written or edited during that turn, for a verbatim match in raw tool output: results from every tool except `WebFetch` and `WebSearch`, including CourtListener, `Read` and Bash, plus the raw tool output inside the subagent transcripts of `Agent` and `Workflow` runs (a subagent's own summary, a workflow's returned result, a task notification and a message from another session do not count, since a model's repetition of a sentence is not a source); the user's own messages; and files a Bash result points at with "Full output saved to:". A `Read` of a file the model itself wrote this session does not count, and neither does the echo in a `Write` or `Edit` result, so a memo cannot vouch for itself. Matching ignores case, whitespace, curly versus straight quotes, dash variants, HTML entities and tags, and `Read` line numbers; ellipses and bracketed alterations split a quotation into segments that must each match. An unmatched quotation blocks the reply with the list, and the model fetches the source or drops the quotation marks and says it is paraphrasing. The tag `[unverified]` on the same line lets a quotation through when checking is impossible. After two consecutive blocks the reply is allowed with a note on stderr, so a stubborn case cannot loop.

What it does not do: it confirms a quotation matches something retrieved this session, not that the retrieved source is the right one or that the pincite is correct; that is cite-check's job. Only the final turn's reply and written files are checked, and a model that writes a quotation to a file with a shell command rather than `Write` is outside its reach. To turn it off, set `LEGAL_RESEARCH_QUOTE_CHECK=off` in the `env` block of `~/.claude/settings.json`. Tests: `python3 claude-code/hooks/tests/test_quote_check.py`.

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

**Plugin installation (Codex CLI and desktop app):** install all six skills together:

```sh
codex plugin marketplace add danepps/legal-research-skills
codex plugin add legal-research@danepps-legal-research-codex
```

Start a new session, then look for **Legal Research Skills** in Plugins or use
`$legal-research:cite-check`, `$legal-research:legal-research-memo`, and the other
packaged skills. See the [Codex plugin guide](codex/README.md) for all six names,
updates, removal, and requirements. This is a repository marketplace; it does not
imply inclusion in OpenAI's curated directory. Choose the plugin or the manual
installation below to avoid duplicate workflows.

**Manual skill installation (also available for the IDE extension):**

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

In Claude Code, `/legal-research:setup` checks and arranges all of this for you. The table is for Codex users and for anyone who wants to know what is being set where.

| Capability | What you need |
|---|---|
| Script execution | Python 3.11 or newer (the test suite runs on 3.11, 3.12, and 3.13). The scripts use only the standard library and sibling modules in the same skill folder. |
| Current external research | Live web access or an authorized connected source in your runtime. Installing the skills does not supply this; deep-research says so explicitly when it is missing. |
| Checking that a cited case exists | A token from a free [CourtListener](https://www.courtlistener.com/profile/api-token/) account. The scripts in both folders look for it in the environment variable `COURTLISTENER_API_TOKEN`, then `COURTLISTENER_TOKEN`, then the file `~/.config/courtlistener/token`, which is where `/legal-research:setup` puts it. The lookup confirms a citation exists and resolves to the named case; whether it supports the proposition still requires reading it. |
| Zotero (optional; only build-library needs it, the other skills work without it) | An API key and your numeric user id (or a group's id), both from [zotero.org/settings/keys](https://www.zotero.org/settings/keys). For Claude Code, `/legal-research:setup` stores them as the `env` of a `zotero` MCP server entry in `~/.claude.json`, and the scripts read them from there. For Codex, set the environment variables `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` (`user` or `group`); on macOS the Codex scripts also accept a Keychain generic-password entry under the service name `codex-zotero-mcp` (accounts `api-key` and `library-id`). |
| Word output | None beyond Python. Markdown is the canonical deliverable; the .docx helpers write OOXML with the standard library. |
| PDF text extraction | `pdftotext` (poppler) where a helper reads a PDF, such as the memo skill's quantifier audit. Not needed for every task. |
| Several agents working at once | Nothing to install; Claude Code and Codex both provide this. The agent roles and models named in the skill files are preferences, not requirements; each skill falls back to whatever your runtime has and records what it used. |

Your token and keys stay on your own computer, in the places named above. Do not paste them into a GitHub issue, an email, or a shared draft; if one ever leaks, generate a new one on the site that issued it, and the old one stops working.

## Tests

One offline command covers both folders. It runs every `test_*.py` entry point as its own process (including the plugin hook tests under `claude-code/hooks/tests/`) (several are standalone assertion scripts, not `unittest` cases), parses every Python file, checks every relative Markdown link, validates each skill's frontmatter and Codex UI metadata, and checks the plugin manifests (catalog and plugin agree, the changelog's top entry matches the plugin version, no hard-coded skill paths). It needs no credentials or network. `claude plugin validate .` and `claude plugin validate ./claude-code` run Claude Code's own manifest checks.

```sh
python3 run_tests.py
```

The same command runs in GitHub Actions on Python 3.11, 3.12, and 3.13.

## Status

These are working tools, not a product. They are written for a specific workflow (law-review drafts in Word, a Zotero library, free legal sources) and will need adapting elsewhere. Date-stamped notes in the skill files record why a rule exists; they are left in deliberately.

## License

MIT. See [LICENSE](LICENSE).
