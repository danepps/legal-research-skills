# Legal Research Skills for Codex

Install all six Codex research skills and an optional update setup helper as one plugin. The package contains the
same maintained skill folders used by the manual installer. It does not install
the Claude skills or configure external accounts.

## Install

In a terminal with a current Codex CLI:

```sh
codex plugin marketplace add danepps/legal-research-skills
codex plugin add legal-research@danepps-legal-research-codex
```

Start a new Codex session after installation. In the desktop app, restart or
refresh the app, open Plugins, and look for **Legal Research Skills** under
**Daniel Epps: Codex Research Skills**. In the CLI, `/plugins` opens the plugin
browser. If `codex plugin` is unavailable, update the Codex CLI first.

This installs from the repository's marketplace. It is not a listing in
OpenAI's curated public directory.

The plugin's skill names are:

| Skill | Explicit invocation |
|---|---|
| Legal research memos | `$legal-research:legal-research-memo` |
| Citation checking | `$legal-research:cite-check` |
| Citation finding | `$legal-research:find-cite` |
| Internal proofreading | `$legal-research:internal-proofread` |
| Zotero library building | `$legal-research:build-zotero-library` |
| Deep research | `$legal-research:deep-research` |
| Automatic update setup | `$legal-research:setup` |

You can also ask in plain English, such as "Cite-check this draft" or "Write a
research memo on this question." Start with a short document to check your setup.

Use either the plugin or manually installed copies of these skills. Existing
manual installations remain valid; the plugin installer does not remove them.
Keeping both can expose duplicate workflows. Remove a manual link only after
confirming that it points to this repository and that you no longer need it.

## Requirements

- Python 3.11 or newer for the included scripts.
- Local file and command access in Codex.
- Live web access or an authorized connected source for current external research.
- Your own credentials for optional case-lookup and Zotero operations; see the
  [configuration table](https://github.com/danepps/legal-research-skills#prerequisites-and-configuration).
- Available subagents for workflows that require independent parallel review.

Installing the plugin adds instructions and helper scripts. It does not supply
database subscriptions, external accounts, or model access. Markdown is the
canonical memo format; requested derivatives have their own requirements in the
relevant skill. Authenticated source files must be supplied by the user.

## Updates and removal

For optional automatic updates, start a Codex session and say:

> Use $legal-research:setup to enable automatic updates.

This installs a per-user schedule on macOS, Linux with systemd, or Windows. It
checks for updates daily while you are logged in, including when Codex is closed.
Automatic updates are off until you enable them. Start a new Codex session to use
an updated plugin. Ask the same setup skill to show status, check now, or disable
automatic updates. See [automatic updates](setup/references/automatic-updates.md)
for requirements, failure behavior, and removal after the plugin is uninstalled.

For manual updates, use these commands in order, stopping if the refresh fails.
Refresh the repository marketplace and install its current plugin version:

```sh
codex plugin marketplace upgrade danepps-legal-research-codex
codex plugin add legal-research@danepps-legal-research-codex
```

Then start a new session. Before removing the plugin, ask `$legal-research:setup`
to disable automatic updates if you enabled them. Then remove the plugin:

```sh
codex plugin remove legal-research@danepps-legal-research-codex
```

Removing the plugin does not remove research documents or separately installed
manual skill copies. To stop tracking the marketplace as well:

```sh
codex plugin marketplace remove danepps-legal-research-codex
```

## Maintainer notes

The Codex package root is `codex/`. Its supported Codex-format manifest is
[.codex-plugin/plugin.json](.codex-plugin/plugin.json), which explicitly lists
the seven relative skill directories (six research skills and setup). This preserves existing manual installation
paths and avoids maintaining duplicate skill copies. The repository catalog is
[.agents/plugins/marketplace.json](https://github.com/danepps/legal-research-skills/blob/main/.agents/plugins/marketplace.json); its source
points only to `./codex`.

The package includes its [MIT license](LICENSE). Increment the plugin's semantic version when releasing changes. Run
`python3 run_tests.py` from the repository root before publishing; this includes
the offline packaging checks in `test_codex_plugin.py`. The package adds no MCP
servers, lifecycle hooks, credential files, or browser companion. The optional
updater uses the operating system scheduler only after explicit setup.

Codex-specific changes are recorded in [CHANGELOG.md](CHANGELOG.md). Claude
releases retain their independent version and changelog at the repository root.

For a checkout that has not been pushed yet, test discovery by adding that
checkout as a local marketplace:

```sh
codex plugin marketplace add /absolute/path/to/legal-research-skills
codex plugin list --marketplace danepps-legal-research-codex --available --json
```

Use one source for this marketplace name at a time. The GitHub installation
commands require the plugin and catalog to be committed and pushed first.

See OpenAI's [plugin packaging documentation](https://developers.openai.com/plugins/build/plugins)
and [CLI plugin reference](https://learn.chatgpt.com/docs/cli/reference#codex-plugin).
