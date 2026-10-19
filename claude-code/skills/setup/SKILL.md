---
name: setup
description: One-time, conversational setup for the legal-research plugin — checks Python, saves and tests the user's CourtListener token, pre-allows web tools, and (optionally) registers a Zotero library, all from inside Claude Code so the user never edits a configuration file. Trigger on "/legal-research:setup", "set up the legal research tools", "where do I put my CourtListener token", "connect my Zotero library", or when another skill in this plugin finds the CourtListener token missing.
---

# Setup

The user is probably a law professor, not a programmer. They installed this plugin by pasting
one line and want everything else to happen in this conversation. Do the work for them, explain
each step in one plain sentence, and never ask them to open a file, the Terminal, or a text
editor. Everything below is done with `${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py`, which
backs up any file it rewrites and never removes a setting it did not add.

Run the steps in order. Skip anything the status report shows is already done, and say so in
a word ("CourtListener: already working"). Keep the whole exchange short.

## 1. Take stock

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" status
```

- If `python3` is missing or the command fails to start: on a Mac the first use of `python3`
  opens a dialog offering to install the "command line developer tools." Tell the user to click
  Install, wait for it to finish (a few minutes), then type `/legal-research:setup` again. On
  Windows, tell them to install Python from python.org (tick "Add python to PATH"), restart the
  app, and run setup again.
- If `python.ok` is false (older than 3.11): same advice, with the current python.org installer.
- Do not paste the raw JSON at the user. Summarize it as a short checklist with a tick or cross
  per line: Python, CourtListener, web access, Zotero, git.

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

## 5. Zotero (optional, for people who keep sources in Zotero)

Ask: "Do you keep your sources in Zotero? If so, I can connect your library so cite-check and
find-cite can search it. If not, or not now, say skip." Treat anything but a clear yes as skip.

If yes and `zotero.servers` already lists a server, say so and move on.

Otherwise:

1. If `zotero.uvx_installed` is false, the Zotero connector needs a small helper program
   called `uv`. Tell the user you are installing it, then run
   `curl -LsSf https://astral.sh/uv/install.sh | sh` (Mac) or
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
   If the install fails, say so plainly, skip Zotero, and note that the rest still works.
2. Give the user these steps and wait:
   1. Open https://www.zotero.org/settings/keys while signed in to zotero.org.
   2. Near the top the page says "Your userID for use in API calls is" followed by a number.
      Note that number.
   3. Click "Create new private key", give it any name, leave "Allow library access" ticked,
      tick "Allow write access" if they want build-library to add records, and save.
   4. Paste the key and the userID here.
3. Run:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py" zotero --key "<key>" --library-id <userID>
   ```

   For a shared group library, add `--type group --name zotero-<short-name>` with the group's
   number (the digits in its zotero.org/groups/NNNN URL) as the library id.
4. Tell the user the Zotero connection takes effect the next time they start Claude Code (in
   the desktop app: close the session and open a new one).

## 6. Finish

Re-run `status` and show the final checklist. Then, in two sentences: they are ready; to try
it, open a folder that holds a short draft (in the desktop app, the folder picker at the top;
in the Terminal, `cd` to it first) and type "cite-check this draft." If this run turned on
workflows or added Zotero, say that those two take effect in a new session, so they should
start one first. Mention that the first cite-check asks for approval before it launches its
workflow, and that choosing "Always" avoids the question next time.

Do not install anything else, do not touch files other than the three the script writes, and
do not read or echo the token or key back after saving them.
