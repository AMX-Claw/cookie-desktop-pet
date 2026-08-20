#!/bin/zsh
set -eu

root="${0:A:h}"
venv="$root/.asset-venv"

find_python() {
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

python="$(find_python)" || {
  echo "需要 Python 3。请先从 python.org 或 Homebrew 安装。"
  read -k 1 "?按任意键关闭…"
  exit 1
}

if [[ ! -x "$venv/bin/python" ]]; then
  "$python" -m venv "$venv"
fi
"$venv/bin/python" -m pip install -r "$root/requirements-assets.txt"
"$venv/bin/python" "$root/tools/cut_layers.py"
"$venv/bin/python" "$root/tools/make_states.py"
"$venv/bin/python" "$root/tools/build_compact.py"

echo
echo "图片处理完成：assets/ 与 assets_compact/ 已更新。"
read -k 1 "?按任意键关闭…"
