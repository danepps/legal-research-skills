# Technical reference

[Back to the getting-started guide](README.md#getting-started)

This page is for readers who already use a terminal, anyone helping someone with setup, and contributors. For the desktop walkthrough, use the [main guide](README.md#set-up-with-claude-desktop).

## Install with the helper script

If you already have Claude Code or the Codex CLI installed, this script runs the plugin installation commands for whichever tools it finds. For older Codex versions without plugin support, it clones this repository and links its skills. It preserves existing manual skill folders; rerunning it can update an existing plugin installation.

Run this in your terminal:

```sh
curl -fsSL https://danepps.github.io/legal-research-skills/install.sh | sh
```

For individual commands, see [Install for Claude Code](#install-for-claude-code) or [Install for Codex](#install-for-codex).

## Updating Codex manually

Run these commands in order, stopping if the first command fails:

```sh
codex plugin marketplace upgrade danepps-legal-research-codex
codex plugin add legal-research@danepps-legal-research-codex
```

Start a new Codex conversation afterward. If you used the installer's manual fallback, rerun the installer instead. For optional daily updates, use the [automatic update guide](https://github.com/danepps/legal-research-skills/blob/main/codex/setup/references/automatic-updates.md).

## Layout

Two parallel implementations live here, one per runtime. They share a design philosophy but are **separate codebases**, not ports of each other.

| Folder | Runtime | How it installs |
|---|---|---|
| [`claude-code/`](https://github.com/danepps/legal-research-skills/tree/main/claude-code) | Claude Code (Anthropic) | A plugin named `legal-research`, listed by the marketplace catalog at [`.claude-plugin/marketplace.json`](https://github.com/danepps/legal-research-skills/blob/main/.claude-plugin/marketplace.json); Claude Code copies it into its plugin cache |
| [`codex/`](https://github.com/danepps/legal-research-skills/tree/main/codex) | Codex CLI (OpenAI) | A plugin named `legal-research`, listed by the catalog at [`.agents/plugins/marketplace.json`](https://github.com/danepps/legal-research-skills/blob/main/.agents/plugins/marketplace.json); Codex caches it. Manual symlinks from `~/.agents/skills/` still work |

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
| **legal-research** | Multi-agent legal research that fans out across free legal sources, verifies every authority, and returns a memo. Modes: case law, scholarship, or both. Also the shared toolbox: `check_cite.py` (CourtListener citation lookup), `cl_case_tools.py` (`citing`: citing opinions by citation graph and name search, deduplicated, with treatment-language triage; `history`: docket entries after the decision and later same-litigation opinions; `find`: resolve a case by caption or by opinions citing its citation string when the reporter cite will not resolve; `pdf`: opinion PDFs), `fetch_page.py` (hard-capped fetcher), `citeform.py` (reads italics and small caps out of .docx runs), `md2docx.py` (stdlib Markdown to .docx). |
| **cite-check** | Takes an article draft (.docx with footnotes), extracts every citation and quotation, resolves the cross-reference web, verifies each against the real source, and returns a graded footnote-by-footnote report with a "needs your attention" section first, an advisory subsequent-history and treatment section (RECAP docket entries after the decision plus later same-litigation opinions for lower-court cases; a two-route citing probe for every case), and, on a re-run, a "since the last report" diff (`scripts/findings_diff.py`, keyed by content rather than footnote number). An opt-in support pass (`support:true`) reads each unquoted cite at its pincite and reports, through the cite's signal, whether it supports the sentence it hangs on; overstatement is a confirm item, never an error. `DESIGN.md` records the design and the lessons from the first full practice run, including where the cost estimate was wrong and what changed. |
| **proofread** | Prose-only proofreading of a long draft: typos, doubled words, editing residue, and internal consistency (hyphenation, capitalization, defined terms, cross-references). Owns the prose; cite-check owns the authorities. |
| **find-cite** | Quick, verified citation-finding for one proposition. A footnote-filler, not a memo. Prefers Supreme Court cites and flagship-journal scholarship, each with a pincite and a parenthetical, verified before delivery. |
| **build-library** | Builds or extends a Zotero collection of verified sources via the Zotero Web API, then runs a deterministic check (`check_source.py`) that every added item must pass. Includes a whole-library inventory script, because delegating the duplicate check to a subagent produced duplicates. |
| **case-prep** | Gathers the full document set for a Supreme Court case (questions presented, lower-court opinion, cert-stage and merits briefs, SG amicus, argument transcript), crops margins, and loads it onto a reMarkable tablet in a per-case folder. |
| **setup** | One-time, conversational configuration. `setup.py status` reports what is present; its other subcommands save and test the CourtListener token (`~/.config/courtlistener/token`, mode 600), merge `WebFetch`/`WebSearch` into `permissions.allow`, set `enableWorkflows`, and set `autoUpdate` on the `danepps` entry of `extraKnownMarketplaces` in `~/.claude/settings.json` (the documented switch that `/plugin`'s Enable auto-update writes; `auto-update status` reads it back together with the `DISABLE_AUTOUPDATER`-style variables that switch the whole update pass off), and register a `uvx zotero-mcp` server in `~/.claude.json`. Every write backs up the file first and never removes a key it did not add. |

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

Updates follow Claude Code's plugin mechanism: `/plugin marketplace update danepps` fetches the catalog and installs a new version when the version in `plugin.json` has changed, and **Enable auto-update** on the marketplace (under `/plugin` > Marketplaces, or `/legal-research:setup`, which writes the same `autoUpdate` field) does that at session start. Releases are versioned in [CHANGELOG.md](CHANGELOG.md).

A plugin installed at user scope serves the Terminal, the desktop app's **Code** tab, and the VS Code extension on that computer, since all three read the same settings ([docs](https://code.claude.com/docs/en/plugins/install)). Two exceptions: the app's Cowork tab takes its plugins from your claude.ai account settings, and cloud sessions at claude.ai/code do not load local plugins.

Runtime notes specific to Claude Code:

- cite-check, proofread, and legal-research use Claude Code's `Workflow` tool (the `.workflow.js` files) for multi-agent fan-out. Dynamic workflows must be enabled: they are on by default for Max, Team, and Enterprise plans and for API access, but **a Pro plan has to turn them on**: `/legal-research:setup` does this (it sets `enableWorkflows` in `~/.claude/settings.json`, the same key the Dynamic workflows row in `/config` writes; [docs](https://code.claude.com/docs/en/workflows)). Each run also asks for approval before it starts; in the desktop app that is an approval card with Once, Always, and Deny.
- Zotero is optional throughout. cite-check and find-cite search a Zotero MCP server when one is configured and otherwise go straight to the web; `/legal-research:setup` registers one on request, and cite-check works out which library a project uses from the `zotero` server entries in `~/.claude.json`. build-library's `check_source.py` reads Zotero credentials from the environment variables in the configuration table below, falling back to that same entry.
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
| **legal-research-memo** | Verified legal or scholarly memos: doctrinal synthesis, historical research, literature reviews, resumable investigations. Authority tables disclose validation tiers. Case tools perform reporter-identity fallback searches and bounded two-route treatment triage with deduplicated decision counts. References cover source protocol, subagent orchestration, autonomous runs, and a review checklist. |
| **cite-check** | Verifies citations, quotations, pincites, proposition support, cross-references, source versions, and URLs in a draft, with schema-v6 case-history/treatment coverage, a separate advisory section, content-keyed re-run findings, actual-speaker attribution and existence-only instance counts. Earlier schemas remain readable; working JSON stays hidden. |
| **internal-proofread** | Proofreads long drafts for internal textual defects using deterministic whole-document checks, bounded subagent review, independent recall and verification passes, and machine-enforced completion gates. Comparison against an externally supplied "challenger" report is optional. |
| **find-cite** | A small set of verified, footnote-ready authorities for one proposition, delivered as a validated evidence packet. |
| **build-zotero-library** | Builds or extends a verified Zotero collection, including full-text PDFs. Open-access PDFs are fetched directly; anything behind a paywall or login is attached from a file the user downloads, with provenance recorded. Nothing automates institutional access. |
| **deep-research** | A resumable, source-grounded investigation runner for the CLI, with cost controls and anti-spiral rules. General-purpose rather than legal, but used by the legal skills. |

### Install for Codex

**Desktop installation without the CLI:** download the repository ZIP, open the extracted outer folder as a local Codex project, and install from its marketplace in Plugins. See the [desktop walkthrough](README.md#set-up-with-codex). This route uses the included catalog and needs no terminal commands; updates to the downloaded copy are manual.

**Command-line alternative:** the commands below require a current Codex CLI. If `codex` is not recognized, use the desktop route above or follow the [Codex CLI installation guide](https://learn.chatgpt.com/docs/cli). To install the six research skills and update setup helper through the CLI:

```sh
codex plugin marketplace add danepps/legal-research-skills
codex plugin add legal-research@danepps-legal-research-codex
```

Start a new session, then look for **Legal Research Skills** in Plugins or use
`$legal-research:cite-check`, `$legal-research:legal-research-memo`, and the other
packaged skills. See the [Codex plugin guide](https://github.com/danepps/legal-research-skills/blob/main/codex/README.md) for the skill names,
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

In Claude Code, `/legal-research:setup` checks and arranges all of this for you; its [setup instructions](https://github.com/danepps/legal-research-skills/blob/main/claude-code/skills/setup/SKILL.md) explain each step. The table is for Codex users and for anyone who wants to know what is being set where. The Codex setup helper handles automatic updates only; it does not configure CourtListener or Zotero. For CourtListener, the shared token file listed below works for both plugins. A token already saved by Claude setup can be reused without running setup again.

| Capability | What you need |
|---|---|
| Script execution | Python 3.11 or newer (the test suite runs on 3.11, 3.12, and 3.13). The scripts use only the standard library and sibling modules in the same skill folder. |
| Current external research | Live web access or an authorized connected source in your runtime. Installing the skills does not supply this; deep-research says so explicitly when it is missing. |
| Checking that a cited case exists | A token from a free [CourtListener](https://www.courtlistener.com/profile/api-token/) account. The scripts in both folders look for it in the environment variable `COURTLISTENER_API_TOKEN`, then `COURTLISTENER_TOKEN`, then the file `~/.config/courtlistener/token`, which is where `/legal-research:setup` puts it. The lookup confirms a citation exists and resolves to the named case; whether it supports the proposition requires reading it, which cite-check does only in its opt-in support pass. |
| Zotero (optional; only build-library needs it, the other skills work without it) | An API key and your numeric user id (or a group's id), both from [zotero.org/settings/keys](https://www.zotero.org/settings/keys). For Claude Code, `/legal-research:setup` stores them as the `env` of a `zotero` MCP server entry in `~/.claude.json`, and the scripts read them from there. For Codex, set the environment variables `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` (`user` or `group`); on macOS the Codex scripts also accept a Keychain generic-password entry under the service name `codex-zotero-mcp` (accounts `api-key` and `library-id`). |
| Word output | None beyond Python. Markdown is the canonical deliverable; the .docx helpers write OOXML with the standard library. |
| PDF text extraction | `pdftotext` (poppler) where a helper reads a PDF, such as the memo skill's quantifier audit. Not needed for every task. |
| Several agents working at once | Nothing to install; Claude Code and Codex both provide this. The agent roles and models named in the skill files are preferences, not requirements; each skill falls back to whatever your runtime has and records what it used. |

Saved credential files stay on your computer, in the places named above. If you paste a token or key into an AI conversation during setup, that copy also remains in the conversation history. Do not paste them into a GitHub issue, an email, or a shared draft; if one ever leaks, generate a new one on the site that issued it, and the old one stops working.

## Tests

One offline command covers both folders. It runs every `test_*.py` entry point as its own process (including the plugin hook tests under `claude-code/hooks/tests/`) (several are standalone assertion scripts, not `unittest` cases), parses every Python file, checks every relative Markdown link, validates each skill's frontmatter and Codex UI metadata, and checks the plugin manifests (catalog and plugin agree, the changelog's top entry matches the plugin version, no hard-coded skill paths). It needs no credentials or network. `claude plugin validate .` and `claude plugin validate ./claude-code` run Claude Code's own manifest checks.

```sh
python3 run_tests.py
```

The same command runs in GitHub Actions on Python 3.11, 3.12, and 3.13.

## Status

These are working tools, not a product. They are written for a specific workflow (law-review drafts in Word, a Zotero library, free legal sources) and will need adapting elsewhere. Date-stamped notes in the skill files record why a rule exists; they are left in deliberately.

## License

MIT. See [LICENSE](https://github.com/danepps/legal-research-skills/blob/main/LICENSE).
