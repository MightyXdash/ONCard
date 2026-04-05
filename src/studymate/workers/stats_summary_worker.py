from __future__ import annotations

import json
import re

from PySide6.QtCore import QThread, Signal

from studymate.services.ollama_service import OllamaError, OllamaService


STATS_SUMMARY_SYSTEM_PROMPT = (
    "You are ONCard's performance analyst. Write a concise third-person study summary about the student using only the provided app data.\n\n"
    "Rules:\n"
    "- Always refer to the student in third person (never 'you').\n"
    "- Pronouns are mandatory. If profile gender is male, use only he/him for the student. If profile gender is female, use only she/her for the student. If gender is not male or female, avoid gendered pronouns and use the student name.\n"
    "- Use normal markdown for readability. Markdown headings, bold, and italics are allowed.\n"
    "- Use these two section headings in this order:\n"
    "  1. How good [name] is performing:\n"
    "  2. What I think [name] should do:\n"
    "- Do not include square brackets around the headings.\n"
    "- Under How good [name] is performing:, start with a direct sentence like '[name] is performing good.' and then briefly explain why using the provided metrics.\n"
    "- Under What I think [name] should do:, include a sentence that starts with: 'I think [name] should focus on ...'.\n"
    "- Keep the markdown tasteful and readable, not excessive.\n"
    "- Ground every claim in supplied metrics; do not invent facts.\n"
    "- Mention strengths, weak spots, and 2-4 concrete focus actions.\n"
    "- If attention span data appears, explain that the scale is from 1 to 10 and represents minutes of attention span.\n"
    "- Clarify that around 3 to 6 minutes is already a good/healthy range, 1 to 2 is somewhat low, and values closer to 10 are strongest.\n"
    "- If data is sparse, explicitly say evidence is limited.\n"
    "- Keep tone supportive, direct, and practical.\n"
    "- Maximum 170 words."
)


def _normalize_gender(value: object) -> str:
    token = str(value or "").strip().lower()
    if token in {"male", "man", "boy", "he", "him", "he/him"}:
        return "male"
    if token in {"female", "woman", "girl", "she", "her", "she/her"}:
        return "female"
    return "unspecified"


def _case_like(source: str, target: str) -> str:
    if source.isupper():
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def _replace_token(text: str, pattern: str, replacement: str) -> str:
    return re.sub(
        pattern,
        lambda m: _case_like(m.group(0), replacement),
        text,
        flags=re.IGNORECASE,
    )


def _enforce_pronouns(text: str, gender: str) -> str:
    if gender == "male":
        guarded = text
        guarded = _replace_token(guarded, r"\bherself\b", "himself")
        guarded = _replace_token(guarded, r"\bhers\b", "his")
        guarded = _replace_token(guarded, r"\bher(?=\s+\w)\b", "his")
        guarded = _replace_token(guarded, r"\bshe\b", "he")
        guarded = _replace_token(guarded, r"\bher\b", "him")
        return guarded
    if gender == "female":
        guarded = text
        guarded = _replace_token(guarded, r"\bhimself\b", "herself")
        guarded = _replace_token(guarded, r"\bhis(?=\s+\w)\b", "her")
        guarded = _replace_token(guarded, r"\bhis\b", "hers")
        guarded = _replace_token(guarded, r"\bhe\b", "she")
        guarded = _replace_token(guarded, r"\bhim\b", "her")
        return guarded
    return text


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
        profile_name = str(self.profile.get("profile_name", "")).strip() or str(self.profile.get("name", "")).strip() or "The student"
        profile_gender_raw = str(self.profile.get("gender", "")).strip() or "unspecified"
        profile_gender = _normalize_gender(profile_gender_raw)
        if profile_gender == "male":
            pronoun_rule = "Use only he/him pronouns for the student."
        elif profile_gender == "female":
            pronoun_rule = "Use only she/her pronouns for the student."
        else:
            pronoun_rule = "Avoid gendered pronouns and use the student's name."
        user_prompt = (
            "Student profile:\n"
            f"{json.dumps(self.profile, ensure_ascii=False, indent=2)}\n\n"
            f"Student name: {profile_name}\n"
            f"Profile gender (raw): {profile_gender_raw}\n"
            f"Profile gender (normalized): {profile_gender}\n"
            f"Pronoun rule: {pronoun_rule}\n\n"
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
        summary = _enforce_pronouns("".join(parts).strip(), profile_gender)
        self.finished.emit(summary)
