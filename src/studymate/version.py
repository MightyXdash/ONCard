from __future__ import annotations

import re


APP_VERSION = "1.5.9"
APP_PUBLISHER = "QyrouLabs"
APP_DESCRIPTION = "opensource AI powered study app."
APP_INTERNAL_NAME = "ONCard"
APP_ORIGINAL_FILENAME = "ONCard.exe"
APP_COPYRIGHT = "Copyright (c) 2026 QyrouLabs"
GITHUB_REPO_SLUG = "MightyXdash/ONCard"
GITHUB_REPO_URL = "https://github.com/MightyXdash/ONCard"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO_SLUG}/releases"
INSTALLER_NAME_PREFIX = "ONCard-Setup"

_BETA_VERSION_PATTERN = re.compile(r"^(?P<core>\d+\.\d+\.\d+)\.beta$", re.IGNORECASE)


def normalize_release_version(raw: str) -> str:
    value = str(raw or "").strip()
    if value.lower().startswith("v"):
        value = value[1:]
    return value


def is_beta_version(raw: str) -> bool:
    return _BETA_VERSION_PATTERN.fullmatch(normalize_release_version(raw)) is not None


def pep440_version(raw: str) -> str:
    value = normalize_release_version(raw)
    match = _BETA_VERSION_PATTERN.fullmatch(value)
    if match is not None:
        return f"{match.group('core')}b0"
    return value


def app_name_with_release_channel(base_name: str = "ONCard", version: str | None = None) -> str:
    resolved = APP_VERSION if version is None else str(version)
    return f"{base_name} Beta" if is_beta_version(resolved) else base_name
