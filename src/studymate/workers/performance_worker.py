from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from studymate.constants import PERFORMANCE_THRESHOLDS
from studymate.services.ollama_service import OllamaError, OllamaService


class PerformanceWorker(QThread):
    progress = Signal(str)
    sample = Signal(int, float)
    done = Signal(float, str)
    failed = Signal(str)

    def __init__(self, ollama: OllamaService, model: str = "gemma4:e2b") -> None:
        super().__init__()
        self.ollama = ollama
        self.model = model
        self.prompts = [
            "Summarize Newton's first law in one sentence.",
            "Explain why photosynthesis matters in 20 words.",
            "What is a quadratic equation? Keep it simple.",
            "Give one practical tip to memorize formulas.",
        ]

    @staticmethod
    def classify(avg_tps: float) -> str:
        if avg_tps >= PERFORMANCE_THRESHOLDS["best"][0]:
            return PERFORMANCE_THRESHOLDS["best"][2]
        if PERFORMANCE_THRESHOLDS["smooth"][0] <= avg_tps <= PERFORMANCE_THRESHOLDS["smooth"][1]:
            return PERFORMANCE_THRESHOLDS["smooth"][2]
        if PERFORMANCE_THRESHOLDS["normal"][0] <= avg_tps <= PERFORMANCE_THRESHOLDS["normal"][1]:
            return PERFORMANCE_THRESHOLDS["normal"][2]
        return PERFORMANCE_THRESHOLDS["poor"][2]

    def run(self) -> None:
        self.progress.emit(f"Running 4 model checks with {self.model}...")
        samples: list[float] = []
        for idx, prompt in enumerate(self.prompts, start=1):
            self.progress.emit(f"Question {idx}/4")
            try:
                tps = self.ollama.benchmark_tps(self.model, prompt)
            except OllamaError as exc:
                self.failed.emit(str(exc))
                return
            samples.append(tps)
            self.sample.emit(idx, tps)
        avg_tps = round(sum(samples) / len(samples), 2) if samples else 0.0
        self.done.emit(avg_tps, self.classify(avg_tps))
