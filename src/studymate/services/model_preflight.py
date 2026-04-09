from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
import threading
import time

from PySide6.QtWidgets import QMessageBox, QWidget

from studymate.services.data_store import DataStore
from studymate.services.model_registry import MODELS, non_embedding_llm_keys
from studymate.services.ollama_service import OllamaService


@dataclass(frozen=True)
class ModelPreflightSnapshot:
    checked_at: str
    cli_available: bool
    api_reachable: bool
    installed_tags: set[str]
    installed_models: dict[str, bool]
    error: str = ""
    cloud_mode: bool = False
    cloud_key_present: bool = False

    def has_model(self, model_key: str) -> bool:
        spec = MODELS.get(model_key)
        if spec is None:
            return False
        if any(tag in self.installed_tags for tag in [spec.primary_tag, *spec.candidate_tags]):
            return True
        return bool(self.installed_models.get(model_key, False))


class ModelPreflightService:
    def __init__(self, datastore: DataStore, ollama: OllamaService, *, ttl_seconds: float = 6.0) -> None:
        self.datastore = datastore
        self.ollama = ollama
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._cached_snapshot: ModelPreflightSnapshot | None = None
        self._cached_at = 0.0

    def snapshot(self, *, force: bool = False) -> ModelPreflightSnapshot:
        with self._lock:
            if not force and self._cached_snapshot is not None and (time.monotonic() - self._cached_at) <= self.ttl_seconds:
                return self._cached_snapshot

            ai_settings = self.datastore.load_ai_settings()
            cloud_mode = bool(ai_settings.get("ollama_cloud_enabled", False))
            cloud_key = str(ai_settings.get("ollama_cloud_api_key", "")).strip()
            self.ollama.configure_from_ai_settings(ai_settings)

            cli_available = shutil.which("ollama") is not None
            api_reachable = False
            installed_tags: set[str] = set()
            error = ""
            if cloud_mode:
                cli_available = True
                if not cloud_key:
                    error = "Cloud mode is enabled, but no API key is set."
                else:
                    api_reachable = self.ollama.ping(use_cloud=True, api_key=cloud_key)
                    try:
                        installed_tags = self.ollama.installed_tags(use_cloud=True, api_key=cloud_key)
                    except Exception as exc:
                        error = str(exc)
            elif cli_available:
                api_reachable = self.ollama.ping(use_cloud=False)
                try:
                    installed_tags = self.ollama.installed_tags(use_cloud=False)
                except Exception as exc:
                    error = str(exc)

            setup = self.datastore.load_setup()
            installed_models = dict(setup.get("installed_models", {}))
            text_keys = set(non_embedding_llm_keys())
            for key, spec in MODELS.items():
                detected = any(
                    tag in installed_tags for tag in [spec.primary_tag, *spec.candidate_tags]
                )
                if cloud_mode:
                    if key in text_keys:
                        installed_models[key] = detected
                    else:
                        installed_models[key] = bool(installed_models.get(key, False))
                elif cli_available and not error:
                    # Source of truth: live installed-tag list from Ollama.
                    installed_models[key] = detected
                elif cli_available and error:
                    # If live lookup failed, avoid stale "installed" flags.
                    installed_models[key] = False
                else:
                    installed_models[key] = bool(installed_models.get(key, False))

            if installed_models != dict(setup.get("installed_models", {})):
                setup["installed_models"] = installed_models
                self.datastore.save_setup(setup)

            snapshot = ModelPreflightSnapshot(
                checked_at=datetime.now(timezone.utc).isoformat(),
                cli_available=cli_available,
                api_reachable=api_reachable,
                installed_tags=installed_tags,
                installed_models=installed_models,
                error=error,
                cloud_mode=cloud_mode,
                cloud_key_present=bool(cloud_key),
            )
            self._cached_snapshot = snapshot
            self._cached_at = time.monotonic()
            return snapshot

    def invalidate(self) -> None:
        with self._lock:
            self._cached_snapshot = None
            self._cached_at = 0.0

    def has_model(self, model_key: str, *, force: bool = False) -> bool:
        return self.snapshot(force=force).has_model(model_key)

    def semantic_search_available(self, *, force: bool = False) -> bool:
        return self.has_model("nomic_embed_text_v2_moe", force=force)

    def gemma_available(self, *, force: bool = False) -> bool:
        return self.has_model("gemma3_4b", force=force)

    def require_model(self, model_key: str, *, parent: QWidget | None, feature_name: str, force: bool = False) -> bool:
        snap = self.snapshot(force=force)
        if snap.has_model(model_key):
            return True
        spec = MODELS.get(model_key)
        tag = spec.primary_tag if spec is not None else model_key
        title = "Model required"
        if snap.cloud_mode:
            if not snap.cloud_key_present:
                message = (
                    f"{feature_name} needs the `{tag}` cloud model.\n\n"
                    "Open Settings > AI, enable cloud inference, and paste your Ollama API key."
                )
            elif not snap.api_reachable:
                message = (
                    f"{feature_name} needs the `{tag}` cloud model, but ONCard could not reach Ollama Cloud.\n\n"
                    "Check your internet/API key in Settings > AI, then refresh model status."
                )
            else:
                message = (
                    f"{feature_name} needs the `{tag}` cloud model.\n\n"
                    "Open Settings > AI and choose that cloud model before using this feature."
                )
        elif not snap.cli_available:
            message = (
                f"{feature_name} needs Ollama and the `{tag}` model.\n\n"
                "Install Ollama first, then open Settings > AI to install the model."
            )
        elif not snap.api_reachable and not snap.installed_tags:
            message = (
                f"{feature_name} needs the `{tag}` model, but ONCard could not reach Ollama right now.\n\n"
                "Start Ollama, then open Settings > AI to install or refresh models."
            )
        else:
            message = (
                f"{feature_name} needs the `{tag}` model.\n\n"
                "Open Settings > AI and install it before using this feature."
            )
        QMessageBox.information(parent, title, message)
        return False
