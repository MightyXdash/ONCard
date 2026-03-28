from __future__ import annotations

import ctypes
from pathlib import Path
import subprocess
import sys


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _find_inner_installer() -> Path | None:
    bundle = _bundle_dir()
    preferred = sorted(bundle.glob("ONCard-Installer-*.exe"))
    if preferred:
        return preferred[0]
    candidates = sorted(bundle.glob("*.exe"))
    if candidates:
        return candidates[0]
    return None


def _show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "ONCard Setup", 0x10)


def main() -> int:
    installer = _find_inner_installer()
    if installer is None:
        _show_error("The embedded ONCard installer could not be found.")
        return 1

    args = [arg for arg in sys.argv[1:] if arg]
    if not any(arg.upper() == "/UPDATEFLOW" for arg in args):
        args.append("/UPDATEFLOW")

    completed = subprocess.run([str(installer), *args], check=False)
    return int(completed.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
