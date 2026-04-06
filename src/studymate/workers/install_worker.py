from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from studymate.services.model_registry import MODELS
from studymate.services.ollama_service import OllamaService


class ModelInstallWorker(QThread):
    line = Signal(str)
    model_finished = Signal(str, bool, str)
    complete = Signal(dict)

    def __init__(self, model_keys: list[str], ollama: OllamaService, *, action: str = "install") -> None:
        super().__init__()
        self.model_keys = model_keys
        self.ollama = ollama
        self.action = action

    def run(self) -> None:
        status: dict[str, bool] = {}
        for key in self.model_keys:
            spec = MODELS[key]
            success = False
            used_tag = ""
            if self.action == "remove":
                self.line.emit(f"Removing {spec.display_name}...")
                for tag in spec.candidate_tags:
                    used_tag = tag
                    self.line.emit(f"Trying tag: {tag}")
                    if self.ollama.remove_model(tag, on_output=self.line.emit):
                        success = True
                        break
                    self.line.emit(f"Tag failed: {tag}")
            else:
                self.line.emit(f"Installing {spec.display_name}...")
                for tag in spec.candidate_tags:
                    used_tag = tag
                    self.line.emit(f"Trying tag: {tag}")
                    if self.ollama.pull_model(tag, on_output=self.line.emit):
                        success = True
                        break
                    self.line.emit(f"Tag failed: {tag}")
            status[key] = success
            self.model_finished.emit(key, success, used_tag)
        self.complete.emit(status)
