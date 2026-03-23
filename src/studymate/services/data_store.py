from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from studymate.constants import SUBJECT_TAXONOMY
from studymate.utils.paths import AppPaths


class DataStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    @staticmethod
    def _read_json(path: Path, default: dict | list):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _write_json(path: Path, data: dict | list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def load_setup(self) -> dict:
        default = {
            "onboarding_complete": False,
            "ram_gb": 0,
            "advanced_installation": False,
            "selected_models": [],
            "installed_models": {},
            "performance_arena": {"skipped": True, "avg_tps": None, "tier": ""},
            "updated_at": self.now_iso(),
        }
        return self._read_json(self.paths.setup_config, default)

    def save_setup(self, payload: dict) -> None:
        payload["updated_at"] = self.now_iso()
        self._write_json(self.paths.setup_config, payload)

    def load_profile(self) -> dict:
        default = {
            "name": "",
            "age": "",
            "grade": "",
            "hobbies": "",
            "attention_span_minutes": 5,
            "question_focus_level": 5,
            "created_at": self.now_iso(),
            "updated_at": self.now_iso(),
        }
        return self._read_json(self.paths.profile_config, default)

    def save_profile(self, payload: dict) -> None:
        payload["updated_at"] = self.now_iso()
        self._write_json(self.paths.profile_config, payload)

    @staticmethod
    def subject_slug(subject: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in subject).strip("_")
        return cleaned or "general"

    def subject_path(self, subject: str) -> Path:
        return self.paths.subjects / f"{self.subject_slug(subject)}.json"

    def load_subject_cards(self, subject: str) -> list[dict]:
        path = self.subject_path(subject)
        return self._read_json(path, [])

    def save_subject_cards(self, subject: str, cards: list[dict]) -> None:
        self._write_json(self.subject_path(subject), cards)

    def list_all_cards(self) -> list[dict]:
        cards: list[dict] = []
        for subject in SUBJECT_TAXONOMY:
            cards.extend(self.load_subject_cards(subject))
        return cards

    def card_counts_by_subject(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for subject in SUBJECT_TAXONOMY:
            counts[subject] = len(self.load_subject_cards(subject))
        return counts

    def save_card(self, card_payload: dict) -> dict:
        subject = card_payload.get("subject", "Mathematics")
        record = {
            "id": card_payload.get("id") or str(uuid.uuid4()),
            "question": card_payload.get("question", "").strip(),
            "title": card_payload.get("title", "").strip(),
            "subject": subject,
            "category": card_payload.get("category", "All").strip() or "All",
            "subtopic": card_payload.get("subtopic", "All").strip() or "All",
            "hints": list(card_payload.get("hints", [])),
            "answer": card_payload.get("answer", "").strip(),
            "natural_difficulty": int(card_payload.get("natural_difficulty", 5)),
            "created_at": card_payload.get("created_at") or self.now_iso(),
            "updated_at": self.now_iso(),
        }
        run_id = str(card_payload.get("run_id", "")).strip()
        if run_id:
            record["run_id"] = run_id
        cards = self.load_subject_cards(subject)
        cards = [item for item in cards if item.get("id") != record["id"]]
        cards.append(record)
        self.save_subject_cards(subject, cards)
        return record

    def delete_cards_by_run(self, run_id: str) -> int:
        removed = 0
        for subject in SUBJECT_TAXONOMY:
            cards = self.load_subject_cards(subject)
            keep = [card for card in cards if card.get("run_id") != run_id]
            removed += len(cards) - len(keep)
            if len(keep) != len(cards):
                self.save_subject_cards(subject, keep)
        return removed

    def delete_card(self, card_id: str, subject: str) -> bool:
        cards = self.load_subject_cards(subject)
        keep = [card for card in cards if card.get("id") != card_id]
        if len(keep) == len(cards):
            return False
        self.save_subject_cards(subject, keep)
        return True

    def move_card(self, card_id: str, old_subject: str, new_subject: str, updates: dict) -> dict | None:
        old_cards = self.load_subject_cards(old_subject)
        target = None
        keep = []
        for card in old_cards:
            if card.get("id") == card_id:
                target = card
            else:
                keep.append(card)
        if target is None:
            return None
        self.save_subject_cards(old_subject, keep)
        target["subject"] = new_subject
        target["category"] = updates.get("category", target.get("category", "All"))
        target["subtopic"] = updates.get("subtopic", target.get("subtopic", "All"))
        target["updated_at"] = self.now_iso()
        new_cards = self.load_subject_cards(new_subject)
        new_cards.append(target)
        self.save_subject_cards(new_subject, new_cards)
        return target

    def load_attempts(self) -> list[dict]:
        return self._read_json(self.paths.study_history_file, [])

    def save_attempt(self, attempt: dict) -> None:
        attempts = self.load_attempts()
        attempts.append(attempt)
        self._write_json(self.paths.study_history_file, attempts)
