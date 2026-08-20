#!/bin/zsh
set -eu

root="${0:A:h}"
label="com.aque.cookie-desktop-pet"
runtime="$HOME/Library/Application Support/CookieDesktopPet"
plist="$HOME/Library/LaunchAgents/$label.plist"
pid_file="$HOME/.cookie_desktop_pet.pid"

find_python() {
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

if [[ -f "$pid_file" ]]; then
  pid="$(<"$pid_file")"
  if [[ "$pid" == <-> ]] && kill -0 "$pid" 2>/dev/null; then
    exit 0
  fi
fi

base_python="$(find_python)" || {
  echo "需要 Python 3。请先从 python.org 或 Homebrew 安装后再双击。"
  read -k 1 "?按任意键关闭…"
  exit 1
}

mkdir -p "$runtime" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cp "$root/cookie_pet.py" "$runtime/cookie_pet.py"
ditto "$root/assets_compact" "$runtime/assets_compact"

if "$base_python" -c 'import AppKit, objc' >/dev/null 2>&1; then
  runtime_python="$base_python"
else
  venv="$runtime/.venv"
  if [[ ! -x "$venv/bin/python" ]]; then
    "$base_python" -m venv "$venv"
  fi
  "$venv/bin/python" -m pip install -r "$root/requirements-runtime.txt"
  runtime_python="$venv/bin/python"
fi

cp "$root/launchagent.plist.template" "$plist"
/usr/libexec/PlistBuddy -c "Set :ProgramArguments:0 $runtime_python" "$plist"
/usr/libexec/PlistBuddy -c "Set :ProgramArguments:1 $runtime/cookie_pet.py" "$plist"
/usr/libexec/PlistBuddy -c "Set :WorkingDirectory $runtime" "$plist"
/usr/libexec/PlistBuddy -c "Set :StandardOutPath $HOME/Library/Logs/CookieDesktopPet.out.log" "$plist"
/usr/libexec/PlistBuddy -c "Set :StandardErrorPath $HOME/Library/Logs/CookieDesktopPet.err.log" "$plist"

launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
