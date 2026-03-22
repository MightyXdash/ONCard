from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: make_icon.py <input_png> <output_ico>")

    source = Path(sys.argv[1]).resolve()
    target = Path(sys.argv[2]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(source).convert("RGBA")
    image.save(target, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
