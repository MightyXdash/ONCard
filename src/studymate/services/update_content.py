from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class PackagedUpdateContent:
    prompt_banner: Path
    update_name: str
    learn_more_title: str
    subtitle: str
    summary_text: str
    banner1: Path
    text1: str
    banner2: Path | None
    text2: str


def load_packaged_update_content(assets_root: Path, version: str) -> PackagedUpdateContent:
    updates_root = assets_root / "updates"
    common_manifest = _read_manifest(updates_root / "common" / "manifest.json")
    version_manifest = _read_manifest(updates_root / version / "manifest.json")

    prompt_scope = _merge(common_manifest.get("prompt", {}), version_manifest.get("prompt", {}))
    post_install_scope = _merge(common_manifest.get("post_install", {}), version_manifest.get("post_install", {}))
    whats_new_scope = _merge(common_manifest.get("whats_new", {}), version_manifest.get("whats_new", {}))

    common_dir = updates_root / "common"
    version_dir = updates_root / version

    prompt_banner_name = str(prompt_scope.get("banner", "update_prompt_banner_16x9.png"))
    banner1_name = str(post_install_scope.get("banner1", whats_new_scope.get("top_banner", "whats_new_top_banner_16x9.png")))
    banner2_name = str(post_install_scope.get("banner2", whats_new_scope.get("showcase_banner", ""))).strip()
    update_name = str(post_install_scope.get("update_name", whats_new_scope.get("title", f"Welcome to ONCard {version}"))).strip()
    learn_more_title = str(whats_new_scope.get("title", update_name)).strip()
    subtitle = str(post_install_scope.get("subtitle", "")).strip()
    text1 = str(post_install_scope.get("text1", whats_new_scope.get("description", "A cleaner update with new features and polish."))).strip()
    text2 = str(post_install_scope.get("text2", "")).strip()
    if not text2:
        points = [str(item).strip() for item in whats_new_scope.get("points", []) if str(item).strip()]
        text2 = "\n".join(f"- {point}" for point in points)
    summary_text = str(post_install_scope.get("summary_text", text2 or text1)).strip()

    return PackagedUpdateContent(
        prompt_banner=_resolve_asset(version_dir, common_dir, prompt_banner_name),
        update_name=update_name or f"Welcome to ONCard {version}",
        learn_more_title=learn_more_title or update_name or f"Welcome to ONCard {version}",
        subtitle=subtitle,
        summary_text=summary_text,
        banner1=_resolve_asset(version_dir, common_dir, banner1_name),
        text1=text1 or "A cleaner update with new features and polish.",
        banner2=_resolve_optional_asset(version_dir, common_dir, banner2_name),
        text2=text2,
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


def _resolve_optional_asset(version_dir: Path, common_dir: Path, file_name: str) -> Path | None:
    if not file_name:
        return None
    version_path = version_dir / file_name
    if version_path.exists():
        return version_path
    common_path = common_dir / file_name
    if common_path.exists():
        return common_path
    return None
