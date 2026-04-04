from __future__ import annotations

import os
from pathlib import Path
import sys

from studymate.constants import APP_NAME


class AppPaths:
    def __init__(
        self,
        root: Path,
        *,
        bundle_root: Path | None = None,
        install_root: Path | None = None,
        data_root: Path | None = None,
        local_data_root: Path | None = None,
        base_data_root: Path | None = None,
        base_local_data_root: Path | None = None,
        account_id: str = "",
        is_frozen: bool = False,
    ) -> None:
        self.root = root
        self.bundle_root = bundle_root or root
        self.install_root = install_root or root
        self.is_frozen = is_frozen
        self.src = root / "src"
        self.assets = self.bundle_root / "assets"
        self.icons = self.assets / "icons"
        self.banners = self.assets / "banners"
        self.startup_assets = self.assets / "startup"
        self.data = data_root or (root / "data")
        self.local_data = local_data_root or self.data
        self.base_data = base_data_root or self.data
        self.base_local_data = base_local_data_root or self.local_data
        self.account_id = str(account_id or "").strip()
        self.accounts = self.base_data / "accounts"
        self.accounts_index_file = self.accounts / "accounts_index.json"
        self.config = self.data / "config"
        self.subjects = self.data / "subjects"
        self.study_history = self.data / "study_history"
        self.backups = self.data / "backups"
        self.updates = self.local_data / "updates"
        self.runtime = self.local_data / "runtime"

        self.setup_config = self.config / "setup.json"
        self.profile_config = self.config / "profile.json"
        self.ai_settings_config = self.config / "ai_settings.json"
        self.study_history_file = self.study_history / "attempts.json"
        self.database_file = self.data / "oncard.sqlite"
        self.embedding_cache_file = self.runtime / "embedding_cache.json"
        self.startup_video = self.startup_assets / "startup_loop.mp4"
        self.update_state = self.runtime / "update_state.json"

    def for_account(self, account_id: str) -> "AppPaths":
        account = str(account_id or "").strip()
        if not account:
            raise ValueError("account_id is required")
        account_root = self.accounts / account
        # Keep account state in one root so import/export can copy the full account cleanly.
        return AppPaths(
            self.root,
            bundle_root=self.bundle_root,
            install_root=self.install_root,
            data_root=account_root,
            local_data_root=account_root,
            base_data_root=self.base_data,
            base_local_data_root=self.base_local_data,
            account_id=account,
            is_frozen=self.is_frozen,
        )

    @classmethod
    def from_runtime(cls, root: Path) -> "AppPaths":
        is_frozen = bool(getattr(sys, "frozen", False))
        install_root = Path(sys.executable).resolve().parent if is_frozen else root
        bundle_candidates: list[Path] = []

        if is_frozen:
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                bundle_candidates.append(Path(meipass))
            bundle_candidates.append(install_root)
        else:
            bundle_candidates.append(root)

        bundle_root = next(
            (candidate for candidate in bundle_candidates if (candidate / "assets").exists()),
            bundle_candidates[0],
        )

        if is_frozen:
            roaming = Path(os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming")))
            local = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            data_root = _select_roaming_data_root(roaming / APP_NAME, roaming / "ONCards")
            local_data_root = _select_local_data_root(local / APP_NAME, local / "ONCards")
        else:
            data_root = root / "data"
            local_data_root = data_root

        return cls(
            root,
            bundle_root=bundle_root,
            install_root=install_root,
            data_root=data_root,
            local_data_root=local_data_root,
            base_data_root=data_root,
            base_local_data_root=local_data_root,
            is_frozen=is_frozen,
        )

    def ensure(self) -> None:
        paths_to_create = [
            self.accounts,
            self.config,
            self.subjects,
            self.study_history,
            self.backups,
            self.updates,
            self.runtime,
        ]
        if not self.is_frozen:
            paths_to_create = [
                self.icons / "app",
                self.icons / "setup",
                self.icons / "create",
                self.icons / "study",
                self.icons / "common",
                self.banners,
                self.startup_assets,
                *paths_to_create,
            ]

        for path in paths_to_create:
            path.mkdir(parents=True, exist_ok=True)


def _select_roaming_data_root(primary: Path, legacy: Path) -> Path:
    primary_has_data = _has_roaming_user_data(primary)
    legacy_has_data = _has_roaming_user_data(legacy)
    if legacy_has_data and not primary_has_data:
        return legacy
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def _select_local_data_root(primary: Path, legacy: Path) -> Path:
    primary_has_state = _has_local_user_state(primary)
    legacy_has_state = _has_local_user_state(legacy)
    if legacy_has_state and not primary_has_state:
        return legacy
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def _has_roaming_user_data(root: Path) -> bool:
    markers = [
        root / "config" / "setup.json",
        root / "config" / "profile.json",
        root / "subjects",
        root / "study_history" / "attempts.json",
    ]
    return any(marker.exists() for marker in markers)


def _has_local_user_state(root: Path) -> bool:
    markers = [
        root / "runtime" / "update_state.json",
        root / "runtime",
        root / "updates",
    ]
    return any(marker.exists() for marker in markers)
