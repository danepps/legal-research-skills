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

**Claude Code: one command, typed into Claude Code itself.** Open Claude Code in the Terminal or the desktop app's Code tab, and type:

```text
/plugin install legal-research --marketplace danepps/legal-research-skills
```

That registers this repository as a plugin marketplace and installs the `legal-research` plugin, which holds all six skills. (On a Claude Code older than 2.1.275, type `/plugin marketplace add danepps/legal-research-skills` and then `/plugin install legal-research@danepps`.) Start a new session, or type `/reload-plugins`, and the skills appear in `/` autocomplete as `/legal-research:cite-check`, `/legal-research:proofread`, and so on. You rarely need to type those names: asking "cite-check this draft" in plain English is enough.

**Codex: two commands in Terminal.** Open the Terminal app (on a Mac, press Cmd-Space and type "Terminal"), paste these, and press Return:

```sh
codex plugin marketplace add danepps/legal-research-skills
codex plugin add legal-research@danepps-legal-research-codex
```

That installs the `legal-research` plugin, which holds the six Codex skills. Start a new Codex session (restart the desktop app if it was open) and they appear under Plugins as **Legal Research Skills**. The [Codex plugin guide](codex/README.md) has the skill names, updates, and removal.

**Or let a script do it.** This one line installs for whichever tools it finds on your Mac, running the same plugin commands as above (and, if your Codex is too old for plugins, cloning this repository and linking its skills in):

```sh
curl -fsSL https://danepps.github.io/legal-research-skills/install.sh | sh
```

It never overwrites anything already there. (If the Mac says git is missing, accept its offer to install the command-line tools, then run the line again.)

**By hand.** The details are in the [Install for Claude Code](#install-for-claude-code) and [Install for Codex](#install-for-codex) sections below.

Before or after installing, two short setup steps:

1. **Install one of the two tools, if you haven't.** [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) needs a Claude Pro or Max plan or an Anthropic API key; the [Claude desktop app](https://code.claude.com/docs/en/desktop) includes it under its Code tab. [Codex](https://developers.openai.com/codex) needs a ChatGPT Plus or Pro plan or an OpenAI API key, and comes as a command-line tool or a desktop app.

   **On a Claude Pro plan, one extra switch.** Cite-check, proofread, and legal-research run as multi-agent "dynamic workflows," which Claude turns on by default for Max and Team plans but not for Pro. In Claude Code, type `/config`, find the **Dynamic workflows** row, and turn it on ([docs](https://code.claude.com/docs/en/workflows)). Without it, those three skills will fail at the fan-out step and the other three work normally. A reader hit exactly this, so check it before your first cite-check.
2. **Get a free CourtListener account** and copy an API token from [courtlistener.com/profile/api-token](https://www.courtlistener.com/profile/api-token/). This is how the skills confirm that a case exists. Add this line to the end of the file `~/.zshrc` (Mac) with the token pasted in, then open a new Terminal window or restart the app:

   ```sh
   export COURTLISTENER_API_TOKEN="paste-your-token-here"
   ```

   Optional: if you keep sources in Zotero, create a key at [zotero.org/settings/keys](https://www.zotero.org/settings/keys) and set `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` the same way. Without it, cite-check still works; it just checks articles against the open web only.

Then open the folder with a short draft, in the Terminal or the desktop app, and type "cite-check this draft." Read the "needs your attention" section first.

## Keeping up to date

New releases are listed in [CHANGELOG.md](CHANGELOG.md).

- **Claude Code** checks for updates the way it does for any plugin. To have new releases arrive on their own, type `/plugin`, open **Marketplaces**, select **danepps**, and choose **Enable auto-update**. Otherwise type `/plugin marketplace update danepps` whenever you want to check. Nothing changes without a release: you get a new copy only when the version number in the changelog moves.
- **Codex** refreshes the catalog and installs the current version with `codex plugin marketplace upgrade danepps-legal-research-codex` followed by `codex plugin add legal-research@danepps-legal-research-codex`. If you used the installer's plain-copy fallback instead, run the installer line again.

Everything below this line is for readers who want the details.

---

## Layout

Two parallel implementations live here, one per runtime. They share a design philosophy but are **separate codebases**, not ports of each other.

| Folder | Runtime | How it installs |
|---|---|---|
| [`claude-code/`](claude-code/) | Claude Code (Anthropic) | A plugin named `legal-research`, listed by the marketplace catalog at [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json); Claude Code copies it into its plugin cache |
| [`codex/`](codex/) | Codex CLI (OpenAI) | A plugin named `legal-research`, listed by the catalog at [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json); Codex caches it. Manual symlinks from `~/.agents/skills/` still work |

## What the skills share

The skills differ in detail but follow the same house rules, which came out of real failures on real drafts:

- **Verify against primary sources, not model memory.** Cases are checked against [CourtListener](https://www.courtlistener.com/) and official reporters; scholarship against the user's Zotero library and then the open web. Nothing is reported as verified without saying *on what basis*.
- **Deterministic scripts for structure, models for judgment.** Footnote extraction, `Id.`/`supra` resolution, quote matching, and schema validation are plain Python, so they are repeatable and cannot invent a source. Model agents handle the parts that need reading. (Scripts can still have bugs, and invoking them still costs some context.)
- **Verify the verifier.** Multi-agent runs end with an independent pass over the findings before anything reaches the user, because the first pass produces confident false positives.
- **Limits enforced where a script can enforce them.** Fetch sizes, page counts, and chunk sizes are hard caps in code, and run validators check recorded usage against budgets. Token, browsing, and time limits also depend on what the runtime measures and on the lead agent's supervision.
- **Report for a reader in Word.** Findings carry verbatim find-strings and footnote numbers rather than internal paragraph ids, so each one can be located with Cmd+F.

Passing a validator confirms the structural and workflow requirements it specifies. It does not establish that a model read an authority correctly; the lead agent remains responsible for source support, interpretation, and disclosed limits.

## Claude Code plugin (`claude-code/`)

The folder is a complete Claude Code plugin: a manifest at `.claude-plugin/plugin.json` and six skills under `skills/`, which load as `/legal-research:<skill>`. The skills reference one another through `${CLAUDE_PLUGIN_ROOT}`, the variable Claude Code substitutes with the plugin's install directory, so they work wherever the plugin is cached and need no fixed path.

| Skill | What it does |
|---|---|
| **legal-research** | Multi-agent legal research that fans out across free legal sources, verifies every authority, and returns a memo. Modes: case law, scholarship, or both. Also the shared toolbox: `check_cite.py` (CourtListener citation lookup), `cl_case_tools.py` (opinion PDFs), `fetch_page.py` (hard-capped fetcher), `citeform.py` (reads italics and small caps out of .docx runs), `md2docx.py` (stdlib Markdown to .docx). |
| **cite-check** | Takes an article draft (.docx with footnotes), extracts every citation and quotation, resolves the cross-reference web, verifies each against the real source, and returns a graded footnote-by-footnote report with a "needs your attention" section first. `DESIGN.md` records the design and the lessons from the first full practice run, including where the cost estimate was wrong and what changed. |
| **proofread** | Prose-only proofreading of a long draft: typos, doubled words, editing residue, and internal consistency (hyphenation, capitalization, defined terms, cross-references). Owns the prose; cite-check owns the authorities. |
| **find-cite** | Quick, verified citation-finding for one proposition. A footnote-filler, not a memo. Prefers Supreme Court cites and flagship-journal scholarship, each with a pincite and a parenthetical, verified before delivery. |
| **build-library** | Builds or extends a Zotero collection of verified sources via the Zotero Web API, then runs a deterministic check (`check_source.py`) that every added item must pass. Includes a whole-library inventory script, because delegating the duplicate check to a subagent produced duplicates. |
| **case-prep** | Gathers the full document set for a Supreme Court case (questions presented, lower-court opinion, cert-stage and merits briefs, SG amicus, argument transcript), crops margins, and loads it onto a reMarkable tablet in a per-case folder. |

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

The same works from a shell with `claude plugin marketplace add danepps/legal-research-skills` and `claude plugin install legal-research@danepps`. Install at user scope (the default) and the plugin is available in every project. To try the plugin from a clone without installing it, run `claude --plugin-dir ./claude-code` from the repository root. To check what loaded, `claude plugin details legal-research` lists the six skills.

Updates follow Claude Code's plugin mechanism: `/plugin marketplace update danepps` fetches the catalog and installs a new version when the version in `plugin.json` has changed, and **Enable auto-update** on the marketplace (under `/plugin` > Marketplaces) does that at session start. Releases are versioned in [CHANGELOG.md](CHANGELOG.md).

A plugin installed at user scope serves the Terminal, the desktop app's **Code** tab, and the VS Code extension on that computer, since all three read the same settings ([docs](https://code.claude.com/docs/en/plugins/install)). Two exceptions: the app's Cowork tab takes its plugins from your claude.ai account settings, and cloud sessions at claude.ai/code do not load local plugins.

Runtime notes specific to Claude Code:

- cite-check, proofread, and legal-research use Claude Code's `Workflow` tool (the `.workflow.js` files) for multi-agent fan-out. Dynamic workflows must be enabled: they are on by default for Max, Team, and Enterprise plans and for API access, but **a Pro plan has to turn them on from the Dynamic workflows row in `/config`** ([docs](https://code.claude.com/docs/en/workflows)). Each run also asks for approval before it starts; in the desktop app that is an approval card with Once, Always, and Deny.
- cite-check and find-cite assume a Zotero MCP server for library search; cite-check works out which library a project uses from the `zotero` server entries in `~/.claude.json`. build-library's `check_source.py` reads Zotero credentials from the environment variables above, falling back to that same entry.
- build-library's HeinOnline section assumes an institutional library proxy; replace `<proxy-host>` with yours.
- case-prep assumes a reMarkable MCP server; the download-and-crop steps work without one.

### Quotation check (hook)

The plugin also installs two hooks (`hooks/hooks.json`), active only in a session where one of its six skills has been invoked. They do nothing in your other sessions.

- After every `WebFetch` or `WebSearch` call, a note is attached to the result saying it is a summary written by a small model and nothing in it is verbatim, so the model fetches the raw text before quoting.
- When the model finishes a turn, `quote_check.py` reads the session transcript and checks every quotation of five or more words in the reply, and in any `.md`, `.txt`, or `.html` file written or edited during that turn, for a verbatim match in raw tool output: results from every tool except `WebFetch` and `WebSearch`, including CourtListener, `Read`, Bash, and the subagent transcripts of `Agent` and `Workflow` runs; the user's own messages; and files a Bash result points at with "Full output saved to:". A `Read` of a file the model itself wrote this session does not count, and neither does the echo in a `Write` or `Edit` result, so a memo cannot vouch for itself. Matching ignores case, whitespace, curly versus straight quotes, dash variants, HTML entities and tags, and `Read` line numbers; ellipses and bracketed alterations split a quotation into segments that must each match. An unmatched quotation blocks the reply with the list, and the model fetches the source or drops the quotation marks and says it is paraphrasing. The tag `[unverified]` on the same line lets a quotation through when checking is impossible. After two consecutive blocks the reply is allowed with a note on stderr, so a stubborn case cannot loop.

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

One offline command covers both folders. It runs every `test_*.py` entry point as its own process (including the plugin hook tests under `claude-code/hooks/tests/`) (several are standalone assertion scripts, not `unittest` cases), parses every Python file, checks every relative Markdown link, validates each skill's frontmatter and Codex UI metadata, and checks the plugin manifests (catalog and plugin agree, the changelog's top entry matches the plugin version, no hard-coded skill paths). It needs no credentials or network. `claude plugin validate .` and `claude plugin validate ./claude-code` run Claude Code's own manifest checks.

```sh
python3 run_tests.py
```

The same command runs in GitHub Actions on Python 3.11, 3.12, and 3.13.

## Status

These are working tools, not a product. They are written for a specific workflow (law-review drafts in Word, a Zotero library, free legal sources) and will need adapting elsewhere. Date-stamped notes in the skill files record why a rule exists; they are left in deliberately.

## License

MIT. See [LICENSE](LICENSE).
