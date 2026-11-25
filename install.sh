#!/bin/sh
set -eu

echo 'Installing Superchat for this account...'
if ! command -v git >/dev/null 2>&1; then
  echo 'Git is required. Install Git and run this installer again.' >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  if ! command -v curl >/dev/null 2>&1; then
    echo 'curl is required to install uv.' >&2
    exit 1
  fi
  echo 'Installing uv...'
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

uv tool install --python 3.12 --force git+https://github.com/sasindaran/Superchat
superchat_bin=$(uv tool dir --bin)/superchat
"$superchat_bin" setup
printf 'Work email (press Enter to skip sign-in): '
read -r superchat_email
if [ -n "$superchat_email" ]; then
  "$superchat_bin" login --email "$superchat_email"
  echo 'Open the emailed sign-in link on this computer.'
fi
echo 'Restart Claude Desktop and start a new Claude Code session.'
if [ "$(uname -s)" = Linux ]; then
  echo 'Linux setup registers Claude Code. Claude Desktop setup requires a supported Desktop installation.'
fi
