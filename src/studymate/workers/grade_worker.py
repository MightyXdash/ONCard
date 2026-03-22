from __future__ import annotations

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
    ) -> None:
        super().__init__()
        self.question = question
        self.expected_answer = expected_answer
        self.user_answer = user_answer
        self.difficulty = difficulty
        self.ollama = ollama
        self.model = model
        self.profile_context = profile_context or {}

    def run(self) -> None:
        preview_prompt = (
            "You are a gentle study coach speaking directly to the student. "
            "Use casual, encouraging language. "
            "Be kind about small grammar mistakes. "
            "Judge based on the student's age and grade level. "
            "If the answer is meaningfully correct for that level, it can still earn 10/10. "
            "Stream concise feedback in markdown."
        )
        user_preview_prompt = (
            f"Student age: {self.profile_context.get('age', '')}\n"
            f"Student grade: {self.profile_context.get('grade', '')}\n\n"
            f"Question:\n{self.question}\n\n"
            f"Expected answer:\n{self.expected_answer}\n\n"
            f"Student answer:\n{self.user_answer}\n\n"
            "Give quick feedback with sections: Score guess, Strengths, Gaps, Next step."
        )
        preview_text = ""
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
            "You are a gentle study coach speaking directly to the student. "
            "Score the answer fairly based on the expected answer, age, and grade level. "
            "Small grammar mistakes are okay. "
            "If the answer is correct in meaning for that level, it can receive full marks. "
            "Set state to 'correct' when the answer meaning is broadly right for the student's level. "
            "Set state to 'wrong' when the answer meaning is not right enough yet."
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
                "state": cleanup_plain_text(str(report.get("state", "wrong"))).lower() or "wrong",
                "answer_summary": cleanup_plain_text(str(report.get("answer_summary", ""))),
                "what_went_bad": cleanup_plain_text(str(report.get("what_went_bad", ""))),
                "what_went_good": cleanup_plain_text(str(report.get("what_went_good", ""))),
                "what_to_improve": cleanup_plain_text(str(report.get("what_to_improve", ""))),
                "preview_markdown": preview_text,
            }
        except Exception as exc:
            self.failed.emit(f"Grade normalization failed: {exc}")
            return

        self.finished.emit(normalized)
