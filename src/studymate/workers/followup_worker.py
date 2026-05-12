from __future__ import annotations

import re

from PySide6.QtCore import QThread, Signal

from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.utils.prompt_files import follow_up_study_mode_prompt


class FollowUpWorker(QThread):
    chunk = Signal(str)
    thinking = Signal(str)
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
        profile_context: dict | None = None,
        think: bool = False,
    ) -> None:
        super().__init__()
        self.ollama = ollama
        self.model = model
        self.prompt = prompt
        self.context = context
        self.context_length = context_length
        self.profile_context = profile_context or {}
        self.think = bool(think)

    @staticmethod
    def _clean_thinking_title(title: str) -> str:
        text = re.sub(r"^\s*\d+\s*\.?\s*", "", str(title or ""))
        text = re.sub(r"\[[^\]]*(?:\]|$)|\([^)]*(?:\)|$)", "", text)
        text = re.sub(r"[:*#]", "", text)
        return " ".join(text.split()).strip()

    def _thinking_title_from_buffer(self, text: str) -> str:
        matches = list(re.finditer(r"(?m)^\s*\d+\s*\.?\s+([^\n]{2,120})", text))
        for match in reversed(matches):
            title = self._clean_thinking_title(match.group(1))
            if title:
                return title
        return "Thinking"

    @staticmethod
    def _append_stream_text(current: str, piece: str) -> str:
        chunk = str(piece or "")
        if not chunk:
            return current
        if chunk.startswith(current):
            return chunk
        if current.endswith(chunk):
            return current
        overlap_limit = min(len(current), len(chunk))
        for size in range(overlap_limit, 0, -1):
            if current.endswith(chunk[:size]):
                return current + chunk[size:]
        return current + chunk

    @staticmethod
    def _visible_answer_from_raw(raw_text: str) -> tuple[str, bool]:
        text = str(raw_text or "")
        end = text.rfind("</think>")
        if end >= 0:
            return text[end + len("</think>") :], True
        if "<think>" in text:
            return "", False
        return text, True

    @staticmethod
    def _looks_like_reasoning_line(line: str) -> bool:
        stripped = str(line or "").strip()
        if not stripped:
            return False
        if re.match(r"^\d+\s*\.?\s+\S", stripped):
            return True
        if stripped[:1] in ("[", "("):
            return True
        if re.match(r"^(?:[-*]|\#)\s*\S", stripped):
            return True
        return False

    @classmethod
    def _strip_leading_reasoning_outline(cls, text: str) -> tuple[str, bool]:
        lines = str(text or "").splitlines()
        index = 0
        consumed_any = False
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped:
                if consumed_any:
                    look_ahead = index + 1
                    while look_ahead < len(lines) and not lines[look_ahead].strip():
                        look_ahead += 1
                    if look_ahead < len(lines) and not cls._looks_like_reasoning_line(lines[look_ahead]):
                        return "\n".join(lines[look_ahead:]).lstrip(), True
                    index += 1
                    continue
                break
            if not re.match(r"^\d+\s*\.?\s+\S", stripped):
                break
            consumed_any = True
            index += 1
            while index < len(lines):
                stripped = lines[index].strip()
                if not stripped:
                    look_ahead = index + 1
                    while look_ahead < len(lines) and not lines[look_ahead].strip():
                        look_ahead += 1
                    if look_ahead < len(lines) and not cls._looks_like_reasoning_line(lines[look_ahead]):
                        return "\n".join(lines[look_ahead:]).lstrip(), True
                    index += 1
                    continue
                if re.match(r"^\d+\s*\.?\s+\S", stripped):
                    break
                if cls._looks_like_reasoning_line(stripped):
                    index += 1
                    continue
                return "\n".join(lines[index:]).lstrip(), True
        remainder = "\n".join(lines[index:]).lstrip()
        return remainder, consumed_any

    @classmethod
    def _extract_visible_answer(cls, raw_text: str, *, saw_thinking: bool, final: bool = False) -> tuple[str, bool]:
        answer, answer_open = cls._visible_answer_from_raw(raw_text)
        if not answer_open:
            return "", False
        candidate = str(answer or "")
        if saw_thinking:
            stripped_candidate, consumed_outline = cls._strip_leading_reasoning_outline(candidate)
            if consumed_outline:
                candidate = stripped_candidate
            preview = candidate.lstrip()
            if not final and (not preview or cls._looks_like_reasoning_line(preview.splitlines()[0])):
                return "", False
        return candidate, True

    def run(self) -> None:
        system_prompt = follow_up_study_mode_prompt()
        user_prompt = f"{self.context}\n\nFollow-up request:\n{self.prompt}"
        content_buffer = ""
        thinking_text = ""
        last_answer = ""
        saw_thinking = False
        answer_started = False
        try:
            stream = self.ollama.stream_chat_events(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                extra_options={"num_ctx": self.context_length},
                think=self.think,
            ) if self.think else (
                ("content", piece)
                for piece in self.ollama.stream_chat(
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.3,
                    extra_options={"num_ctx": self.context_length},
                    think=False,
                )
            )
            for kind, piece in stream:
                if kind == "thinking":
                    saw_thinking = True
                    thinking_text = self._append_stream_text(thinking_text, piece)
                    self.thinking.emit(self._thinking_title_from_buffer(thinking_text))
                    continue
                content_buffer = self._append_stream_text(content_buffer, piece)
                answer, ready = self._extract_visible_answer(content_buffer, saw_thinking=saw_thinking, final=False)
                if self.think and not ready:
                    continue
                if saw_thinking and ready and answer and not answer_started:
                    self.thinking.emit("Planning the next move")
                    answer_started = True
                if answer != last_answer:
                    last_answer = answer
                    self.chunk.emit(answer)
        except OllamaError as exc:
            self.failed.emit(str(exc))
            return
        answer, _ready = self._extract_visible_answer(content_buffer, saw_thinking=saw_thinking, final=True)
        if answer and answer != last_answer:
            self.chunk.emit(answer)
        self.finished.emit()
