#!/bin/sh
# Installer for legal-research-skills (https://github.com/danepps/legal-research-skills)
#
# One line, run in Terminal:
#   curl -fsSL https://danepps.github.io/legal-research-skills/install.sh | sh
#
# What it does: clones (or updates) the repository into ~/legal-research-skills,
# then links the skills into the folders Claude Code and Codex read from. It never
# overwrites anything that is already there. Re-run it any time to update.
#
# Options:   sh install.sh --claude     only the Claude Code skills
#            sh install.sh --codex      only the Codex skills
#            sh install.sh --all        both (default when neither tool is detected)
set -e

REPO_URL="https://github.com/danepps/legal-research-skills.git"
DEST="${LRS_HOME:-$HOME/legal-research-skills}"
WANT_CLAUDE=""
WANT_CODEX=""

for arg in "$@"; do
  case "$arg" in
    --claude) WANT_CLAUDE=1 ;;
    --codex) WANT_CODEX=1 ;;
    --all) WANT_CLAUDE=1; WANT_CODEX=1 ;;
    -h|--help) sed -n '2,15p' "$0" 2>/dev/null; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ -z "$WANT_CLAUDE$WANT_CODEX" ]; then
  if command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; then WANT_CLAUDE=1; fi
  if command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ] || [ -d "$HOME/.agents" ]; then WANT_CODEX=1; fi
  if [ -z "$WANT_CLAUDE$WANT_CODEX" ]; then WANT_CLAUDE=1; WANT_CODEX=1; fi
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is not installed. On a Mac, run 'xcode-select --install', accept the prompt, then run this again." >&2
  exit 1
fi

if [ -d "$DEST/.git" ]; then
  echo "Updating $DEST"
  git -C "$DEST" pull -q --ff-only || echo "  (could not fast-forward; keeping the existing copy)"
elif [ -e "$DEST" ]; then
  echo "$DEST exists but is not a git checkout; move it aside and run again." >&2
  exit 1
else
  echo "Downloading to $DEST"
  git clone -q "$REPO_URL" "$DEST"
fi

link_set() {
  # $1 = source subfolder, $2 = destination folder, rest = skill names
  src_dir="$DEST/$1"; dst_dir="$2"; shift 2
  mkdir -p "$dst_dir"
  for s in "$@"; do
    src="$src_dir/$s"; dst="$dst_dir/$s"
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
      echo "  ok       $dst"
    elif [ -e "$dst" ] || [ -L "$dst" ]; then
      echo "  skipped  $dst (already exists; left untouched)"
    else
      ln -s "$src" "$dst"
      echo "  linked   $dst"
    fi
  done
}

if [ -n "$WANT_CLAUDE" ]; then
  echo "Claude Code skills -> ~/.claude/skills"
  link_set claude-code "$HOME/.claude/skills" legal-research cite-check proofread find-cite build-library case-prep
fi
if [ -n "$WANT_CODEX" ]; then
  echo "Codex skills -> ~/.agents/skills"
  link_set codex "$HOME/.agents/skills" legal-research-memo cite-check internal-proofread find-cite build-zotero-library deep-research
fi

cat <<'NEXT'

Done. Next steps:
  1. Start a new Claude Code or Codex session (restart the desktop app if it was open).
  2. For case checking, get a free CourtListener API token at
     https://www.courtlistener.com/profile/api-token/ and add this line to ~/.zshrc:
       export COURTLISTENER_API_TOKEN="paste-your-token-here"
  3. Claude Pro plan only: in Claude Code, type /config and turn on "Dynamic workflows".
     (cite-check, proofread, and legal-research need it; Max and Team plans have it on already.)
  4. Open a folder with a short draft and ask: "cite-check this draft."
Re-run this installer any time to update.
NEXT
