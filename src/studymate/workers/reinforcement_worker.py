from __future__ import annotations

import uuid

from PySide6.QtCore import QThread, Signal

from studymate.constants import REINFORCEMENT_SCHEMA
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.utils.markdown import cleanup_plain_text
from studymate.workers.autofill_worker import generate_card_payload


class ReinforcementWorker(QThread):
    progress = Signal(str, str, bool)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        *,
        ollama: OllamaService,
        weak_card: dict,
        similar_cards: list[dict],
        recent_incorrect_answers: list[dict],
        profile_context: dict | None = None,
        assistant_tone: str = "",
        context_length: int = 8192,
        model: str = "gemma3:4b",
    ) -> None:
        super().__init__()
        self.ollama = ollama
        self.weak_card = weak_card
        self.similar_cards = similar_cards
        self.recent_incorrect_answers = recent_incorrect_answers
        self.profile_context = profile_context or {}
        self.assistant_tone = assistant_tone
        self.context_length = context_length
        self.model = model

    def run(self) -> None:
        self.progress.emit("creating", "Creating questions...", False)
        try:
            questions = self._generate_questions()
        except OllamaError as exc:
            self.failed.emit(str(exc))
            return
        self.progress.emit("creating", "Creating questions...", True)

        self.progress.emit("filling", "Filling cards...", False)
        cards: list[dict] = []
        for index, question in enumerate(questions, start=1):
            try:
                payload = generate_card_payload(
                    question=question,
                    ollama=self.ollama,
                    model=self.model,
                    profile_context=self.profile_context,
                    subject_override=str(self.weak_card.get("subject", "General")),
                    category_override=str(self.weak_card.get("category", "All")),
                    subtopic_override=str(self.weak_card.get("subtopic", "All")),
                    response_to_user="Reinforcement card ready.",
                    extra_options={"num_ctx": self.context_length},
                )
            except Exception as exc:
                self.failed.emit(f"Reinforcement autofill failed: {exc}")
                return
            payload["id"] = f"temp-{uuid.uuid4()}"
            payload["question"] = cleanup_plain_text(question)
            payload["title"] = payload.get("title") or "Reinforcement card"
            payload["temporary"] = True
            payload["related_topic"] = self.weak_card.get("subtopic") or self.weak_card.get("category") or "General"
            payload["source_card_id"] = self.weak_card.get("id")
            payload["batch_index"] = index
            cards.append(payload)
        self.progress.emit("filling", "Filling cards...", True)
        self.finished.emit(cards)

    def _generate_questions(self) -> list[str]:
        system_prompt = (
            "Return only strict JSON matching the schema. "
            "You create temporary reinforcement flashcards for one weak topic. "
            "Make the cards academically useful, clear, and age-appropriate. "
            "Do not mention that they are temporary."
        )
        context_lines = [
            f"Student age: {self.profile_context.get('age', '')}",
            f"Student grade: {self.profile_context.get('grade', '')}",
            f"Tone: {self.assistant_tone or 'supportive teacher'}",
            f"Context budget hint: {self.context_length}",
            f"Weak question: {self.weak_card.get('question', '')}",
            f"Expected answer: {self.weak_card.get('answer', '')}",
        ]
        if self.similar_cards:
            context_lines.append("Related cards:")
            for card in self.similar_cards[:5]:
                context_lines.append(f"- Q: {card.get('question', '')}")
                context_lines.append(f"  A: {card.get('answer', '')}")
        if self.recent_incorrect_answers:
            context_lines.append("Recent incorrect answers:")
            for item in self.recent_incorrect_answers[-4:]:
                context_lines.append(f"- Student answer: {item.get('answer_text', '')}")
                context_lines.append(f"  Weakness feedback: {item.get('what_went_bad', '')}")
        user_prompt = "\n".join(context_lines) + "\nGenerate exactly 4 targeted reinforcement questions for this topic."
        payload = self.ollama.structured_chat(
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=REINFORCEMENT_SCHEMA,
            temperature=0.1,
            extra_options={"num_ctx": self.context_length},
        )
        raw_questions = payload.get("questions", [])
        if not isinstance(raw_questions, list) or len(raw_questions) < 4:
            raise OllamaError("Reinforcement failed: Gemma did not return 4 questions.")
        questions = [cleanup_plain_text(str(item)) for item in raw_questions[:4] if cleanup_plain_text(str(item))]
        if len(questions) < 4:
            raise OllamaError("Reinforcement failed: generated questions were empty.")
        return questions[:4]
