from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from PySide6.QtCore import QThread, Signal

from studymate.constants import files_to_cards_question_schema
from studymate.services.files_to_cards_service import (
    gemma_ctx_for_batch,
    normalize_sources,
    paper_ctx_for_units,
)
from studymate.services.model_registry import MODELS
from studymate.services.ollama_service import OllamaService
from studymate.utils.markdown import cleanup_plain_text


class FilesToCardsCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class FilesToCardsJob:
    run_id: str
    mode: str
    source_family: str
    file_paths: list[Path]
    requested_questions: int
    custom_instructions: str
    use_ocr: bool


class FilesToCardsWorker(QThread):
    activity = Signal(object)
    question_generated = Signal(str, str)
    completed = Signal(str, object)
    cancelled = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, *, job: FilesToCardsJob, ollama: OllamaService, runtime_root: Path) -> None:
        super().__init__()
        self.job = job
        self.ollama = ollama
        self.runtime_root = runtime_root

    def run(self) -> None:
        try:
            self._run_pipeline()
        except FilesToCardsCancelled:
            self.cancelled.emit(self.job.run_id, "Files To Cards stopped.")
        except Exception as exc:
            self.failed.emit(self.job.run_id, str(exc))

    def _run_pipeline(self) -> None:
        run_dir = self.runtime_root / "files_to_cards" / self.job.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        self._emit_status("Normalizing selected files...")
        normalized = normalize_sources(
            self.job.file_paths,
            source_family=self.job.source_family,
            run_dir=run_dir,
            on_status=self._emit_status,
        )
        self._ensure_running()
        if not normalized:
            raise RuntimeError("No usable pages or images were created from the selected files.")

        total_units = len(normalized)
        source_text_parts: list[str] = []
        if self.job.use_ocr:
            self._emit_status("Gemma OCR is extracting page text...")
            for page in normalized:
                self._ensure_running()
                page_text = self._ocr_page(page)
                source_text_parts.append(f"{page.label}\n{page_text}".strip())
        else:
            self._emit_status("OCR is off. Gemma Vision is reading the pages directly...")
            for page in normalized:
                self._ensure_running()
                page_text = self._summarize_page_without_ocr(page)
                source_text_parts.append(f"{page.label}\n{page_text}".strip())

        paper = self._run_paper_stage(source_text_parts, total_units)
        self._ensure_running()
        questions = self._run_gemma_stage(paper)
        self._ensure_running()
        self.completed.emit(self.job.run_id, questions)

    def _ocr_page(self, page) -> str:
        entry_key = f"{self.job.run_id}:ocr:{page.unit_index}"
        self._emit_status(f"OCR {page.unit_index}/{page.total_units}: {page.label}")

        while True:
            self._ensure_running()
            parts: list[str] = []
            restart_requested = False
            for chunk in self.ollama.stream_chat(
                model=MODELS["gemma3_4b"].primary_tag,
                system_prompt=(
                    "You are a careful OCR assistant. "
                    "First reason about what is visible, then transcribe only the visible content. "
                    "Do not invent or complete missing text. "
                    "If a word is unreadable, write [unclear]. "
                    "Return markdown with exactly these sections: ## Analysis and ## Plain Text."
                ),
                user_prompt=self._ocr_prompt_for_page(page),
                image_paths=[str(page.image_path)],
                temperature=0.0,
                extra_options={
                    "num_ctx": 8192,
                    "repeat_last_n": 256,
                    "repeat_penalty": 1.2,
                },
                timeout=300,
                should_stop=self.isInterruptionRequested,
            ):
                self._ensure_running()
                parts.append(chunk)
                combined = "".join(parts)
                self._emit_activity(
                    key=entry_key,
                    kind="reasoning",
                    title=f"Gemma OCR {page.unit_index}/{page.total_units}",
                    text=combined,
                )
                if _has_consecutive_repeated_word(combined, threshold=8) or _has_consecutive_repeated_line(
                    combined,
                    threshold=4,
                ):
                    restart_requested = True
                    self._emit_status(f"Gemma OCR repetition detected on {page.label}. Restarting this page...")
                    break

            if not restart_requested:
                combined = "".join(parts)
                plain_text = _extract_ocr_plain_text(combined)
                if not plain_text.strip():
                    plain_text = combined
                self._emit_activity(
                    key=f"{entry_key}:plain",
                    kind="markdown",
                    title=f"OCR Text {page.unit_index}/{page.total_units}",
                    text=plain_text,
                )
                return cleanup_plain_text(plain_text)

    @staticmethod
    def _ocr_prompt_for_page(page) -> str:
        if page.family == "images":
            return "OCR this image to plaintext."
        return "OCR this document to plaintext."

    def _summarize_page_without_ocr(self, page) -> str:
        entry_key = f"{self.job.run_id}:vision:{page.unit_index}"
        self._emit_status(f"Vision read {page.unit_index}/{page.total_units}: {page.label}")
        parts: list[str] = []
        for chunk in self.ollama.stream_chat(
            model=MODELS["gemma3_4b"].primary_tag,
            system_prompt=(
                "You are reading study notes from an image without using strict OCR. "
                "Describe only what is visibly present. "
                "Write plain text notes that preserve headings, short formulas, definitions, and key facts. "
                "Do not invent missing words or facts. "
                "If something is unclear, say [unclear]."
            ),
            user_prompt=(
                "Read this study page and turn it into plain text notes. "
                "Keep it concise but capture the important visible content."
            ),
            image_paths=[str(page.image_path)],
            temperature=0.1,
            extra_options={
                "num_ctx": 8192,
                "repeat_last_n": 256,
                "repeat_penalty": 1.2,
            },
            timeout=240,
            should_stop=self.isInterruptionRequested,
        ):
            self._ensure_running()
            parts.append(chunk)
            combined = "".join(parts)
            self._emit_activity(
                key=entry_key,
                kind="reasoning",
                title=f"Gemma Vision {page.unit_index}/{page.total_units}",
                text=combined,
            )
        summary = cleanup_plain_text("".join(parts))
        self._emit_activity(
            key=f"{entry_key}:plain",
            kind="markdown",
            title=f"Vision Notes {page.unit_index}/{page.total_units}",
            text=summary,
        )
        return summary

    def _run_paper_stage(self, source_text_parts: list[str], total_units: int) -> str:
        paper_buffer: list[str] = []
        ctx = paper_ctx_for_units(total_units)
        source_block = "\n\n".join(source_text_parts).strip()
        custom_block = self.job.custom_instructions.strip()
        user_prompt = (
            "Study the source notes carefully and prepare revision material.\n"
            f"Total inputs: {total_units}\n"
            f"Mode: {self.job.mode}\n"
            f"OCR enabled: {'yes' if self.job.use_ocr else 'no'}\n"
            "Return markdown with exactly these sections:\n"
            "## Analysis\n"
            "## Paper\n\n"
            "The paper must be between 750 and 2000 words, factual, cohesive, and helpful for later card generation.\n"
            "If some content is ambiguous, say so briefly instead of inventing facts.\n"
        )
        if custom_block:
            user_prompt += f"\nOptional question-style guidance for later stages:\n{custom_block}\n"
        user_prompt += f"\nSource notes:\n{source_block}\n"
        entry_key = f"{self.job.run_id}:paper"
        self._emit_status("Gemma is building the paper...")

        while True:
            self._ensure_running()
            paper_buffer.clear()
            restart_requested = False
            for chunk in self.ollama.stream_chat(
                model=MODELS["gemma3_4b"].primary_tag,
                system_prompt=(
                    "You are an expert study-material synthesizer. "
                    "Do not loop or repeat the same word over and over. "
                    "Use plain markdown headings only."
                ),
                user_prompt=user_prompt,
                temperature=0.2,
                extra_options={"num_ctx": ctx},
                timeout=420,
                should_stop=self.isInterruptionRequested,
            ):
                self._ensure_running()
                paper_buffer.append(chunk)
                combined = "".join(paper_buffer)
                self._emit_activity(
                    key=entry_key,
                    kind="reasoning",
                    title="Gemma Paper",
                    text=combined,
                )
                if _has_consecutive_repeated_word(_analysis_section(combined), threshold=8):
                    restart_requested = True
                    self._emit_status("Gemma repeated itself. Restarting the paper stage...")
                    break
            if not restart_requested:
                break

        combined = "".join(paper_buffer)
        paper = _extract_paper(combined)
        if not paper.strip():
            raise RuntimeError("Gemma did not return a paper.")
        self._emit_activity(
            key=f"{self.job.run_id}:paper-final",
            kind="markdown",
            title="Paper",
            text=paper,
        )
        self._emit_status("Paper ready. Moving into question generation...")
        return paper

    def _run_gemma_stage(self, research_paper: str) -> list[str]:
        questions: list[str] = []
        batch_index = 0
        remaining = self.job.requested_questions

        while remaining > 0:
            self._ensure_running()
            batch_index += 1
            batch_size = min(4, remaining)
            ctx = gemma_ctx_for_batch(batch_index)
            self._emit_status(f"Generating question batch {batch_index}...")
            batch_questions = self._collect_gemma_batch(
                research_paper=research_paper,
                existing_questions=questions,
                batch_size=batch_size,
                ctx=ctx,
            )
            for question in batch_questions:
                self.question_generated.emit(self.job.run_id, question)

            questions.extend(batch_questions)
            if len(questions) > self.job.requested_questions:
                questions = questions[: self.job.requested_questions]
            remaining = self.job.requested_questions - len(questions)

        return questions

    def _collect_gemma_batch(self, *, research_paper: str, existing_questions: list[str], batch_size: int, ctx: int) -> list[str]:
        collected: list[str] = []
        attempt = 0

        while len(collected) < batch_size:
            self._ensure_running()
            attempt += 1
            needed = batch_size - len(collected)
            request_size = min(4, max(needed, batch_size))
            schema = files_to_cards_question_schema(request_size)
            prior_questions = "\n".join(f"- {question}" for question in [*existing_questions, *collected]) or "None yet."
            prompt = (
                f"Research paper:\n{research_paper}\n\n"
                f"Previously generated questions:\n{prior_questions}\n\n"
                f"Generate exactly {request_size} new study questions.\n"
                "Questions should usually be 5-40 words. If a question is genuinely complex, it can be 20-75 words.\n"
                "Avoid markdown formatting, numbering, duplicates, and paraphrases of earlier questions.\n"
            )
            if self.job.custom_instructions.strip():
                prompt += f"\nOptional guidance:\n{self.job.custom_instructions.strip()}\n"

            self._emit_status(f"Gemma batch attempt {attempt}: collecting {needed} more question(s)...")
            result = self.ollama.stream_structured_chat(
                model=MODELS["gemma3_4b"].primary_tag,
                system_prompt=(
                    "Return only strict JSON matching the schema. "
                    "Write concise school-study questions with natural wording."
                ),
                user_prompt=prompt,
                schema=schema,
                temperature=0.1,
                extra_options={"num_ctx": ctx},
                timeout=240,
                should_stop=self.isInterruptionRequested,
            )

            added_this_round = 0
            for raw_question in result.get("questions", []):
                question = _normalize_question(str(raw_question))
                if not question:
                    continue
                if question in existing_questions or question in collected:
                    continue
                collected.append(question)
                added_this_round += 1
                if len(collected) >= batch_size:
                    break

            if len(collected) > batch_size:
                collected = collected[:batch_size]

            if added_this_round == 0 and attempt >= 8:
                raise RuntimeError("Gemma could not generate enough unique questions after multiple retries.")

        return collected[:batch_size]

    def _ensure_running(self) -> None:
        if self.isInterruptionRequested():
            raise FilesToCardsCancelled()

    def _emit_status(self, text: str) -> None:
        self._emit_activity(kind="status", title="Files To Cards", text=text)

    def _emit_activity(self, *, kind: str, title: str, text: str, key: str | None = None) -> None:
        self.activity.emit(
            {
                "run_id": self.job.run_id,
                "key": key or "",
                "kind": kind,
                "title": title,
                "text": text,
            }
        )


def _analysis_section(text: str) -> str:
    lower = text.lower()
    paper_idx = lower.find("## research paper")
    if paper_idx == -1:
        return text
    return text[:paper_idx]


def _extract_research_paper(text: str) -> str:
    match = re.search(r"##\s*Research Paper\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_paper(text: str) -> str:
    match = re.search(r"##\s*Paper\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_ocr_plain_text(text: str) -> str:
    match = re.search(r"##\s*Plain Text\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _has_consecutive_repeated_word(text: str, threshold: int = 8) -> bool:
    words = re.findall(r"[A-Za-z0-9']+", text.lower())
    if len(words) < threshold:
        return False
    count = 1
    for idx in range(1, len(words)):
        if words[idx] == words[idx - 1]:
            count += 1
            if count >= threshold:
                return True
        else:
            count = 1
    return False


def _normalize_question(raw_question: str) -> str:
    question = cleanup_plain_text(raw_question).strip()
    question = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", question)
    return " ".join(question.split())


def _has_consecutive_repeated_line(text: str, threshold: int = 4) -> bool:
    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    if len(lines) < threshold:
        return False
    count = 1
    for idx in range(1, len(lines)):
        if lines[idx] == lines[idx - 1]:
            count += 1
            if count >= threshold:
                return True
        else:
            count = 1
    return False
