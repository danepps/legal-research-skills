# Automatic updates

Automatic updates are optional and off until the user enables them. Run
`$legal-research:setup` in Codex and ask to enable automatic updates. This adds a
per-user schedule, without administrator access or a plugin startup hook.

The computer must be awake, online, and logged into the user's OS account to
fetch updates. Codex itself can be closed. On Linux, a functioning systemd user
manager is required; containers and WSL installations without one use manual
updates. Windows uses the current user's interactive login and stores no
password. The Codex CLI and Python 3.11+ must remain installed.

The scheduler wakes the helper hourly. The helper attempts a network refresh
at most once every 24 hours, including after a failed attempt. An explicit
`run --force` retries immediately. Sleeping or signing out postpones checks;
there is no guarantee of a particular update time. Start a new Codex session
after an update so it loads the new skills.

## What gets installed

The durable helper, configuration, lock file, and last result live in
`$CODEX_HOME/legal-research-updater/`, or `~/.codex/legal-research-updater/` when
`CODEX_HOME` is unset. The configuration saves the selected Codex home, executable
paths, and PATH, not API tokens or passwords. Run setup in the same Codex home
that holds the plugin. Re-run setup if Python or Codex moves. Re-enabling from
the current plugin also refreshes the durable helper.

The job name begins `org.danepps.legal-research-codex.` and ends in a hash of the
updater directory. Scheduling uses:

| Platform | Per-user schedule |
|---|---|
| macOS | A plist in `~/Library/LaunchAgents/`, loaded with launchctl |
| Linux | A service and timer in `$XDG_CONFIG_HOME/systemd/user/` (normally `~/.config/systemd/user/`) |
| Windows | A Task Scheduler task using the current user's login |

Each check reads the installed plugin state, verifies the official unpinned
GitHub marketplace, refreshes that marketplace, installs its current plugin,
and reads back the version. It never deliberately reinstalls a removed plugin
or re-enables a disabled one. Stop the updater before removing the plugin or
changing marketplace settings; that also avoids a race with a check already
in progress. A failed refresh stops before the explicit install command.
Codex's own refresh may already change plugin files; the helper does not provide
transactional rollback of the native plugin manager.

## Status and removal

Ask `$legal-research:setup` to show status, check for updates now, or disable
automatic updates. Alternatively, with the default Codex home:

```sh
python3 ~/.codex/legal-research-updater/auto_update.py status
python3 ~/.codex/legal-research-updater/auto_update.py run --force
python3 ~/.codex/legal-research-updater/auto_update.py disable
```

Use the actual Codex home when customized. On Windows, use `python` and the
equivalent path under your user profile. `status` reports whether updates are
enabled, whether the scheduler confirms registration, and the latest attempt.
`updated` and `up_to_date` require a successful installed-version readback;
`failed` includes the error, and `skipped` means the plugin was removed or
disabled. `not_due` means the daily interval has not elapsed.

Disable the updater before `codex plugin remove`. Disabling removes its scheduled
job and generated scheduler files, retaining the helper and last result so
failures can be diagnosed. It does not remove the plugin or research documents.
Removing the plugin alone does not unregister the OS schedule: subsequent checks
skip the missing plugin. The retained helper can still disable the schedule.

If scheduler activation fails, the saved configuration stays disabled. If
scheduler removal fails, the configuration is disabled first, so subsequent
runs do no update work; retry `disable` when the scheduler is available. A
concurrent run holds a lock and must finish before enable/disable can proceed.
Externally modified scheduler files are left unchanged and reported for review.

Manual updates remain available:

```sh
codex plugin marketplace upgrade danepps-legal-research-codex
codex plugin add legal-research@danepps-legal-research-codex
```

Run the install command only after a successful refresh. Plain-copy/manual skill
installs continue to use the repository installer; this updater does not manage
them.
