from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService


class StartupWarmupWorker(QThread):
    progress = Signal(str, str, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, datastore: DataStore, preflight: ModelPreflightService) -> None:
        super().__init__()
        self.datastore = datastore
        self.preflight = preflight

    def run(self) -> None:
        try:
            setup = self.datastore.load_setup()
            performance = dict(setup.get("performance", {}))
            startup_workers = max(1, min(int(performance.get("startup_workers", 8) or 8), 8))
            warm_cache = bool(performance.get("warm_cache_on_startup", True))

            self.progress.emit("Loading SQL store", "Reading settings and profile...", 10)
            snapshot = self.datastore.startup_snapshot(
                visible_limit=48,
                startup_workers=startup_workers,
                persist=warm_cache,
            )
            self.progress.emit("Checking models", "Refreshing local model availability...", 76)
            model_snapshot = self.preflight.snapshot(force=True)
            snapshot["model_preflight"] = {
                "checked_at": model_snapshot.checked_at,
                "cli_available": model_snapshot.cli_available,
                "api_reachable": model_snapshot.api_reachable,
                "installed_tags": sorted(model_snapshot.installed_tags),
                "installed_models": dict(model_snapshot.installed_models),
                "error": model_snapshot.error,
            }
            self.progress.emit("Priming cards", "Hydrating visible cards and vector cache...", 92)
            self.progress.emit("Ready", "Startup warmup completed.", 100)
            self.finished.emit(snapshot)
        except Exception as exc:
            self.failed.emit(str(exc))
