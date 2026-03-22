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
        self.data = data_root or (root / "data")
        self.local_data = local_data_root or self.data
        self.config = self.data / "config"
        self.subjects = self.data / "subjects"
        self.study_history = self.data / "study_history"
        self.backups = self.data / "backups"
        self.updates = self.local_data / "updates"
        self.runtime = self.local_data / "runtime"

        self.setup_config = self.config / "setup.json"
        self.profile_config = self.config / "profile.json"
        self.study_history_file = self.study_history / "attempts.json"
        self.update_state = self.runtime / "update_state.json"

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
            data_root = roaming / APP_NAME
            local_data_root = local / APP_NAME
        else:
            data_root = root / "data"
            local_data_root = data_root

        return cls(
            root,
            bundle_root=bundle_root,
            install_root=install_root,
            data_root=data_root,
            local_data_root=local_data_root,
            is_frozen=is_frozen,
        )

    def ensure(self) -> None:
        paths_to_create = [
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
                *paths_to_create,
            ]

        for path in paths_to_create:
            path.mkdir(parents=True, exist_ok=True)
