from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from studymate.services.ollama_service import OllamaError, OllamaService


class FollowUpWorker(QThread):
    chunk = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        *,
        ollama: OllamaService,
        model: str,
        prompt: str,
        context: str,
        context_length: int = 8192,
    ) -> None:
        super().__init__()
        self.ollama = ollama
        self.model = model
        self.prompt = prompt
        self.context = context
        self.context_length = context_length

    def run(self) -> None:
        system_prompt = "You are a friendly study coach. Give concise practical follow-up advice."
        user_prompt = f"{self.context}\n\nFollow-up request:\n{self.prompt}"
        text = ""
        try:
            for piece in self.ollama.stream_chat(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                extra_options={"num_ctx": self.context_length},
            ):
                text += piece
                self.chunk.emit(text)
        except OllamaError as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit()
