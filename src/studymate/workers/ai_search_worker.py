from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.workers.prompt_context import with_oncard_context


class AiSearchWorker(QThread):
    chunk = Signal(int, str)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(
        self,
        *,
        request_id: int,
        ollama: OllamaService,
        model: str,
        prompt: str,
        context_length: int = 8192,
        profile_context: dict | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.ollama = ollama
        self.model = model
        self.prompt = prompt
        self.context_length = context_length
        self.profile_context = profile_context or {}
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        system_prompt = with_oncard_context(
            (
            "You are a compact search-style answer engine. "
            "Respond in clean Markdown only. "
            "Be factual, short, structured, and non-conversational. "
            "Do not ramble. Do not ask follow-up questions. Do not add filler."
            ),
            feature="Ask AI search answer",
            profile_context=self.profile_context,
        )
        user_prompt = (
            "Answer the user query directly using this exact shape:\n"
            "# Short answer title\n"
            "## Key points\n"
            "- 2 to 4 bullets only\n"
            "## Quick explanation\n"
            "- 2 to 4 bullets only\n"
            "## Takeaway\n"
            "- 1 short bullet\n\n"
            "Rules:\n"
            "- Maximum 170 words.\n"
            "- Use short bullets, not long paragraphs.\n"
            "- Use code blocks only if the query explicitly needs code.\n"
            "- If uncertain, say so in one short bullet and continue.\n"
            "- Do not include chatter, encouragement, or extra sections.\n\n"
            "Markdown validity rules:\n"
            "- Put a space after heading markers (example: `## Key points`).\n"
            "- Keep headings and bullets on separate lines.\n"
            "- Leave one blank line between sections.\n"
            "- Start every bullet with `- ` on its own line.\n"
            "- Put a space after punctuation when followed by a word.\n\n"
            "- Never merge adjacent words; keep natural word spacing.\n\n"
            f"User query:\n{self.prompt.strip()}"
        )
        markdown = ""
        last_emit = 0.0
        last_emitted_markdown = ""
        emit_interval = 1.0 / 45.0
        try:
            for piece in self.ollama.stream_chat(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.35,
                extra_options={
                    "num_ctx": self.context_length,
                    "num_predict": 220,
                    "repeat_penalty": 1.15,
                    "top_p": 0.9,
                },
                should_stop=lambda: self._stop_requested,
            ):
                if self._stop_requested:
                    return
                markdown += piece
                now = time.perf_counter()
                if (
                    (now - last_emit) >= emit_interval
                    or piece.endswith("\n")
                    or len(markdown) - len(last_emitted_markdown) >= 32
                ):
                    self.chunk.emit(self.request_id, markdown)
                    last_emitted_markdown = markdown
                    last_emit = now
        except OllamaError as exc:
            if not self._stop_requested:
                self.failed.emit(self.request_id, str(exc))
            return
        if not self._stop_requested:
            if markdown and markdown != last_emitted_markdown:
                self.chunk.emit(self.request_id, markdown)
            self.finished.emit(self.request_id)
