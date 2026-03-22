from __future__ import annotations

from datetime import datetime
import shutil

from studymate.utils.paths import AppPaths


class BackupService:
    def __init__(self, paths: AppPaths, keep_versions: int = 5) -> None:
        self.paths = paths
        self.keep_versions = keep_versions

    def create_exit_backup(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.paths.backups / timestamp
        target.mkdir(parents=True, exist_ok=True)

        for source_dir in [self.paths.config, self.paths.subjects, self.paths.study_history]:
            if source_dir.exists():
                dest_dir = target / source_dir.name
                shutil.copytree(source_dir, dest_dir, dirs_exist_ok=True)

        backups = sorted([p for p in self.paths.backups.iterdir() if p.is_dir()])
        while len(backups) > self.keep_versions:
            to_remove = backups.pop(0)
            shutil.rmtree(to_remove, ignore_errors=True)
