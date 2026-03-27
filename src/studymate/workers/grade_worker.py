from __future__ import annotations

import re

from PySide6.QtCore import QThread, Signal

from studymate.constants import GRADE_RESPONSE_SCHEMA
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.utils.markdown import cleanup_plain_text


class GradeWorker(QThread):
    stream = Signal(str)
    status = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        *,
        question: str,
        expected_answer: str,
        user_answer: str,
        difficulty: int,
        ollama: OllamaService,
        model: str = "gemma3:4b",
        profile_context: dict | None = None,
        stream_preview: bool = True,
    ) -> None:
        super().__init__()
        self.question = question
        self.expected_answer = expected_answer
        self.user_answer = user_answer
        self.difficulty = difficulty
        self.ollama = ollama
        self.model = model
        self.profile_context = profile_context or {}
        self.stream_preview = stream_preview

    @staticmethod
    def _is_inappropriate_or_garbage(text: str) -> bool:
        lowered = " ".join(text.lower().split())
        if not lowered:
            return True
        stripped = re.sub(r"[\W_]+", "", lowered)
        if len(stripped) < 2:
            return True
        banned = [
            "nigger",
            "nigga",
            "faggot",
            "retard",
            "i hate ",
        ]
        if any(term in lowered for term in banned):
            return True
        if re.fullmatch(r"[.\-_,!? ]+", lowered):
            return True
        words = lowered.split()
        if len(words) == 1 and len(stripped) >= 7:
            vowels = sum(1 for ch in stripped if ch in "aeiou")
            if vowels <= 1:
                return True
        if stripped and len(set(stripped)) <= 3 and len(stripped) >= 6:
            return True
        return False

    def _strict_rejection_report(self) -> dict:
        text = self.user_answer.strip()
        bad_reason = "The answer is inappropriate, off-topic, or not a real attempt at the question."
        if not text or re.fullmatch(r"[.\-_,!? ]*", text):
            bad_reason = "The answer is effectively blank and does not attempt the question."
        return {
            "marks_out_of_10": 0.0,
            "how_good": 0.0,
            "state": "wrong",
            "what_went_bad": bad_reason,
            "what_went_good": "",
            "what_to_improve": "Answer the actual question in a respectful, on-topic way with real content.",
            "preview_markdown": (
                "### Feedback\n"
                "- This answer is not acceptable.\n"
                "- It is blank, inappropriate, spam, or unrelated to the question.\n"
                "- Write a real answer to the question before asking for marks."
            ),
        }

    def run(self) -> None:
        if self._is_inappropriate_or_garbage(self.user_answer):
            self.stream.emit(
                "### Feedback\n"
                "- This answer is not acceptable.\n"
                "- It is blank, inappropriate, spam, or unrelated to the question.\n"
                "- Write a respectful, on-topic answer."
            )
            self.finished.emit(self._strict_rejection_report())
            return

        preview_text = ""
        if self.stream_preview:
            preview_prompt = (
                "You are a strict but fair teacher speaking directly to the student. "
                "Be calm and professional, not soft. "
                "Reward correct or mostly correct answers strongly, including 10/10 when the core meaning is clearly right for the student's level. "
                "If the student is age 16 or younger, a vague or slightly imprecise but clearly correct answer may still earn 10/10. "
                "In that case, you may omit criticism entirely instead of forcing a what-is-wrong section. "
                "Be strict on wrong, off-topic, vague, spammy, or low-effort answers. "
                "If an answer is inappropriate, hateful, abusive, nonsense, or does not attempt the question, say that clearly and do not praise it. "
                "Stream concise feedback in markdown."
            )
            user_preview_prompt = (
                f"Student age: {self.profile_context.get('age', '')}\n"
                f"Student grade: {self.profile_context.get('grade', '')}\n\n"
                f"Question:\n{self.question}\n\n"
                f"Expected answer:\n{self.expected_answer}\n\n"
                f"Student answer:\n{self.user_answer}\n\n"
                "Give quick feedback with sections: What is right, What is wrong, Next step. "
                "Do not include any numeric score in this streaming feedback."
            )
            self.status.emit("Streaming grading feedback...")
            try:
                for chunk in self.ollama.stream_chat(
                    model=self.model,
                    system_prompt=preview_prompt,
                    user_prompt=user_preview_prompt,
                    temperature=0.2,
                ):
                    preview_text += chunk
                    self.stream.emit(preview_text)
            except OllamaError:
                preview_text = "### Feedback\n- Could not stream from Ollama right now.\n- Please try again."
                self.stream.emit(preview_text)

        self.status.emit("Creating structured grade report...")
        structured_prompt = (
            "Return only strict JSON matching schema. "
            "You are a strict but fair teacher speaking directly to the student. "
            "Score the answer based on the expected answer, age, and grade level. "
            "Small grammar mistakes are okay, but factual mistakes, off-topic content, spam, gibberish, abusive language, slurs, or non-answers must be graded harshly. "
            "If the answer is inappropriate, hateful, abusive, random garbage, or does not attempt the question, marks_out_of_10 must be between 0 and 2 and state must be wrong. "
            "If the core meaning is clearly correct for the student's level, award 10/10 even if wording is simple. "
            "If the student is age 16 or younger, a vague or slightly imprecise but clearly correct answer may still receive 10/10. "
            "For those under-16 clearly-correct answers, you may leave what_went_bad empty and avoid nitpicking. "
            "Somewhat right answers may still receive high marks if the core meaning is correct. "
            "Also produce a hidden how_good score out of 120.0000 for internal study analytics. "
            "Set state to 'correct' when the answer meaning is broadly right for the student's level. "
            "Set state to 'wrong' when the answer meaning is not right enough yet. "
            "When correct, make what_went_good specific and deserved. "
            "When wrong, be firm and direct about what is missing or unacceptable. "
            "Do not praise wrong, abusive, irrelevant, or nonsense answers."
        )
        user_structured = (
            f"Student age: {self.profile_context.get('age', '')}\n"
            f"Student grade: {self.profile_context.get('grade', '')}\n\n"
            f"Question:\n{self.question}\n\n"
            f"Expected answer:\n{self.expected_answer}\n\n"
            f"Student answer:\n{self.user_answer}\n\n"
            f"Question difficulty: {self.difficulty}\n"
            "When difficulty is below 5, set what_to_improve to an empty string."
        )
        try:
            report = self.ollama.structured_chat(
                model=self.model,
                system_prompt=structured_prompt,
                user_prompt=user_structured,
                schema=GRADE_RESPONSE_SCHEMA,
                temperature=0.0,
            )
        except OllamaError as exc:
            self.failed.emit(str(exc))
            return

        try:
            if self.difficulty < 5:
                report["what_to_improve"] = ""

            normalized = {
                "marks_out_of_10": float(report.get("marks_out_of_10", 0)),
                "how_good": float(report.get("how_good", 0)),
                "state": cleanup_plain_text(str(report.get("state", "wrong"))).lower() or "wrong",
                "what_went_bad": cleanup_plain_text(str(report.get("what_went_bad", ""))),
                "what_went_good": cleanup_plain_text(str(report.get("what_went_good", ""))),
                "what_to_improve": cleanup_plain_text(str(report.get("what_to_improve", ""))),
                "preview_markdown": preview_text,
            }
        except Exception as exc:
            self.failed.emit(f"Grade normalization failed: {exc}")
            return

        self.finished.emit(normalized)
