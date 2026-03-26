from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from studymate.services.embedding_service import EmbeddingService
from studymate.services.ollama_service import OllamaError


class EmbeddingWorker(QThread):
    progress = Signal(str, int, int)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, *, cards: list[dict], embedding_service: EmbeddingService) -> None:
        super().__init__()
        self.cards = list(cards)
        self.embedding_service = embedding_service

    def run(self) -> None:
        results: list[dict] = []
        total = len(self.cards)
        try:
            for index, card in enumerate(self.cards, start=1):
                if self.isInterruptionRequested():
                    break
                label = str(card.get("title") or card.get("question") or "Card").strip() or "Card"
                self.progress.emit(label, index, total)
                self.embedding_service.ensure_card_embedding(card)
                results.append(card)
        except OllamaError as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(results)
