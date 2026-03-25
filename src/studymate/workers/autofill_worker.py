from __future__ import annotations

import random
import time

from PySide6.QtCore import QThread, Signal

from studymate.constants import CREATE_RESPONSE_SCHEMA, SUBJECT_TAXONOMY
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.utils.markdown import cleanup_plain_text


def generate_card_payload(
    *,
    question: str,
    ollama: OllamaService,
    model: str = "gemma3:4b",
    profile_context: dict | None = None,
    subject_override: str | None = None,
    category_override: str | None = None,
    subtopic_override: str | None = None,
    response_to_user: str = "Done!",
) -> dict:
    profile_context = profile_context or {}

    def fallback() -> dict:
        subject = subject_override or random.choice(list(SUBJECT_TAXONOMY.keys()))
        core = SUBJECT_TAXONOMY.get(subject, {}).get("core", [])
        subtopics = SUBJECT_TAXONOMY.get(subject, {}).get("subtopics", [])
        return {
            "title": cleanup_plain_text(question[:72] or "New Question"),
            "subject": subject,
            "category": category_override or (random.choice(core) if core else "All"),
            "subtopic": subtopic_override or (random.choice(subtopics) if subtopics else "All"),
            "hints": [
                "Break the question into smaller pieces.",
                "Start with a known definition or formula.",
                "Double-check your final step for accuracy.",
            ],
            "answer": "AI fallback mode: Ollama was unavailable, so this card was not fully generated.",
            "natural_difficulty": 5,
            "response_to_user": response_to_user,
        }

    system_prompt = (
        "You are a precise flashcard assistant. "
        "Return only valid JSON that matches the provided schema. "
        "No markdown, no code fences, no extra keys."
    )
    taxonomy = ", ".join(SUBJECT_TAXONOMY.keys())
    profile_text = (
        f"Student age: {profile_context.get('age', '')}\n"
        f"Student grade: {profile_context.get('grade', '')}\n"
    )
    override_lines = []
    if subject_override:
        override_lines.append(f"Subject must be exactly: {subject_override}")
    else:
        override_lines.append(f"Pick a subject from: {taxonomy}")
    if category_override:
        override_lines.append(f"Category must be exactly: {category_override}")
    if subtopic_override:
        override_lines.append(f"Subtopic must be exactly: {subtopic_override}")
    override_lines.append("Return clean values for title, category, subtopic, hints, answer, difficulty and response_to_user.")
    user_prompt = f"{profile_text}Question: {question}\n" + "\n".join(override_lines)
    try:
        payload = ollama.structured_chat(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=CREATE_RESPONSE_SCHEMA,
            temperature=0.0,
        )
    except OllamaError:
        payload = fallback()

    payload["title"] = cleanup_plain_text(str(payload.get("title", "")))
    payload["subject"] = cleanup_plain_text(str(payload.get("subject", subject_override or "Mathematics")))
    payload["category"] = cleanup_plain_text(str(payload.get("category", category_override or "All")))
    payload["subtopic"] = cleanup_plain_text(str(payload.get("subtopic", subtopic_override or "All")))
    payload["answer"] = cleanup_plain_text(str(payload.get("answer", "")))
    payload["response_to_user"] = cleanup_plain_text(str(payload.get("response_to_user", response_to_user)))
    payload["natural_difficulty"] = int(payload.get("natural_difficulty", 5))
    hints = payload.get("hints", [])
    if not isinstance(hints, list):
        hints = []
    payload["hints"] = [cleanup_plain_text(str(item)) for item in hints[:5]]
    while len(payload["hints"]) < 3:
        payload["hints"].append("Use the key concept in the question.")

    if subject_override:
        payload["subject"] = subject_override
    if category_override:
        payload["category"] = category_override
    if subtopic_override:
        payload["subtopic"] = subtopic_override
    return payload


class AutofillWorker(QThread):
    progress = Signal(str)
    field = Signal(str, object)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        question: str,
        ollama: OllamaService,
        model: str = "gemma3:4b",
        profile_context: dict | None = None,
    ) -> None:
        super().__init__()
        self.question = question
        self.ollama = ollama
        self.model = model
        self.profile_context = profile_context or {}

    def _fallback(self) -> dict:
        return generate_card_payload(
            question=self.question,
            ollama=self.ollama,
            model=self.model,
            profile_context=self.profile_context,
            response_to_user="Done! I queued a fallback draft card so you can keep studying.",
        )

    def run(self) -> None:
        self.progress.emit("Analyzing your question...")
        time.sleep(0.15)
        self.progress.emit("Planning card metadata...")
        time.sleep(0.15)
        self.progress.emit("Generating JSON response with Gemma...")
        try:
            payload = generate_card_payload(
                question=self.question,
                ollama=self.ollama,
                model=self.model,
                profile_context=self.profile_context,
            )
        except OllamaError:
            payload = self._fallback()
            self.progress.emit("Ollama unavailable. Used fallback draft.")

        ordered_fields = [
            ("title", payload["title"]),
            ("subject", payload["subject"]),
            ("category", payload["category"]),
            ("subtopic", payload["subtopic"]),
            ("hints", payload["hints"]),
            ("answer", payload["answer"]),
            ("natural_difficulty", payload["natural_difficulty"]),
            ("response_to_user", payload["response_to_user"]),
        ]
        for name, value in ordered_fields:
            self.progress.emit(f"Writing {name}...")
            time.sleep(0.08)
            self.field.emit(name, value)

        self.done.emit(payload)
