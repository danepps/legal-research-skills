# Changelog

Releases of the `legal-research` plugin for Claude Code and the companion Codex skills. Claude Code users receive a release when the version below changes (`/plugin marketplace update danepps`, or automatically if auto-update is on for the `danepps` marketplace). Codex users re-run the installer.

## 1.0.1 (2026-10-18)

- Claude Code: the plugin is now named `legal-research`, the same name as the Codex plugin, so the install command is `/plugin install legal-research --marketplace danepps/legal-research-skills` and skills load as `/legal-research:<skill>`. Anyone who installed `law` earlier today should uninstall it (`/plugin uninstall law@danepps`) and install `legal-research`.

## 1.0.0 (2026-10-18)

First public release.

- Claude Code: `law` plugin (renamed `legal-research` in 1.0.1) with six skills (legal-research, cite-check, proofread, find-cite, build-library, case-prep), installable from the `danepps` marketplace in this repository.
- Codex: six skills (legal-research-memo, cite-check, internal-proofread, find-cite, build-zotero-library, deep-research), installed by the one-line installer.
