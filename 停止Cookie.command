#!/bin/zsh
set -eu
label="com.aque.cookie-desktop-pet"
pid_file="$HOME/.cookie_desktop_pet.pid"
plist="$HOME/Library/LaunchAgents/$label.plist"
launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
if [[ -f "$pid_file" ]]; then
  pid="$(<"$pid_file")"
  if [[ "$pid" == <-> ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
  fi
fi
