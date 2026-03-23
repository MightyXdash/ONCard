from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class PackagedUpdateContent:
    prompt_banner: Path
    prompt_short_description: str
    whats_new_banner: Path
    whats_new_title: str
    whats_new_description: str
    whats_new_showcase: Path
    whats_new_points: list[str]
    whats_new_closing_banner: Path


def load_packaged_update_content(assets_root: Path, version: str) -> PackagedUpdateContent:
    updates_root = assets_root / "updates"
    common_manifest = _read_manifest(updates_root / "common" / "manifest.json")
    version_manifest = _read_manifest(updates_root / version / "manifest.json")

    prompt_scope = _merge(common_manifest.get("prompt", {}), version_manifest.get("prompt", {}))
    whats_new_scope = _merge(common_manifest.get("whats_new", {}), version_manifest.get("whats_new", {}))

    common_dir = updates_root / "common"
    version_dir = updates_root / version

    prompt_banner_name = str(prompt_scope.get("banner", "update_prompt_banner_16x9.png"))
    whats_new_banner_name = str(whats_new_scope.get("top_banner", "whats_new_top_banner_16x9.png"))
    showcase_name = str(whats_new_scope.get("showcase_banner", "whats_new_showcase_16x9.png"))
    closing_name = str(whats_new_scope.get("closing_banner", "whats_new_closing_banner_16x9.png"))

    return PackagedUpdateContent(
        prompt_banner=_resolve_asset(version_dir, common_dir, prompt_banner_name),
        prompt_short_description=str(prompt_scope.get("short_description", "A smoother ONCard update is ready for you.")),
        whats_new_banner=_resolve_asset(version_dir, common_dir, whats_new_banner_name),
        whats_new_title=str(whats_new_scope.get("title", f"Welcome to ONCard {version}")),
        whats_new_description=str(whats_new_scope.get("description", "A cleaner update with new features and polish.")),
        whats_new_showcase=_resolve_asset(version_dir, common_dir, showcase_name),
        whats_new_points=[str(item) for item in whats_new_scope.get("points", [])][:6],
        whats_new_closing_banner=_resolve_asset(version_dir, common_dir, closing_name),
    )


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    merged.update(override)
    return merged


def _resolve_asset(version_dir: Path, common_dir: Path, file_name: str) -> Path:
    version_path = version_dir / file_name
    if version_path.exists():
        return version_path
    return common_dir / file_name
