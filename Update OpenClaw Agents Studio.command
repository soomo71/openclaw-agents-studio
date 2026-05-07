#!/bin/zsh
set -u

cd "$(dirname "$0")" || exit 1

echo "Updating OpenClaw Agents Studio..."
echo "Directory: $(pwd)"
echo

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git was not found."
  echo "Suggestion: install Xcode Command Line Tools with: xcode-select --install"
  echo
  read "reply?Press Enter to close..."
  exit 1
fi

if [ ! -d ".git" ]; then
  echo "ERROR: this folder is not a git repository."
  echo "Suggestion: clone openclaw-agents-studio from GitHub again, or place this script in the project root."
  echo
  read "reply?Press Enter to close..."
  exit 1
fi

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
  branch="main"
fi

echo "Branch: $branch"
echo "Current version: $(git describe --tags --always 2>/dev/null || git rev-parse --short HEAD)"
echo

dirty="$(git status --porcelain)"
if [ -n "$dirty" ]; then
  echo "ERROR: local changes detected. The updater stopped to avoid overwriting your files."
  echo
  echo "$dirty"
  echo
  echo "Suggestion: back up or commit these changes, then run this script again."
  read "reply?Press Enter to close..."
  exit 1
fi

echo "Fetching latest changes from GitHub..."
git fetch --tags origin || {
  echo "ERROR: failed to fetch updates. Please check network access or GitHub permissions."
  read "reply?Press Enter to close..."
  exit 1
}

echo "Fast-forwarding..."
git pull --ff-only origin "$branch" || {
  echo "ERROR: fast-forward update failed."
  echo "Suggestion: make sure this branch matches GitHub main, or clone a fresh copy."
  read "reply?Press Enter to close..."
  exit 1
}

echo
echo "Updated to: $(git describe --tags --always 2>/dev/null || git rev-parse --short HEAD)"

viewer_label="ai.openclaw.sessionviewer"
if launchctl print "gui/$(id -u)/$viewer_label" >/dev/null 2>&1; then
  echo "Restarting local Agents Studio service..."
  launchctl kickstart -k "gui/$(id -u)/$viewer_label" >/dev/null 2>&1 || true
  echo "Local URL: http://127.0.0.1:8766"
else
  echo "Background service was not detected. Double-click Start OpenClaw Agents Studio.command when needed."
fi

echo
read "reply?Press Enter to close..."
