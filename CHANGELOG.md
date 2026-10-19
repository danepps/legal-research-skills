# Changelog

Releases of the `legal-research` plugin for Claude Code and the companion Codex skills. Claude Code users receive a release when the version below changes (`/plugin marketplace update danepps`, or automatically if auto-update is on for the `danepps` marketplace). Codex users re-run the installer.

## 1.2.0 (2026-10-19)

- Claude Code: a seventh skill, `/legal-research:setup`, does the configuration in conversation so nobody has to edit a file. It checks Python, asks for the free CourtListener token and saves it to `~/.config/courtlistener/token` after testing it against a live lookup (the Codex scripts read the same file), pre-allows `WebFetch` and `WebSearch`, sets `enableWorkflows` (the Dynamic workflows switch a Pro plan needs), and can register a Zotero MCP server. Its script backs up every file it rewrites and never removes a setting it did not add.
- README: the Getting started section is now four steps done entirely inside the Claude desktop app or Claude Code, with the Terminal, installer-script, and Codex routes moved under "Other ways to install." The prerequisites table says where each credential goes in plain English. Prompted by a reader who found the old instructions assumed too much.

## 1.1.0 (2026-10-19)

- Claude Code: the plugin now carries a quotation check (`claude-code/hooks/`). While one of its skills is in use, every quotation of five or more words in the reply, or in a Markdown or text file written that turn, must match raw tool output from the session verbatim, including text fetched inside Agent and Workflow subagents; WebFetch and WebSearch summaries and the model's own written files do not count. An unmatched quotation blocks the reply until the model fetches the source, drops the quotation marks, or tags the line `[unverified]`. Inactive in sessions that do not use the plugin's skills; `LEGAL_RESEARCH_QUOTE_CHECK=off` disables it. See the README's "Quotation check (hook)" section.

## 1.0.1 (2026-10-18)

- Claude Code: the plugin is now named `legal-research`, the same name as the Codex plugin, so the install command is `/plugin install legal-research --marketplace danepps/legal-research-skills` and skills load as `/legal-research:<skill>`. Anyone who installed `law` earlier today should uninstall it (`/plugin uninstall law@danepps`) and install `legal-research`.

## 1.0.0 (2026-10-18)

First public release.

- Claude Code: `law` plugin (renamed `legal-research` in 1.0.1) with six skills (legal-research, cite-check, proofread, find-cite, build-library, case-prep), installable from the `danepps` marketplace in this repository.
- Codex: six skills (legal-research-memo, cite-check, internal-proofread, find-cite, build-zotero-library, deep-research), installed by the one-line installer.
