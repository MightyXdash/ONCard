from __future__ import annotations

from dataclasses import dataclass
import re


MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
BARE_IMAGE_RE = re.compile(r"https?://\S+\.(?:png|jpg|jpeg|gif|webp)(?:\?\S+)?", re.IGNORECASE)


@dataclass
class UpdateNotesContent:
    text: str
    image_urls: list[str]


def parse_update_notes(markdown: str) -> UpdateNotesContent:
    if not markdown.strip():
        return UpdateNotesContent(
            text="A new ONCards update is available.",
            image_urls=[],
        )

    image_urls: list[str] = []
    working = markdown

    for match in MARKDOWN_IMAGE_RE.findall(markdown):
        if match not in image_urls:
            image_urls.append(match)
    working = MARKDOWN_IMAGE_RE.sub("", working)

    for match in BARE_IMAGE_RE.findall(working):
        if match not in image_urls:
            image_urls.append(match)
        working = working.replace(match, "")

    lines: list[str] = []
    for raw_line in working.splitlines():
        line = raw_line.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*+]\s*", "• ", line)
        line = re.sub(r"^\s*\d+\.\s*", "", line)
        line = line.replace("**", "").replace("__", "").replace("`", "")
        line = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", line)
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    if not cleaned:
        cleaned = "A new ONCards update is available."
    return UpdateNotesContent(text=cleaned, image_urls=image_urls[:3])
