# Note for Codex: up-front dialog follow-ups on the Claude side

Date: 2026-10-30
Author: Claude (Claude Code side), on branch `cite-check-proposition-support` (PR #1)
For: Codex, and Daniel Epps
Subject: what changed in the Claude Code cite-check dialog and Zotero detection after a dry run on 2026-10-30, and what may be worth carrying to the Codex skill

## 1. How this came up

Dan asked for a dry run of the Claude step-1b dialog (built in `8e5159b`). It was run in a session with three Zotero libraries registered (personal, Federal Criminal Common Law, 5A General Law) and no `Zotero library:` line recorded. The dialog rendered as one interaction with Depth, Support and Zotero, and the Zotero question used exactly the four-option maximum. The free-text matcher was then tried on four typed answers. Three behaved as intended. The fourth, `5A`, matched nothing. Two gaps also came out of the review: the Claude dialog had no Coverage question (the Codex picker already has one), and Zotero detection read only one of Claude Code's three config scopes.

## 2. What changed (Claude side only)

| Area | Change | Files |
|---|---|---|
| Coverage question | New first question in step 1b: whole draft, sample (footnotes 1–10), or specific footnotes typed in the Other box. These are the same three choices as `codex/cite-check/references/run-picker.md`. A sample or specific answer becomes the existing partial pass (`prepare_units.py --footnotes`). The question is dropped when the request names a range, or when the tracked-changes question needs the fourth slot (the tool allows four questions per call). Headless default: whole draft. | `claude-code/skills/cite-check/SKILL.md` |
| Config scopes | `zotero_servers.py` and `zotero_lookup.py` now read MCP servers from user scope (`~/.claude.json` `mcpServers`), project scope (`<project>/.mcp.json`) and local scope (`~/.claude.json` `projects.<path>.mcpServers`). On a name clash the later scope wins, as in Claude Code. A new `--project DIR` flag defaults to the current directory. `zotero_lookup.py` imports `server_entries` from `zotero_servers.py` (and degrades to user scope if the import fails), so a library the dialog offers always resolves at lookup time. | `claude-code/skills/legal-research/zotero_servers.py`, `claude-code/skills/cite-check/scripts/zotero_lookup.py` |
| Unusable servers | A server that looks like Zotero (name, command, args or a `ZOTERO_*` env key) but has no Web API key and library id is listed by `--text` as `NOT USABLE`, with the missing fields and whether it uses the desktop local API. It is never offered as an option. The run says once, before launch and again at deliver, that the library exists but cannot be searched until `/legal-research:setup` adds a key. Before this change, such a server was silently treated as no Zotero at all. | same, plus SKILL.md |
| Matcher | A token under three characters now counts when it contains a digit (`5A`, `2L`). Other short words are still dropped. | `zotero_servers.py` `words()` |
| Option text | The `No Zotero this run` option now has a description in the SKILL.md table, so runs stop improvising one. | SKILL.md |

Tests: new checks in `test_zotero_servers.py` (digit token, project and local scopes, the unusable report, no false positives on non-Zotero servers) and `test_zotero_lookup.py` (a project `.mcp.json` server resolves; local scope beats user scope). Offline suite: 45 of 45 test programs pass, along with compile, link, frontmatter and manifest checks. Checked by hand against the real config (three libraries listed, `5A` resolves), against a temporary home with only a key-less local-API server (reported as not usable), and against an empty home (no server registered).

Not yet done: a live cite-check run through the full dialog. The Coverage question has only been checked as SKILL.md text, not rendered.

## 3. What may be worth porting to Codex

1. **Coverage parity is now in place**, and the option sets match. Two differences remain. Codex offers the picker only above a size threshold (30 notes, 20 quotes or 10 uncached sources, unless `--ask`). Claude always asks, because it has no footnote count before the dialog. If Codex thinks the threshold is the better design, the Claude side could add a cheap footnote count ahead of step 1b.
2. **Zotero in the Codex picker.** The Codex cite-check picker has no library question, and its source bundle carries `zotero_item_key` and `source_path`, but nothing selects a library up front. If Codex runs read Zotero, the same three lessons apply: list libraries by their real names, report a configured but unusable library instead of going web-only without a word, and match typed descriptions with short digit-bearing tokens kept.
3. **Config scope.** Any Codex script that reads credentials from a single config location has the same blind spot for per-project setups. This is worth a check on the Codex side, for example in `build-zotero-library/scripts/zotero_api.py`.

## 4. Open idea for both sides: a local PDF folder as a source

Neither skill can read sources from a folder of PDFs the author already has. Subscription-only material (HeinOnline, JSTOR, Westlaw) and script-blocked repositories (SSRN, bepress) end as unverifiable even when the PDF is on disk. On the Claude side, the proposal is a deterministic pre-launch matcher modeled on `zotero_lookup.py`: match each cited article or book to a PDF in a named folder by title and author (file name and PDF metadata), extract the text, and hand agents the text on disk. It would surface as a fourth choice in the source question, and as the only choice for users without Zotero. The Codex `source_path` field suggests the Codex bundle could take the same input. Not built; Dan has not yet decided whether it starts as a design note.
