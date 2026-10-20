# Legal Research Skills

Check citations, proofread drafts, find supporting authorities, build a Zotero library, and write research memos using Claude or Codex. These free add-ons give the AI detailed research instructions and tools for checking its work.

**No coding or Terminal experience needed for the Claude desktop guide below.** You click through setup and paste a few shortcuts into the app's message box. After that, you ask for help in ordinary English.

Created by [Daniel Epps](https://law.wustl.edu/faculty-staff-directory/profile/daniel-epps/), a law professor who uses these tools in his own scholarship. [Questions or trouble getting started? Email me.](mailto:epps@wustl.edu)

## Getting started

You need **only one** of these apps:

- **I'm starting from scratch:** follow the [Claude desktop guide](#set-up-with-claude-desktop), which walks you through setup without Terminal.
- **I already use Claude:** follow the [same guide](#set-up-with-claude-desktop). If the desktop app is already installed, start at step 2.
- **I already use Codex:** see [Set up with Codex](#set-up-with-codex). Its installation currently requires extra technical setup.

The add-ons are free. Using them requires access to Claude Code or Codex through your AI provider. A full cite-check can use a substantial amount of your plan, so begin with a short document.

## Set up with Claude desktop

These steps are for Mac or Windows. You will need a Claude plan that includes Claude Code, such as Pro or Max; eligible Team and Enterprise accounts also work. See [Claude's getting-started guide](https://code.claude.com/docs/en/desktop-quickstart) for account requirements.

### 1. Install and open Claude

[Download the Claude desktop app](https://claude.ai/download), install it, and sign in to your Claude account.

### 2. Click the Code tab

At the top of the app, click **Code**. Despite its name, you can use this tab for research and writing. The instructions below all take place here.

### 3. Choose the folder containing your draft

In Finder on a Mac, or File Explorer on Windows, put a short Word document in a folder you can easily find. A few pages with footnotes is a good first test.

Back in Claude, find the row below the message box. Click the first control and choose the top entry under **Local**, which means Claude will work with files on your computer. Then click the folder control beside it, choose **Open folder…**, and select the folder containing your document.

If your app looks different, see [Claude's guide to earlier layouts](https://code.claude.com/docs/en/desktop#check-which-layout-you-have).

### 4. Add the research tools

Copy the entire line below, paste it into **Claude's message box in the Code tab**, and press **Return** or **Enter**. The slash at the beginning tells Claude this is an app shortcut. You do not need to understand or change the line.

```text
/plugin install legal-research --marketplace danepps/legal-research-skills
```

If asked to add the source `danepps/legal-research-skills`, confirm it. When the plugin's details appear, choose to install it **for your user account**, so it is available in all your folders, and select **Install**. A *plugin* is simply the bundle of research tools you are adding.

Wait for installation to finish. If an error appears, use [Trouble getting started?](#trouble-getting-started) below.

### 5. Let Claude finish setup

Start a new conversation in the **Code** tab, using the same folder. The app calls each conversation a *session*. Paste this into the message box and press Return or Enter:

```text
/legal-research:setup
```

Claude will check the helper software it needs and guide you through any missing setup. Follow its prompts. In particular:

- **CourtListener:** create a free account when asked. This is the case-law database used for citation checks. Claude will direct you to a page with a *token*—a string of letters and numbers that lets the tools access your account—and explain how to connect it.
- **Automatic updates:** choose whether you want new versions of these research tools installed automatically. This is optional.
- **Zotero:** if you do not use Zotero, say **skip**. You can still cite-check, proofread, find citations, and write memos.

Wait for Claude to report that setup is finished. You do not need to find or edit any settings files yourself.

### 6. Try your first task

Start another new conversation in the **Code** tab, using the folder containing your draft. Type the request below, replacing `My Article.docx` with your document's actual filename:

```text
Cite-check "My Article.docx" in this folder. Leave the draft unchanged.
When you finish, show me the report and explain how to open it.
```

Claude may ask permission to run its checks or divide the work among several AI assistants. Read the request and approve it to continue.

When it finishes, open the report from the link in its reply. Read the **needs your attention** section first. The report should distinguish confirmed problems from items it could not verify. Use the quoted words and footnote numbers to locate each issue in Word.

For future work, choose the relevant folder and ask in ordinary English. You do not need to repeat installation.

## What you can ask for

- **“Cite-check My Article.docx.”** Check citations, quotations, and footnote cross-references against sources, with a report showing problems and anything that could not be checked.
- **“Find me a cite for the proposition that…”** Find a few verified authorities, with specific pages and short explanations you can use in a footnote.
- **“Proofread My Article.docx.”** Find typos, missing or repeated words, and inconsistent terminology or cross-references.
- **“Build a Zotero collection on…”** Find sources, create records, check for duplicates, and attach available PDFs. Requires a connected Zotero library.
- **“Write me a research memo on…”** Research the question and produce a memo with source links and disclosed limits.
- **“Prep Smith v. Arizona.”** Collect Supreme Court case materials for reading on a reMarkable tablet. This tool is available in the Claude plugin and requires additional tablet setup.

## What these tools add

A normal AI conversation can help with a research question. These skills add a repeatable workflow: read footnotes directly from a Word file, retrieve sources, compare quotations, keep track of what was checked, and save a report you can work through. Larger tasks can be divided among several AI assistants and reviewed again before delivery.

**You still decide what to rely on.** These tools can miss problems and raise false alarms. They supplement your own reading and the journal's cite-check. For sources behind a login or paywall, supply a PDF you are authorized to download; the report should identify any source the tools could not access.

## Trouble getting started?

**The installation shortcut is not recognized.** First check that you are in the **Code** tab and selected **Local**. An older version of Claude Code may need two separate shortcuts. Paste each line below into Claude's message box, pressing Return or Enter after each:

```text
/plugin marketplace add danepps/legal-research-skills
```

```text
/plugin install legal-research@danepps
```

When the details panel opens, select **Install** for your user account. Then continue with step 5.

**Your computer asks to install “command line developer tools.”** On a Mac, click **Install**, wait for it to finish, and retry the step. The name sounds technical, but this is an installer dialog; you do not need to type Terminal commands. If setup still reports missing software, follow its next instructions. On Windows, plugin installation needs [Git for Windows](https://git-scm.com/download/win); install it and restart Claude if prompted that Git is missing.

**The setup shortcut does not appear.** Start a new conversation in the Code tab after installation. If it is still missing, click **+** beside the message box, then **Add plugins** (or **Plugins → Browse plugins**) and check that Legal Research is installed. See [Claude's plugin instructions](https://code.claude.com/docs/en/desktop#install-plugins).

**Claude cannot find the draft.** Check that you selected the folder containing it and used the exact filename in your request. You can ask: “What files can you see in this folder?”

**Still stuck?** [Email epps@wustl.edu](mailto:epps@wustl.edu) with the step you reached and the error message. You can also [report a problem on GitHub](https://github.com/danepps/legal-research-skills/issues). A confusing instruction is a bug.

<a id="install-for-codex"></a>

## Set up with Codex

The Codex version supports citation checking, citation finding, proofreading, Zotero library building, research memos, and broader research projects. Once installed and configured, you can use it from the desktop app and ask in ordinary English.

**Installation currently needs someone comfortable with technical setup.** The commands require the Codex command-line tool to be installed, and CourtListener and Zotero need separate configuration. The Codex setup helper manages automatic updates only. You do not need to install Claude as well.

If you already use the Codex command-line tool, or someone is helping you, follow the [Codex installation instructions](TECHNICAL.md#install-for-codex) and [account configuration](TECHNICAL.md#prerequisites-and-configuration). The [Codex plugin guide](https://github.com/danepps/legal-research-skills/blob/main/codex/README.md) lists the skills and explains updates and removal. If you want the walkthrough that avoids Terminal, use the [Claude desktop guide](#set-up-with-claude-desktop).

## Keeping up to date

**Claude:** during setup, say yes to automatic updates if you want them. You can change your choice later by entering `/legal-research:setup` in the Code tab and asking to turn automatic updates on or off.

**Codex:** after installing the plugin, say: “Use $legal-research:setup to enable automatic updates.” You can also ask it to show update status or turn updates off. See the [Codex update guide](https://github.com/danepps/legal-research-skills/blob/main/codex/setup/references/automatic-updates.md) for details.

Start a new conversation after an update to use the updated tools. Release notes are in the [Claude changelog](CHANGELOG.md) and [Codex changelog](https://github.com/danepps/legal-research-skills/blob/main/codex/CHANGELOG.md).

<a id="other-ways-to-install"></a>
<a id="install-for-claude-code"></a>
<a id="prerequisites-and-configuration"></a>

## Technical reference

For terminal installation, account configuration, how the tools work, and contributor information, see the [technical reference](TECHNICAL.md). You can skip that page when following the Claude desktop walkthrough.

## About

Written by [Daniel Epps](https://law.wustl.edu/faculty-staff-directory/profile/daniel-epps/), Howard and Caroline Cayne Distinguished Professor of Law at Washington University in St. Louis and co-host of the *Divided Argument* podcast. See also his [Bluebook citation style](https://danepps.github.io/bluebook/) and [Zotero plugins](https://danepps.github.io/zotero/) for law reviews.

These are working research tools, released as-is under the [MIT license](https://github.com/danepps/legal-research-skills/blob/main/LICENSE).
