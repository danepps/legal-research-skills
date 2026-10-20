# Installing Legal Research Skills: instructions for the AI assistant

This page is written for Claude Code or Codex, not for the person. If you are an AI assistant and someone pointed you at this repository and asked you to install or set it up, follow these steps and do the work yourself. The person is probably a law professor, not a programmer: explain each step in one plain sentence, ask them only for things you cannot do (creating an account, pasting a token, clicking a button or a system dialog), and do not ask them to open the Terminal, edit a file, or set an environment variable.

Run the steps in order. Skip anything already done and say so in a few words. Keep the exchange short. If your sandbox blocks network access or writes outside the working folder, request the permission or escalation you need and say in one sentence why.

## 1. Work out where you are

With shell commands, check:

- Which assistant you are (Claude Code or Codex) and the operating system. On Windows under Claude Code, plugins do not work in a WSL environment; if that is where you are, ask the person to choose a non-WSL **Local** environment and start again.
- Whether `git` and `python3` are on the PATH, and the Python version (3.11 or newer is needed).
- Whether the `claude` or `codex` command is on the PATH. The desktop apps do not always put it there.

If `git` or `python3` is missing on a Mac, run `xcode-select --install` and tell the person to click **Install** in the dialog that appears and to tell you when it finishes (a few minutes). On Windows, ask them to install [Git for Windows](https://git-scm.com/download/win) and Python from python.org (ticking the option that adds Python to PATH), then restart the app. If Python is older than 3.11, point them to the current installer at python.org. Do not use `sudo` or administrator privileges.

## 2. Claude Code

**Install.** If `claude` is on the PATH, run:

```sh
claude plugin marketplace add danepps/legal-research-skills
claude plugin install legal-research@danepps
```

If the marketplace is already registered, run `claude plugin marketplace update danepps` instead of the first line; if the plugin is already installed, run `claude plugin update legal-research@danepps` instead of the second. If `claude` is not on the PATH, you cannot install it yourself: ask the person to paste this line into the message box, press Return, confirm adding the source if asked, and choose **Install for you** and then **Install** in the panel that appears:

```text
/plugin install legal-research --marketplace danepps/legal-research-skills
```

If that line is not recognized, the Claude Code version is older; the two-line form is `/plugin marketplace add danepps/legal-research-skills` and then `/plugin install legal-research@danepps`. If either form fails with a message about a blocked or unapproved marketplace, the person's organization manages Claude for them: stop and point them to the "Your organization manages Claude for you" item under [Trouble getting started?](README.md#trouble-getting-started) in the README, which has a request to send their administrator.

**Configure.** The new `/legal-research:setup` skill will not load until a new session, so do its work now. Find the installed setup script:

```sh
find ~/.claude/plugins -path '*legal-research*/skills/setup/setup.py' 2>/dev/null
```

If it lists more than one (older versions can linger in the cache), use the most recently modified.

Then read the `SKILL.md` beside it and follow it from step 1 to the end, using that path wherever it says `${CLAUDE_PLUGIN_ROOT}/skills/setup/setup.py`. It covers Python, the CourtListener token, web access, dynamic workflows, Zotero (optional), and automatic updates (optional).

## 3. Codex

**Install.** If `codex` is on the PATH and `codex plugin --help` works, run:

```sh
codex plugin marketplace add danepps/legal-research-skills
codex plugin add legal-research@danepps-legal-research-codex
```

If the marketplace is already registered, run `codex plugin marketplace upgrade danepps-legal-research-codex` instead of the first line.

If there is no usable `codex` command (common in the desktop app), use the download route instead. Download https://github.com/danepps/legal-research-skills/archive/refs/heads/main.zip and extract it to a stable place that is not a research folder, such as `~/Documents/legal-research-skills-main` (ask before choosing the location if there is any doubt). Then walk the person through the buttons, which you cannot press for them: restart the desktop app, open that `legal-research-skills-main` folder as the project, open **Plugins**, choose **Daniel Epps: Codex Research Skills**, open **Legal Research Skills**, and select install (sometimes shown as **+**). Updates for this route are manual; tell them so.

**CourtListener token (required).** Codex's plugin has no credential setup, so use the Claude plugin's standard-library helper, which works for both. Download it to a temporary directory:

```sh
curl -fsSL https://raw.githubusercontent.com/danepps/legal-research-skills/main/claude-code/skills/setup/setup.py -o "${TMPDIR:-/tmp}/lrs-setup.py"
```

Run `python3 <that file> status`. If `courtlistener.works` is true, move on. Otherwise explain in two sentences that CourtListener is the free, nonprofit case-law database the skills use to confirm that a cited case exists, and that it needs a free account. Give them these steps and wait:

1. Open https://www.courtlistener.com/register/ and create a free account (or sign in).
2. Open https://www.courtlistener.com/profile/api-token/ and copy the long string shown there.
3. Paste it into this chat.

Then run `python3 <that file> courtlistener "<token>"`. It tests the token with a live lookup before saving it to `~/.config/courtlistener/token`, readable only by the person. On HTTP 401, ask them to copy it again. If the output says `"effective": false`, an environment variable holds a different token; tell them which one. Do not echo the token back. Tell them once that the pasted copy also sits in this conversation's history and that they can generate a new token on the same page at any time. Do not run the helper's `allow-web`, `enable-workflows`, `auto-update`, or `zotero` commands under Codex; they configure Claude Code.

**Zotero (optional).** Say that it is optional and that every skill except build-zotero-library works without it. Ask whether they keep their sources in Zotero; treat anything but a clear yes as skip. If yes, the Codex scripts read `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` (`user` or `group`) from the environment, and on macOS a Keychain generic-password entry under the service name `codex-zotero-mcp` (accounts `api-key` and `library-id`). Have them create a key at https://www.zotero.org/settings/keys, and ask before storing it.

**Automatic updates (optional, command-line install only).** After a new session, the plugin's `$legal-research:setup` skill can turn on daily updates. Mention it; do not set it up unasked.

## 4. Finish

Summarize what is in place as a short checklist (Python, plugin installed, CourtListener working, plus web access and workflows for Claude Code, and Zotero and automatic updates marked optional). Then tell the person:

- Start a new conversation (the app calls it a session) so the new tools load. In Claude, use the **Code** tab.
- To try it, choose the folder that holds a short draft with footnotes and type, replacing the filename with theirs: Cite-check "My Article.docx" in this folder. Leave the draft unchanged.
- The first run may ask permission to run checks or divide the work among several agents; approving it lets the run continue.
- Problems go to epps@wustl.edu or https://github.com/danepps/legal-research-skills/issues.

Do not modify anything other than what the commands above write, and do not install other software without saying so first.
