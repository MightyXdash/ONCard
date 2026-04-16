from __future__ import annotations

import random
import re

from PySide6.QtCore import QThread, Signal

from studymate.constants import CREATE_RESPONSE_SCHEMA, SUBJECT_TAXONOMY
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.utils.markdown import cleanup_plain_text
from studymate.workers.mcq_worker import normalize_mcq_answers
from studymate.workers.prompt_context import with_oncard_context


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
    extra_options: dict | None = None,
) -> dict:
    profile_context = profile_context or {}

    def fallback() -> dict:
        subject = subject_override or random.choice(list(SUBJECT_TAXONOMY.keys()))
        core = SUBJECT_TAXONOMY.get(subject, {}).get("core", [])
        subtopics = SUBJECT_TAXONOMY.get(subject, {}).get("subtopics", [])
        return {
            "title": _enforce_title_word_range(cleanup_plain_text(question[:72] or "New Question"), question),
            "subject": subject,
            "category": category_override or (random.choice(core) if core else "All"),
            "subtopic": subtopic_override or (random.choice(subtopics) if subtopics else "All"),
            "hints": [
                "Break the question into smaller pieces.",
                "Start with a known definition or formula.",
                "Double-check your final step for accuracy.",
            ],
            "search_terms": _default_search_terms(question),
            "answer": "",
            "mcq_answers": [],
            "natural_difficulty": 5,
            "response_to_user": response_to_user,
        }

    system_prompt = with_oncard_context(
        (
            "You are a precise flashcard assistant. "
            "Return only valid JSON that matches the provided schema. "
            "No markdown, no code fences, no extra keys."
        ),
        feature="Card autofill generation",
        profile_context=profile_context,
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
    override_lines.append(
        "Return clean values for title, category, subtopic, hints, exactly 5 short search_terms, mcq_answers, difficulty and response_to_user."
    )
    override_lines.append("Title must be strictly 2 to 6 words only.")
    override_lines.append("If the best title is longer, shorten it to a meaningful 2 to 6 word title.")
    override_lines.append(
        "mcq_answers must contain exactly 4 strings. mcq_answers[0] is correct. "
        "mcq_answers[1], [2], and [3] are wrong but tricky near-miss misconceptions. "
        "All four choices should answer the same question in a similar grammatical slot and be semantically close. "
        "They should be similar in topic family, wording style, specificity, and length so a half-prepared student cannot eliminate them by vibe. "
        "Give every answer choice a comparable amount of detail; if one uses a qualifier, mechanism, condition, example, or specific detail, all four should use comparable detail. "
        "You may add extra specifics to wrong choices when that makes them harder, but do not let any option stand out by being much simpler or much more detailed. "
        "Avoid unrelated categories, broad mismatches, historical jokes, literal misreadings, or fake/easy distractors like medieval origin, coding algorithm, or strict formula. "
        "Aim for 1 to 7 words per MCQ answer. Do not generate a separate long answer."
    )
    user_prompt = f"{profile_text}Question: {question}\n" + "\n".join(override_lines)
    try:
        payload = ollama.structured_chat(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=CREATE_RESPONSE_SCHEMA,
            temperature=0.0,
            extra_options=extra_options,
        )
    except OllamaError:
        payload = fallback()

    payload["title"] = _enforce_title_word_range(cleanup_plain_text(str(payload.get("title", ""))), question)
    payload["subject"] = cleanup_plain_text(str(payload.get("subject", subject_override or "Mathematics")))
    payload["category"] = cleanup_plain_text(str(payload.get("category", category_override or "All")))
    payload["subtopic"] = cleanup_plain_text(str(payload.get("subtopic", subtopic_override or "All")))
    try:
        payload["mcq_answers"] = normalize_mcq_answers(payload.get("mcq_answers", []))
    except ValueError:
        payload["mcq_answers"] = []
    payload["answer"] = payload["mcq_answers"][0] if payload["mcq_answers"] else ""
    payload["response_to_user"] = cleanup_plain_text(str(payload.get("response_to_user", response_to_user)))
    payload["natural_difficulty"] = int(payload.get("natural_difficulty", 5))
    hints = payload.get("hints", [])
    if not isinstance(hints, list):
        hints = []
    payload["hints"] = [cleanup_plain_text(str(item)) for item in hints[:5]]
    while len(payload["hints"]) < 3:
        payload["hints"].append("Use the key concept in the question.")
    search_terms = payload.get("search_terms", [])
    if not isinstance(search_terms, list):
        search_terms = []
    payload["search_terms"] = [cleanup_plain_text(str(item)) for item in search_terms if cleanup_plain_text(str(item))][:5]
    if len(payload["search_terms"]) < 5:
        extras = _default_search_terms(" ".join([payload["title"], question]))
        for term in extras:
            if term not in payload["search_terms"]:
                payload["search_terms"].append(term)
            if len(payload["search_terms"]) >= 5:
                break

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
        self.progress.emit("Planning card metadata...")
        self.progress.emit(f"Generating JSON response with {self.model}...")
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
            ("search_terms", payload["search_terms"]),
            ("mcq_answers", payload["mcq_answers"]),
            ("natural_difficulty", payload["natural_difficulty"]),
            ("response_to_user", payload["response_to_user"]),
        ]
        for name, value in ordered_fields:
            self.progress.emit(f"Writing {name}...")
            self.field.emit(name, value)

        self.done.emit(payload)


def _default_search_terms(seed_text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", cleanup_plain_text(seed_text).lower())
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "describe",
        "do",
        "does",
        "explain",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "why",
        "with",
    }
    candidates: list[str] = []
    filtered = [word for word in words if len(word) > 2 and word not in stop_words]
    for word in filtered:
        if word not in candidates:
            candidates.append(word)
        if len(candidates) >= 5:
            return candidates
    for idx in range(max(0, len(filtered) - 1)):
        phrase = f"{filtered[idx]} {filtered[idx + 1]}".strip()
        if phrase and phrase not in candidates:
            candidates.append(phrase)
        if len(candidates) >= 5:
            return candidates
    for fallback in ["core concept", "key idea", "exam clue", "topic meaning", "study review"]:
        if fallback not in candidates:
            candidates.append(fallback)
        if len(candidates) >= 5:
            return candidates
    return candidates[:5]


def _enforce_title_word_range(title: str, question: str) -> str:
    cleaned = cleanup_plain_text(title)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'/-]*", cleaned)
    if 2 <= len(words) <= 6:
        return " ".join(words)

    if len(words) > 6:
        return " ".join(words[:6])

    question_words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'/-]*", cleanup_plain_text(question))
    filtered_question_words: list[str] = []
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "why",
        "with",
    }
    for word in question_words:
        lowered = word.lower()
        if lowered not in stop_words:
            filtered_question_words.append(word)
        if len(filtered_question_words) >= 6:
            break

    if len(filtered_question_words) >= 2:
        return " ".join(filtered_question_words[:6])
    if filtered_question_words:
        return f"{filtered_question_words[0]} Overview"
    if words:
        return f"{words[0]} Overview"
    return "Study Overview"
