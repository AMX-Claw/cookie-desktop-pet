#!/bin/zsh
set -eu

label="com.aque.cookie-desktop-pet"
runtime="$HOME/Library/Application Support/CookieDesktopPet"
plist="$HOME/Library/LaunchAgents/$label.plist"
stamp="$(date +%Y%m%d-%H%M%S)"
trash="$HOME/.Trash/CookieDesktopPet-uninstalled-$stamp"

launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
mkdir -p "$trash"
for path in "$runtime" "$plist" "$HOME/.cookie_desktop_pet_state.json" "$HOME/.cookie_desktop_pet.lock" "$HOME/.cookie_desktop_pet.pid"; do
  if [[ -e "$path" ]]; then
    mv "$path" "$trash/"
  fi
done

echo "Cookie 已停止，程序和状态已移到废纸篓，可恢复。"
read -k 1 "?按任意键关闭…"
