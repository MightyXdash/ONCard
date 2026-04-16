from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import random
import re

from PySide6.QtCore import QThread, Signal

from studymate.constants import MCQ_RESPONSE_SCHEMA
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.utils.markdown import cleanup_plain_text
from studymate.workers.prompt_context import with_oncard_context


THROWAWAY_ANSWERS = {
    "all of the above",
    "none of the above",
    "both a and b",
    "not enough information",
    "i don't know",
    "unknown",
}

OBVIOUS_EASY_DISTRACTORS = {
    "a coding algorithm for ai",
    "a rule from medieval times",
    "a strict mathematical formula",
    "core concept",
    "exam clue",
    "key idea",
    "nearby topic",
    "related detail",
    "random guess",
    "similar concept",
    "study review",
    "topic meaning",
    "unrelated concept",
}

MCQ_GENERATION_ATTEMPTS = 3
MCQ_GENERATION_TIMEOUT_SECONDS = 45


def question_hash(question: str) -> str:
    normalized = " ".join(str(question or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def mcq_cache_key(card: dict, model_tag: str) -> str:
    card_id = str(card.get("id", "")).strip()
    return f"mcq:v2:{card_id}:{question_hash(str(card.get('question', '')))}:{str(model_tag or '').strip()}"


def normalize_mcq_answers(raw_answers: object) -> list[str]:
    if not isinstance(raw_answers, list):
        raise ValueError("MCQ response must include an answers list.")
    answers: list[str] = []
    seen: set[str] = set()
    for item in raw_answers:
        answer = cleanup_plain_text(str(item or "")).strip()
        answer = re.sub(r"\s+", " ", answer)
        normalized = re.sub(r"[\W_]+", "", answer.lower())
        if not answer:
            raise ValueError("MCQ answers cannot be blank.")
        lowered = answer.lower()
        if lowered in THROWAWAY_ANSWERS or lowered in OBVIOUS_EASY_DISTRACTORS:
            raise ValueError("MCQ answers cannot use throwaway or obviously easy choices.")
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'/-]*", answer)
        if not (1 <= len(words) <= 40):
            raise ValueError("MCQ answers must be 1-40 words.")
        if normalized in seen:
            raise ValueError("MCQ answers must be unique.")
        seen.add(normalized)
        answers.append(answer)
    if len(answers) != 4:
        raise ValueError("MCQ responses must include exactly 4 answers.")
    lengths = [len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'/-]*", answer)) for answer in answers]
    if max(lengths) - min(lengths) > 20:
        raise ValueError("MCQ answers should have similar length.")
    char_lengths = [len(answer) for answer in answers]
    if min(char_lengths) > 0 and max(char_lengths) / min(char_lengths) > 5.0:
        raise ValueError("MCQ answers should look similar in length and specificity.")
    return answers


def _mcq_system_prompt(profile_context: dict | None, difficulty: str = "slightly_harder") -> str:
    difficulty_instructions = {
        "easier": (
            "Create a straightforward multiple-choice answer set for a study card. "
            "The first answer must be the correct answer. The second, third, and fourth answers must be wrong. "
            "The wrong answers should be clearly incorrect but related to the topic. "
            "Keep all four choices from the same topic family, but distractors can be obviously wrong. "
            "Make distractors shorter and simpler, with less detail than the correct answer. "
            "A student who only half understands the card should easily identify the correct answer. "
            "Avoid tricky wording or near-miss misconceptions. "
            "Aim for 1 to 5 words per answer."
        ),
        "standard": (
            "Return only strict JSON matching schema. "
            "Create a standard multiple-choice answer set for a study card. "
            "The first answer must be the correct answer. The second, third, and fourth answers must be wrong. "
            "The wrong answers should be plausible misconceptions that answer the same question in a similar grammatical slot. "
            "Keep all four choices semantically close, from the same topic family, and reasonably similar in wording, specificity, and length. "
            "Give every answer choice a comparable amount of detail. "
            "A student who only half understands the card should find all four choices believable. "
            "Avoid broad category mismatches, historical jokes, literal misreadings, unrelated fields, or obviously fake distractors. "
            "Aim for 1 to 6 words per answer."
        ),
        "slightly_harder": (
            "Return only strict JSON matching schema. "
            "Create a tricky multiple-choice answer set for a study card. "
            "The first answer must be the correct answer. The second, third, and fourth answers must be wrong. "
            "The wrong answers should be near-miss misconceptions that answer the same question in a similar grammatical slot. "
            "Keep all four choices semantically close, from the same topic family, and reasonably similar in wording, specificity, and length. "
            "Give every answer choice a comparable amount of detail. "
            "If one choice uses a qualifier, condition, mechanism, example, or specific detail, the other three should include comparable details too. "
            "Wrong choices may include extra specifics when that makes them more confusable, but avoid making only one option visibly more detailed. "
            "A student who only half understands the card should find all four choices believable. "
            "Avoid broad category mismatches, historical jokes, literal misreadings, unrelated fields, obviously fake distractors, or options that can be eliminated by style or length. "
            "Aim for 1 to 8 words per answer."
        ),
        "harder": (
            "Return only strict JSON matching schema. "
            "Create a challenging multiple-choice answer set for a study card. "
            "The first answer must be the correct answer. The second, third, and fourth answers must be wrong. "
            "The wrong answers should be sophisticated near-miss misconceptions with subtle distinctions from the correct answer. "
            "Keep all four choices highly semantically close, from the same topic family, and nearly identical in wording, specificity, and length. "
            "Use advanced terminology and nuanced distinctions that require deep understanding to differentiate. "
            "Give every answer choice a comparable amount of technical detail and precision. "
            "Wrong choices should represent common expert-level misconceptions or subtle misapplications of concepts. "
            "A student with superficial understanding should find all four choices nearly indistinguishable. "
            "Avoid obvious eliminations, broad mismatches, or options that differ only in minor wording. "
            "Aim for 2 to 10 words per answer."
        ),
        "much_harder": (
            "Return only strict JSON matching schema. "
            "Create an expert-level multiple-choice answer set for a study card. "
            "The first answer must be the correct answer. The second, third, and fourth answers must be wrong. "
            "The wrong answers should represent expert-level misconceptions, edge cases, or boundary conditions that even advanced students struggle with. "
            "Keep all four choices extremely semantically close, from the same topic family, and virtually identical in wording, specificity, and technical depth. "
            "Use precise terminology, edge-case scenarios, and subtle logical distinctions that require mastery to differentiate. "
            "Every answer choice must demonstrate comparable technical sophistication and nuanced reasoning. "
            "Wrong choices should represent misconceptions that arise from partial mastery of advanced material or overgeneralization of principles. "
            "A student without deep understanding should find all four choices essentially equivalent. "
            "Avoid any option that can be eliminated through surface-level analysis, style differences, or length cues. "
            "Aim for 3 to 12 words per answer."
        ),
    }
    instruction = difficulty_instructions.get(difficulty, difficulty_instructions["slightly_harder"])
    return with_oncard_context(
        f"Return only strict JSON matching schema. {instruction}",
        feature="MCQ generation",
        profile_context=profile_context or {},
    )


def _mcq_user_prompt(card: dict, profile_context: dict | None) -> str:
    profile_context = profile_context or {}
    return (
        f"Student age: {profile_context.get('age', '')}\n"
        f"Student grade: {profile_context.get('grade', '')}\n\n"
        f"Card title: {card.get('title', '')}\n"
        f"Subject: {card.get('subject', '')}\n"
        f"Category: {card.get('category', '')}\n"
        f"Subtopic: {card.get('subtopic', '')}\n\n"
        f"Question:\n{card.get('question', '')}\n\n"
        "Return JSON only with an answers array of exactly 4 strings. "
        "answers[0] must be the correct answer. "
        "answers[1], answers[2], and answers[3] must be wrong but close to answers[0]. "
        "Make the distractors confusable alternatives, not totally different meanings or unrelated categories. "
        "If the correct answer is a definition, prefer competing definitions of the same term. "
        "If the correct answer is a term, prefer same-type terms from the same lesson. "
        "Use the same level of detail in all four answers. "
        "You may add specific qualifiers or extra details to the wrong choices when it makes them harder, but keep the detail level comparable so none stands out. "
        "Keep answers concise and aim for 1 to 8 words each. "
        "Avoid easy eliminations such as medieval origin, coding algorithm, strict formula, joke options, or broad unrelated labels unless they are truly a same-type near miss."
    )


def build_mcq_payload(card: dict, answers: list[str], model_tag: str) -> dict:
    normalized = normalize_mcq_answers(answers)
    correct_answer = normalized[0]
    choices = [{"text": answer, "correct": index == 0} for index, answer in enumerate(normalized)]
    random.shuffle(choices)
    correct_index = next(index for index, choice in enumerate(choices) if choice["correct"])
    return {
        "answers": normalized,
        "choices": [choice["text"] for choice in choices],
        "correct_answer": correct_answer,
        "correct_index": correct_index,
        "model_tag": str(model_tag or "").strip(),
        "card_id": str(card.get("id", "")).strip(),
        "question_hash": question_hash(str(card.get("question", ""))),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def cached_mcq_payload(datastore, card: dict, model_tag: str) -> dict | None:
    payload = datastore.load_cache_entry(mcq_cache_key(card, model_tag))
    if not isinstance(payload, dict):
        return None
    try:
        choices = payload.get("choices", [])
        correct_index = int(payload.get("correct_index", -1))
        correct_answer = cleanup_plain_text(str(payload.get("correct_answer", ""))).strip()
        if not isinstance(choices, list) or len(choices) != 4 or not (0 <= correct_index < 4):
            return None
        if cleanup_plain_text(str(choices[correct_index])).strip() != correct_answer:
            return None
        normalize_mcq_answers(payload.get("answers", []))
    except Exception:
        return None
    return payload


def save_mcq_payload(datastore, card: dict, payload: dict) -> None:
    model_tag = str(payload.get("model_tag", "")).strip()
    if not model_tag:
        return
    datastore.put_cache_entry(mcq_cache_key(card, model_tag), payload)


class MCQWorker(QThread):
    status = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        *,
        card: dict,
        ollama: OllamaService,
        model: str,
        profile_context: dict | None = None,
        difficulty: str = "slightly_harder",
    ) -> None:
        super().__init__()
        self.card = dict(card)
        self.ollama = ollama
        self.model = model
        self.profile_context = profile_context or {}
        self.difficulty = difficulty

    def run(self) -> None:
        question = str(self.card.get("question", "")).strip()
        if not question:
            self.failed.emit("This card has no question.")
            return
        try:
            payload = _generate_mcq_payload_with_retries(
                card=self.card,
                ollama=self.ollama,
                model=self.model,
                profile_context=self.profile_context,
                difficulty=self.difficulty,
                status_callback=self.status.emit,
            )
        except (OllamaError, ValueError) as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(payload)


class MCQBulkWorker(QThread):
    progress = Signal(int, int, int, int)
    generated = Signal(str, dict)
    finished = Signal(int, int, int)
    failed = Signal(str)

    def __init__(
        self,
        *,
        cards: list[dict],
        datastore,
        ollama: OllamaService,
        model: str,
        profile_context: dict | None = None,
        difficulty: str = "slightly_harder",
    ) -> None:
        super().__init__()
        self.cards = list(cards)
        self.datastore = datastore
        self.ollama = ollama
        self.model = model
        self.profile_context = profile_context or {}
        self.difficulty = difficulty

    def _save_generated_card_answer(self, card: dict, payload: dict) -> None:
        correct_answer = cleanup_plain_text(str(payload.get("correct_answer", ""))).strip()
        if not correct_answer:
            return
        updated = dict(card)
        updated["answer"] = correct_answer
        if payload.get("answers"):
            updated["mcq_answers"] = list(payload.get("answers", []))
        self.datastore.save_card(updated)

    def run(self) -> None:
        generated = 0
        skipped = 0
        failed = 0
        total = len(self.cards)
        for index, card in enumerate(self.cards, start=1):
            if self.isInterruptionRequested():
                break
            try:
                cached = cached_mcq_payload(self.datastore, card, self.model)
                if cached is not None:
                    skipped += 1
                    self.progress.emit(index, total, generated, failed)
                    continue
                if card.get("mcq_answers"):
                    payload = build_mcq_payload(card, list(card.get("mcq_answers", [])), self.model)
                    save_mcq_payload(self.datastore, card, payload)
                    self._save_generated_card_answer(card, payload)
                    generated += 1
                    self.generated.emit(str(card.get("id", "")), payload)
                    self.progress.emit(index, total, generated, failed)
                    continue
                payload = generate_mcq_payload(
                    card=card,
                    ollama=self.ollama,
                    model=self.model,
                    profile_context=self.profile_context,
                    difficulty=self.difficulty,
                )
                save_mcq_payload(self.datastore, card, payload)
                self._save_generated_card_answer(card, payload)
                generated += 1
                self.generated.emit(str(card.get("id", "")), payload)
            except Exception:
                failed += 1
            self.progress.emit(index, total, generated, failed)
        self.finished.emit(generated, skipped, failed)


def generate_mcq_payload(
    *,
    card: dict,
    ollama: OllamaService,
    model: str,
    profile_context: dict | None = None,
    difficulty: str = "slightly_harder",
) -> dict:
    question = str(card.get("question", "")).strip()
    if not question:
        raise ValueError("This card has no question.")
    profile_context = profile_context or {}
    return _generate_mcq_payload_with_retries(
        card=card,
        ollama=ollama,
        model=model,
        profile_context=profile_context,
        difficulty=difficulty,
    )


def _generate_mcq_payload_with_retries(
    *,
    card: dict,
    ollama: OllamaService,
    model: str,
    profile_context: dict | None = None,
    difficulty: str = "slightly_harder",
    status_callback=None,
) -> dict:
    profile_context = profile_context or {}
    system_prompt = _mcq_system_prompt(profile_context, difficulty)
    base_user_prompt = _mcq_user_prompt(card, profile_context)
    last_error: Exception | None = None
    for attempt in range(1, MCQ_GENERATION_ATTEMPTS + 1):
        if status_callback is not None:
            if attempt == 1:
                status_callback("Generating MCQ choices...")
            else:
                status_callback(f"Retrying MCQ choices... ({attempt}/{MCQ_GENERATION_ATTEMPTS})")
        retry_note = ""
        if last_error is not None:
            retry_note = (
                "\n\nThe previous answer set was rejected because: "
                f"{last_error}. "
                "Return a cleaner set where every wrong option is a plausible same-topic misconception and every option has a comparable level of detail."
            )
        try:
            response = ollama.structured_chat(
                model=model,
                system_prompt=system_prompt,
                user_prompt=base_user_prompt + retry_note,
                schema=MCQ_RESPONSE_SCHEMA,
                temperature=min(0.45, 0.2 + (0.1 * attempt)),
                timeout=MCQ_GENERATION_TIMEOUT_SECONDS,
            )
            return build_mcq_payload(card, normalize_mcq_answers(response.get("answers", [])), model)
        except (OllamaError, ValueError) as exc:
            last_error = exc
    if last_error is None:
        raise ValueError("MCQ generation failed.")
    raise last_error
