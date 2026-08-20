#!/usr/bin/env python3
"""Resize every generated transparent layer for the tiny desktop renderer."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets"
OUTPUT = ROOT / "assets_compact"
WIDTH = 190
HEIGHT = 214


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    paths = sorted(SOURCE.glob("*.png"))
    if not paths:
        raise SystemExit("No generated PNG files found in assets/. Run the full pipeline.")
    for path in paths:
        output = OUTPUT / path.name
        subprocess.run(
            ["/usr/bin/sips", "-z", str(HEIGHT), str(WIDTH), str(path), "--out", str(output)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        print(f"{path.name}: 950x1070 -> {WIDTH}x{HEIGHT}")


if __name__ == "__main__":
    main()
