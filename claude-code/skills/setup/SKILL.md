---
name: setup
description: One-time, conversational setup for the legal-research plugin — checks Python, saves and tests the user's CourtListener token, pre-allows web tools, offers automatic plugin updates, and (optionally) registers a Zotero library, all from inside Claude Code so the user never edits a configuration file. Trigger on /legal-research:setup, on a request to set up the legal research tools, to find out where a CourtListener token goes, to turn automatic updates of this plugin on or off, or to connect a Zotero library, or when another skill in this plugin finds the CourtListener token missing.
---

# Setup

The user is probably a law professor, not a programmer. They installed this plugin by pasting
one line and want everything else to happen in this conversation. Do the work for them, explain
each step in one plain sentence, and never ask them to open a file, the Terminal, or a text
editor. Everything below is done with `${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py`, which
backs up any file it rewrites and never removes a setting it did not add.

Run the steps in order. Skip anything the status report shows is already done, and say so in
a few words, such as CourtListener, already working. Keep the whole exchange short.

## 1. Take stock

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" status
```

- If `python3` is missing or the command fails to start: on a Mac the first use of `python3`
  opens a dialog offering to install the command line developer tools. Tell the user to click
  Install, wait for it to finish (a few minutes), then type `/legal-research:setup` again. On
  Windows, tell them to install Python from python.org (tick the option that adds python to PATH), restart the
  app, and run setup again.
- If `python.ok` is false (older than 3.11): same advice, with the current python.org installer.
- Do not paste the raw JSON at the user. Summarize it as a short checklist with a tick or cross
  per line: Python, CourtListener, web access, automatic updates, Zotero (marked optional), git.

## 2. CourtListener token (required for case checking)

If `courtlistener.works` is true, say so and move on.

Otherwise explain, in two sentences, that CourtListener is the free, nonprofit case-law
database the skills use to confirm that a cited case exists and says what the draft claims, and
that it needs a free account. Then give the user these exact steps and wait for their reply:

1. Open https://www.courtlistener.com/register/ and create a free account (or sign in).
2. Open https://www.courtlistener.com/profile/api-token/ and copy the long string of letters
   and numbers shown there.
3. Paste it here, into this chat, and press Return.

When they paste it, run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" courtlistener "<token>"
```

The script tests the token with a live lookup of *Brown v. Board of Education* before saving
it to `~/.config/courtlistener/token`, readable only by the user. Exit 0 means it works, and
it works immediately, with no restart. On HTTP 401 the token was mistyped or truncated: ask
them to copy it again. On a network error, say CourtListener could not be reached and offer
to retry.

Tell the user, once, that the token now lives on their own computer, that the pasted copy
also sits in this conversation's history, and that if that ever worries them they can
generate a new token on the same CourtListener page and run setup again.

## 3. Web access (so a long run is never interrupted by a permission prompt)

If either `web_permissions` entry is false:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" allow-web
```

One sentence to the user: the research skills look things up on the open web, and this lets
them do so during a long run without stopping to ask each time.

## 4. Dynamic workflows (needed on a Claude Pro plan)

cite-check, proofread, and legal-research run as multi-agent dynamic workflows. Claude turns
these on by default for Max, Team, and Enterprise plans but not for Pro. The switch is a
setting, so just set it; it is harmless on a plan that already has it on. If
`enableWorkflows` in the status report is not `true`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" enable-workflows
```

One sentence to the user: this lets the bigger skills split the work among several agents, and
it takes effect the next time they start a session. (It is the same switch as the **Dynamic
workflows** row in `/config`; docs: https://code.claude.com/docs/en/workflows.)

## 5. Zotero (optional; many users do not have it, and nothing else depends on it)

Say first that this step is optional and that every skill except build-library works without
Zotero, checking articles against the open web instead. Then ask whether they keep their
sources in Zotero, and say that if so you can connect the library so cite-check and find-cite
search it before the web, and that they can answer skip now and run setup again later.
Treat anything but a clear yes as skip, and never present a missing Zotero as a problem in
the final checklist; show it as not connected (optional).

If yes and `zotero.servers` already lists a server, say so and move on.

Otherwise:

1. If `zotero.uvx_installed` is false, the Zotero connector needs a small helper program
   called `uv`. Tell the user you are installing it, then run
   `curl -LsSf https://astral.sh/uv/install.sh | sh` (Mac) or
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
   If the install fails, say so plainly, skip Zotero, and note that the rest still works.
2. Give the user these steps and wait:
   1. Open https://www.zotero.org/settings/keys while signed in to zotero.org.
   2. Near the top, the page shows the numeric userID for use in API calls (the page is behind
      a login, so this wording is from memory). Note that number.
   3. Click the button that creates a new private key, give it any name, leave library access
      allowed, allow write access if they want build-library to add records, and save.
   4. Paste the key and the userID here.
3. Run:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" zotero --key "<key>" --library-id <userID>
   ```

   For a shared group library, add `--type group --name zotero-<short-name>` with the group's
   number (the digits in its zotero.org/groups/NNNN URL) as the library id.
4. Tell the user the Zotero connection takes effect the next time they start Claude Code (in
   the desktop app: close the session and open a new one).

## 6. Automatic updates (optional)

Claude Code updates a plugin on its own only when the marketplace it came from has
auto-update on, and for this marketplace (`danepps`) that is off unless the user turns it on.
The switch is a setting, the same `autoUpdate` field that the Enable auto-update choice under
`/plugin` > Marketplaces writes, so the script sets it; no terminal command or file editing.

Read `auto_update` in the status report first:

- `effective` is `on`: say automatic updates are already on and move on. Never turn them off
  unless asked.
- `effective` is `not registered`: the plugin was not installed from the `danepps`
  marketplace (for example, it was loaded from a folder), so there is nothing to update
  automatically. Say so in one sentence, show automatic updates as not available in the
  checklist, and move on; this does not affect anything else.
- Otherwise ask once, and wait for the answer:

  Would you like this plugin to receive future updates automatically? Claude checks when you
  start a session, and new sessions use the updated skills. You can turn this off later by
  asking me to.

  Treat anything but a clear yes as skip. Skipping changes nothing and must not hold up the
  rest of setup. If the user already asked for automatic updates in their own words, skip the
  question and run the command.

For a yes:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" auto-update on
```

Report what the script read back, not what the user said: the JSON's `auto_update.effective`
is the state. If it is `on`, the checklist line is automatic updates: on (verified in
settings). If the output carries a `warning` naming a variable such as `DISABLE_AUTOUPDATER`,
the setting is saved but Claude Code's whole update pass is switched off by that variable;
tell the user which variable, that it was set outside this plugin (usually in a shell profile
or the `env` block of `~/.claude/settings.json`), and that updates will run once it is
removed; the checklist line is then automatic updates: not confirmed, blocked by
`<variable>`. If the command exits 1, read its `next_step` to the user and show automatic
updates: not confirmed.

Three things to know: the setting takes effect in the next session; it governs every plugin
installed from `danepps`, not this plugin alone; and an update changes files on disk only,
so a running session keeps what it loaded until a new one starts.

To turn updates off later (the user asks, in any words), run the same command with `off`,
and read `effective` back the same way.

## 7. Finish

Re-run `status` and show the final checklist. Then, in two sentences: they are ready; to try
it, open a folder that holds a short draft (in the desktop app, the folder picker at the top;
in the Terminal, `cd` to it first) and type cite-check this draft. If this run turned on
workflows, automatic updates, or Zotero, say that those take effect in a new session, so they
should start one first. Mention that the first cite-check asks for approval before it launches its
workflow, and that choosing Always avoids the question next time.

Do not install anything else, do not touch files other than the three the script writes, and
do not read or echo the token or key back after saving them.
