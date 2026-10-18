#!/bin/sh
# Installer for legal-research-skills (https://github.com/danepps/legal-research-skills)
#
# One line, run in Terminal:
#   curl -fsSL https://danepps.github.io/legal-research-skills/install.sh | sh
#
# What it does:
#   Claude Code: registers the "danepps" plugin marketplace and installs the "law"
#                plugin with the claude CLI (or prints the two commands to type in
#                Claude Code if the CLI is not on your PATH).
#   Codex:       clones (or updates) the repository into ~/legal-research-skills and
#                links the Codex skills into ~/.agents/skills.
# It never overwrites anything that is already there. Re-run it any time to update.
#
# Options:   sh install.sh --claude     only Claude Code
#            sh install.sh --codex      only Codex
#            sh install.sh --all        both (default when neither tool is detected)
set -e

REPO="danepps/legal-research-skills"
REPO_URL="https://github.com/$REPO.git"
MARKET="danepps"
PLUGIN="law"
DEST="${LRS_HOME:-$HOME/legal-research-skills}"
WANT_CLAUDE=""
WANT_CODEX=""

for arg in "$@"; do
  case "$arg" in
    --claude) WANT_CLAUDE=1 ;;
    --codex) WANT_CODEX=1 ;;
    --all) WANT_CLAUDE=1; WANT_CODEX=1 ;;
    -h|--help) sed -n '2,19p' "$0" 2>/dev/null; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ -z "$WANT_CLAUDE$WANT_CODEX" ]; then
  if command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; then WANT_CLAUDE=1; fi
  if command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ] || [ -d "$HOME/.agents" ]; then WANT_CODEX=1; fi
  if [ -z "$WANT_CLAUDE$WANT_CODEX" ]; then WANT_CLAUDE=1; WANT_CODEX=1; fi
fi

# ---------------------------------------------------------------- Claude Code
CLAUDE_MANUAL=""
if [ -n "$WANT_CLAUDE" ]; then
  echo "Claude Code: the $PLUGIN plugin"
  if command -v claude >/dev/null 2>&1; then
    if claude plugin marketplace list 2>/dev/null | grep -q "$MARKET"; then
      echo "  marketplace $MARKET already registered; refreshing"
      claude plugin marketplace update "$MARKET" >/dev/null 2>&1 || true
    else
      claude plugin marketplace add "$REPO"
    fi
    if claude plugin list 2>/dev/null | grep -q "$PLUGIN@$MARKET"; then
      echo "  $PLUGIN@$MARKET already installed; updating"
      claude plugin update "$PLUGIN@$MARKET" || true
    else
      claude plugin install "$PLUGIN@$MARKET"
    fi
  else
    CLAUDE_MANUAL=1
    echo "  The claude command is not on your PATH, so type these two lines inside Claude Code instead:"
    echo "    /plugin marketplace add $REPO"
    echo "    /plugin install $PLUGIN@$MARKET"
  fi
fi

# ---------------------------------------------------------------------- Codex
if [ -n "$WANT_CODEX" ]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "git is not installed. On a Mac, run 'xcode-select --install', accept the prompt, then run this again." >&2
    exit 1
  fi
  if [ -d "$DEST/.git" ]; then
    echo "Codex: updating $DEST"
    git -C "$DEST" pull -q --ff-only || echo "  (could not fast-forward; keeping the existing copy)"
  elif [ -e "$DEST" ]; then
    echo "$DEST exists but is not a git checkout; move it aside and run again." >&2
    exit 1
  else
    echo "Codex: downloading to $DEST"
    git clone -q "$REPO_URL" "$DEST"
  fi
  echo "Codex skills -> ~/.agents/skills"
  mkdir -p "$HOME/.agents/skills"
  for s in legal-research-memo cite-check internal-proofread find-cite build-zotero-library deep-research; do
    src="$DEST/codex/$s"; dst="$HOME/.agents/skills/$s"
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
      echo "  ok       $dst"
    elif [ -e "$dst" ] || [ -L "$dst" ]; then
      echo "  skipped  $dst (already exists; left untouched)"
    else
      ln -s "$src" "$dst"
      echo "  linked   $dst"
    fi
  done
fi

cat <<'NEXT'

Done. Next steps:
  1. Start a new Claude Code or Codex session (restart the desktop app if it was open).
     In Claude Code, type / and look for law:cite-check, law:proofread, and the others.
  2. For case checking, get a free CourtListener API token at
     https://www.courtlistener.com/profile/api-token/ and add this line to ~/.zshrc:
       export COURTLISTENER_API_TOKEN="paste-your-token-here"
  3. Claude Pro plan only: in Claude Code, type /config and turn on "Dynamic workflows".
     (cite-check, proofread, and legal-research need it; Max and Team plans have it on already.)
  4. Open a folder with a short draft and ask: "cite-check this draft."
Updates: Claude Code users can turn on auto-update under /plugin > Marketplaces > danepps,
or run /plugin marketplace update danepps. Codex users re-run this installer.
NEXT
