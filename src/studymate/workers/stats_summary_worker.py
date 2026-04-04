from __future__ import annotations

import json

from PySide6.QtCore import QThread, Signal

from studymate.services.ollama_service import OllamaError, OllamaService


STATS_SUMMARY_SYSTEM_PROMPT = (
    "You are ONCard's performance analyst. Write a concise third-person study summary about the student using only the provided app data.\n\n"
    "Rules:\n"
    "- Always refer to the student in third person (never 'you').\n"
    "- Use plain markdown with short sections and bullets.\n"
    "- Ground every claim in supplied metrics; do not invent facts.\n"
    "- Mention strengths, weaknesses, and 2-4 concrete focus actions.\n"
    "- If data is sparse, explicitly say evidence is limited.\n"
    "- Keep tone supportive, direct, and practical.\n"
    "- Maximum 170 words."
)


class StatsSummaryWorker(QThread):
    chunk_received = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        ollama: OllamaService,
        profile: dict,
        summary_payload: dict,
        context_length: int,
        model: str = "gemma3:4b",
    ) -> None:
        super().__init__()
        self.ollama = ollama
        self.profile = profile
        self.summary_payload = summary_payload
        self.context_length = max(1024, int(context_length))
        self.model = model

    def run(self) -> None:
        user_prompt = (
            "Student profile:\n"
            f"{json.dumps(self.profile, ensure_ascii=False, indent=2)}\n\n"
            "Performance data:\n"
            f"{json.dumps(self.summary_payload, ensure_ascii=False, indent=2)}\n\n"
            "Write the summary now."
        )
        try:
            parts: list[str] = []
            for chunk in self.ollama.stream_chat(
                model=self.model,
                system_prompt=STATS_SUMMARY_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.25,
                extra_options={"num_ctx": self.context_length},
                timeout=180,
                should_stop=self.isInterruptionRequested,
            ):
                if self.isInterruptionRequested():
                    return
                if not chunk:
                    continue
                parts.append(chunk)
                self.chunk_received.emit(chunk)
        except OllamaError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive guard for thread safety
            self.failed.emit(str(exc))
            return
        self.finished.emit("".join(parts).strip())
