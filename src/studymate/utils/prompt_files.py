from __future__ import annotations

from pathlib import Path
import sys


FOLLOW_UP_STUDY_MODE_PROMPT_PATH = Path("prompts") / "Chat" / "system" / "follow_up" / "study_mode.md"


def _prompt_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parents[3])
    cwd = Path.cwd()
    if cwd not in roots:
        roots.append(cwd)
    return roots


def read_prompt_file(relative_path: str | Path) -> str:
    prompt_path = Path(relative_path)
    for root in _prompt_roots():
        candidate = root / prompt_path
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    searched = ", ".join(str(root / prompt_path) for root in _prompt_roots())
    raise FileNotFoundError(f"Prompt file not found: {prompt_path.as_posix()}. Searched: {searched}")


def follow_up_study_mode_prompt() -> str:
    return read_prompt_file(FOLLOW_UP_STUDY_MODE_PROMPT_PATH)
