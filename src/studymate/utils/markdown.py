from __future__ import annotations

import re


def cleanup_plain_text(text: str) -> str:
    value = text or ""
    value = value.replace("**", "")
    value = value.replace("__", "")
    value = value.replace("`", "")
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = value.replace("#", "")
    return value.strip()
