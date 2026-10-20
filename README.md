# Legal Research Skills

**AI assistants:** if someone asked you to install or set up these tools, follow [INSTALL.md](INSTALL.md) (plain text: https://raw.githubusercontent.com/danepps/legal-research-skills/main/INSTALL.md) and do the work for them.

Check citations, proofread drafts, find supporting authorities, build a Zotero library, and write research memos using Claude or Codex. These free add-ons give the AI detailed research instructions and tools for checking its work.

**You can install these tools through either desktop app without opening Terminal.** Claude has a guided setup conversation. Codex can install from a downloaded folder, following OpenAI's documented method, though that route has not yet been tested end to end on a fresh account. After setup, you ask for help in ordinary English.

Created by [Daniel Epps](https://law.wustl.edu/faculty-staff-directory/profile/daniel-epps/), a law professor who uses these tools in his own scholarship. [Questions or trouble getting started? Email me.](mailto:epps@wustl.edu)

## Getting started

### The quick way: let the AI install it

Claude and Codex can do the installation themselves, and they handle surprises better than any written instructions. If you already have Claude Code or Codex open on your computer (in Claude, that means the **Code** tab with a **Local** folder chosen; see steps 1–3 of the [Claude desktop guide](#set-up-with-claude-desktop) if not), paste this sentence and press Return:

```text
Install and set up the legal research skills from https://github.com/danepps/legal-research-skills for me. Follow the instructions in its INSTALL.md.
```

Then answer its questions. It will check your computer, install the tools, and ask you only for things it cannot do itself: most importantly, to make a free CourtListener account and paste in a *token* (a string of letters and numbers) from your profile page. If it asks permission to run commands or go online, say yes. If you do not use Zotero, say **skip**. Sometimes it will ask you to paste one line or click a button; do what it says. When it reports that it is done, start a new conversation and try your first task, as in [step 6](#6-try-your-first-task).

If something goes wrong partway, tell the AI what you see in your own words; it can usually work around it. If it gets stuck, use the step-by-step guides below or [email me](mailto:epps@wustl.edu).

### Step by step

You need **only one** of these apps:

- **I'm starting from scratch:** follow the [Claude desktop guide](#set-up-with-claude-desktop), which walks you through setup without Terminal.
- **I already use Claude:** follow the [same guide](#set-up-with-claude-desktop). If the desktop app is already installed, start at step 2.
- **I already use Codex:** follow the [Codex desktop guide](#set-up-with-codex). You do not need the Codex command-line tool.

The add-ons are free. Using them requires access to Claude Code or Codex through your AI provider. A full cite-check can use a substantial amount of your plan, so begin with a short document.

## Set up with Claude desktop

These steps are for Mac or Windows. You will need a Claude plan that includes Claude Code, such as Pro or Max; eligible Team and Enterprise accounts also work. See [Claude's getting-started guide](https://code.claude.com/docs/en/desktop-quickstart) for account requirements.

### 1. Install and open Claude

[Download the Claude desktop app](https://claude.ai/download), install it, and sign in to your Claude account.

### 2. Click the Code tab

At the top of the app, click **Code**. Despite its name, you can use this tab for research and writing. The instructions below all take place here.

### 3. Choose the folder containing your draft

In Finder on a Mac, or File Explorer on Windows, put a short Word document in a folder you can easily find. A few pages with footnotes is a good first test.

Back in Claude, find the row below the message box. Click the first control and choose the top entry under **Local**, which means Claude will work with files on your computer (on Windows, do not choose a WSL entry; plugins are not available there). Then click the folder control beside it, choose **Open folder…**, and select the folder containing your document.

If your app looks different, see [Claude's guide to earlier layouts](https://code.claude.com/docs/en/desktop#check-which-layout-you-have).

### 4. Add the research tools

Copy the entire line below, paste it into **Claude's message box in the Code tab**, and press **Return** or **Enter**. The slash at the beginning tells Claude this is an app shortcut. You do not need to understand or change the line.

```text
/plugin install legal-research --marketplace danepps/legal-research-skills
```

If asked to add the source `danepps/legal-research-skills`, confirm it. When the plugin's details appear, choose **Install for you** (so it is available in all your folders) and select **Install**. A *plugin* is simply the bundle of research tools you are adding.

Wait for installation to finish. If an error appears, use [Trouble getting started?](#trouble-getting-started) below.

### 5. Let Claude finish setup

Start a new conversation in the **Code** tab, using the same folder. The app calls each conversation a *session*. Paste this into the message box and press Return or Enter:

```text
/legal-research:setup
```

Claude will check the helper software it needs and guide you through any missing setup. Follow its prompts. In particular:

- **CourtListener:** create a free account when asked. This is the case-law database used for citation checks. Claude will direct you to a page with a *token*—a string of letters and numbers that lets the tools access your account—and explain how to connect it.
- **Zotero:** if you do not use Zotero, say **skip**. You can still cite-check, proofread, find citations, and write memos.
- **Automatic updates:** choose whether you want new versions of these research tools installed automatically. This is optional.

Wait for Claude to report that setup is finished. You do not need to find or edit any settings files yourself.

### 6. Try your first task

Start another new conversation in the **Code** tab, using the folder containing your draft. Type the request below, replacing `My Article.docx` with your document's actual filename:

```text
Cite-check "My Article.docx" in this folder. Leave the draft unchanged.
When you finish, show me the report and explain how to open it.
```

Claude may ask permission to run its checks or divide the work among several AI assistants. Read the request and approve it to continue.

When it finishes, the report is saved beside your draft as a file whose name ends in `Cite Check.md`, and Claude's reply says where it is. If you cannot open it from the reply, ask Claude to show you the report. Read the **needs your attention** section first. The report should distinguish confirmed problems from items it could not verify. Use the quoted words and footnote numbers to locate each issue in Word.

For future work, choose the relevant folder and ask in ordinary English. You do not need to repeat installation.

## What you can ask for

- **“Cite-check My Article.docx.”** Check citations, quotations, and footnote cross-references against sources, with a report showing problems and anything that could not be checked. It also flags, in an advisory section, lower-court cases whose citation omits later history (affirmed, reversed, cert. denied) and cases a later decision overruled or limited, and on a re-run it opens with what changed since the last report.
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

When the details panel opens, choose **Install for you** and select **Install**. Then continue with step 5.

**Your computer asks to install “command line developer tools.”** On a Mac, click **Install**, wait for it to finish, and retry the step. The name sounds technical, but this is an installer dialog; you do not need to type Terminal commands. If setup still reports missing software, follow its next instructions. On Windows, plugin installation needs [Git for Windows](https://git-scm.com/download/win); install it and restart Claude if prompted that Git is missing.

**The setup shortcut does not appear.** Start a new conversation in the Code tab after installation. If it is still missing, click **+** beside the message box, then **Add plugins** (or **Plugins → Browse plugins**) and check that Legal Research is installed. See [Claude's plugin instructions](https://code.claude.com/docs/en/desktop#install-plugins).

**Your organization manages Claude for you.** On some Team and Enterprise accounts an administrator controls which plugin sources Claude may add, and the installation line fails with a message about a blocked or unapproved marketplace. Nothing is wrong with your copy of Claude. Send your administrator this request:

> Could you allow the plugin marketplace `danepps/legal-research-skills` (a GitHub repository of legal-research skills by Professor Daniel Epps, Washington University in St. Louis) in our Claude Code settings, so I can install the `legal-research` plugin? It adds research instructions and scripts only; it does not change who can see my files.

If the answer is no, the [technical reference](TECHNICAL.md#install-for-claude-code) explains how to run the skills from a downloaded folder on a personal account instead.

**Claude cannot find the draft.** Check that you selected the folder containing it and used the exact filename in your request. You can ask: “What files can you see in this folder?”

**Still stuck?** [Email epps@wustl.edu](mailto:epps@wustl.edu) with the step you reached and the error message. You can also [report a problem on GitHub](https://github.com/danepps/legal-research-skills/issues). A confusing instruction is a bug.

<a id="install-for-codex"></a>

## Set up with Codex

**You do not need to install the Codex CLI or use Terminal for this route.** Use Codex in the ChatGPT desktop app, with access to folders on your computer. You do not need Claude as well.

1. **Download the tools.** [Download the ZIP file](https://github.com/danepps/legal-research-skills/archive/refs/heads/main.zip) and open it to extract the folder. On Windows, choose **Extract All** if needed. Keep the resulting `legal-research-skills-main` folder somewhere you can find it again, such as Documents.
2. **Open that folder in Codex.** In the desktop app, select the downloaded folder as your local project. Choose the outer `legal-research-skills-main` folder; it contains the catalog that tells the app where to find the plugin.
3. **Open the plugin browser.** Restart the desktop app, reopen that project, and open **Plugins**. Choose the source named **Daniel Epps: Codex Research Skills**, open **Legal Research Skills**, and select the install button, which may appear as **+**. If that source does not appear, check that the selected project is the extracted folder, then [get in touch](mailto:epps@wustl.edu) if it is still missing.
4. **Check research setup.** Start a new Codex conversation with your draft's folder selected. Ask: “Check what I need to use Legal Research Skills on this computer, including Python, web access, and CourtListener. Walk me through anything missing.” Installing the plugin adds the research instructions and scripts; Python and research accounts still need to be available. Zotero is optional. The plugin's named `setup` helper handles updates only, so it is not a replacement for this check.
5. **Try a short draft.** Ask: “Cite-check My Article.docx. Leave the draft unchanged, and show me how to open the report.” Substitute your actual filename.

This uses OpenAI's documented [installation from a local folder](https://developers.openai.com/plugins/build/plugins#build-your-own-curated-plugin-list). The download already includes the catalog, so you do not need to create or edit it. One caution: the download has been checked to show up correctly in Codex's plugin browser, but a complete installation through the desktop buttons on a fresh account has not yet been tested. If a step does not match what you see, [email me](mailto:epps@wustl.edu) with where you got stuck; that is exactly the report I need.

**Updates for this route are manual.** Keep the downloaded tools separate from your research documents. To update, download a fresh ZIP and repeat the folder-selection and installation steps. If the plugin still shows the old version, remove it in Plugins and install it from the new folder. The optional scheduled updater does not update ZIP installations.

If you prefer Terminal, use the [command-line installation instructions](TECHNICAL.md#install-for-codex). The [Codex plugin guide](https://github.com/danepps/legal-research-skills/blob/main/codex/README.md) has more details, including [research-account configuration](TECHNICAL.md#prerequisites-and-configuration).

## Keeping up to date

**Claude:** during setup, say yes to automatic updates if you want them. You can change your choice later by entering `/legal-research:setup` in the Code tab and asking to turn automatic updates on or off.

**Codex:** if you used the ZIP download, follow the manual update steps in the [Codex desktop guide](#set-up-with-codex). If you installed through the command-line instructions, you can instead say: “Use $legal-research:setup to enable automatic updates.” See the [Codex update guide](https://github.com/danepps/legal-research-skills/blob/main/codex/setup/references/automatic-updates.md) for details.

Start a new conversation after an update to use the updated tools. Release notes are in the [Claude changelog](CHANGELOG.md) and [Codex changelog](https://github.com/danepps/legal-research-skills/blob/main/codex/CHANGELOG.md).

<a id="other-ways-to-install"></a>
<a id="install-for-claude-code"></a>
<a id="prerequisites-and-configuration"></a>

## Technical reference

For terminal installation, account configuration, how the tools work, and contributor information, see the [technical reference](TECHNICAL.md). The desktop installation steps above do not require Terminal.

## About

Written by [Daniel Epps](https://law.wustl.edu/faculty-staff-directory/profile/daniel-epps/), Howard and Caroline Cayne Distinguished Professor of Law at Washington University in St. Louis and co-host of the *Divided Argument* podcast. See also his [Bluebook citation style](https://danepps.github.io/bluebook/) and [Zotero plugins](https://danepps.github.io/zotero/) for law reviews.

These are working research tools, released as-is under the [MIT license](https://github.com/danepps/legal-research-skills/blob/main/LICENSE).
