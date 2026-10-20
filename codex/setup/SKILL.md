---
name: setup
description: Set up, inspect, disable, or troubleshoot optional automatic updates for the Legal Research Skills Codex plugin. Use for this plugin's setup and update requests, not research tasks or Claude configuration.
---

# Legal Research setup

Manage optional daily updates for this Codex plugin. The helper uses the native
Codex plugin manager and a per-user OS schedule. It does not configure research
credentials. For CourtListener or Zotero setup, use the relevant research skill's
configuration instructions.

Resolve `scripts/auto_update.py` relative to this skill directory and use Python
3.11 or newer. Run `status` first; explain the result briefly rather than showing
raw JSON. Status does not enable updates or create a schedule.

```sh
python3 <skill-directory>/scripts/auto_update.py status
```

For a general setup request, offer automatic updates as optional: checks run
daily while the user is logged in, even when Codex is closed, and fetch new
releases from `danepps/legal-research-skills`. If the user already asked to enable
automatic updates, proceed without asking again. Otherwise wait for opt-in
before running `enable`. Skipping leaves the research skills usable.

```sh
python3 <skill-directory>/scripts/auto_update.py enable
python3 <skill-directory>/scripts/auto_update.py status
```

Only report activation when `enabled` and `schedule_registered` are both true
and there is no `scheduler_error`. On failure, explain the concrete error and
retain manual updates. Do not use administrator privileges, install a different
scheduler, edit a plugin cache, or switch the user's marketplace source to make
setup succeed. The helper supports macOS launchd, Linux user systemd, and Windows
Task Scheduler; it requires the native plugin from the official, unpinned GitHub
marketplace. Manual skill copies and local development marketplaces are excluded.

When the user requests an immediate update and automatic updates are enabled:

```sh
python3 <skill-directory>/scripts/auto_update.py run --force
```

When automatic updates are off, an immediate update uses the normal commands;
it does not authorize creating a schedule:

```sh
codex plugin marketplace upgrade danepps-legal-research-codex
codex plugin add legal-research@danepps-legal-research-codex
```

Run the second command only if the first succeeds. Read the installed version
back with `codex plugin list --marketplace danepps-legal-research-codex --json`.
Say to start a new Codex session to use the updated skills.

To disable automatic updates, run `disable`, then `status`. Research files and
the installed plugin remain intact. If disabling fails, distinguish the disabled
updater configuration from a scheduler job that still needs removal.

```sh
python3 <skill-directory>/scripts/auto_update.py disable
```

The stable helper also lives at `${CODEX_HOME:-~/.codex}/legal-research-updater/auto_update.py`.
It remains available after plugin removal so the schedule can be removed.
For status fields, platform requirements, and recovery, read
[the update guide](references/automatic-updates.md).
