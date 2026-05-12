from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any
import uuid

from studymate.constants import SUBJECT_TAXONOMY
from studymate.services.model_registry import DEFAULT_TEXT_LLM_KEY, normalize_ai_settings
from studymate.utils.paths import AppPaths


SQL_SCHEMA_VERSION = 1

CARD_CORE_FIELDS = {
    "id",
    "question",
    "title",
    "subject",
    "category",
    "subtopic",
    "hints",
    "search_terms",
    "answer",
    "natural_difficulty",
    "run_id",
    "created_at",
    "updated_at",
}


class DataStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.paths.database_file), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._configure_connection(self._conn)
        self._settings_cache: dict[str, dict] = {}
        self._cards_cache: list[dict] | None = None
        self._attempts_cache: list[dict] | None = None
        self._embedding_cache: dict[str, dict[str, Any]] | None = None
        self._embedding_card_index: dict[str, set[str]] | None = None
        self._subject_counts_cache: dict[str, int] | None = None
        self._fts_enabled = False

        with self._lock:
            self._create_schema()
            self._migrate_legacy_json_if_needed()
            self._ensure_default_settings()

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA cache_size=-16000")

    @staticmethod
    def _read_json(path: Path, default: dict | list):
        if not path.exists():
            return copy.deepcopy(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return copy.deepcopy(default)

    @staticmethod
    def _write_json(path: Path, data: dict | list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def default_setup(cls) -> dict:
        return {
            "onboarding_complete": False,
            "ram_gb": 0,
            "advanced_installation": False,
            "selected_models": [],
            "installed_models": {},
            "performance_arena": {"skipped": True, "avg_tps": None, "tier": ""},
            "embedding_gate_declined_version": "",
            "embedding_gate_prompted_version": "",
            "appearance": {
                "theme": "light",
            },
            "performance": {
                "mode": "auto",
                "startup_workers": 8,
                "background_workers": 2,
                "warm_cache_on_startup": True,
                "reduced_motion": False,
            },
            "stats": {
                "default_range": "daily",
            },
            "audio": {
                "enabled": True,
                "click_enabled": True,
                "click_sound": "click3",
                "transition_enabled": True,
                "transition_sound": "woosh",
                "notification_sound": "windows",
            },
            "notifications": {
                "enabled": True,
            },
            "mcq": {
                "enabled": False,
            },
            "updated_at": cls.now_iso(),
        }

    @classmethod
    def default_profile(cls) -> dict:
        now = cls.now_iso()
        return {
            "name": "",
            "profile_name": "",
            "age": "",
            "grade": "",
            "gender": "",
            "hobbies": "",
            "avatar_category": "",
            "avatar_file": "",
            "avatar_index": "",
            "attention_span_minutes": 5,
            "question_focus_level": 5,
            "created_at": now,
            "updated_at": now,
        }

    @classmethod
    def default_ai_settings(cls) -> dict:
        return {
            "assistant_tone": "",
            "ask_ai_tone": "warm",
            "ask_ai_emoji_level": 2,
            "use_selected_llm_for_text_features": False,
            "selected_text_llm_key": DEFAULT_TEXT_LLM_KEY,
            "ollama_cloud_enabled": False,
            "ollama_cloud_api_key": "",
            "ollama_cloud_selected_model_tag": "",
            "selected_ocr_llm_key": DEFAULT_TEXT_LLM_KEY,
            "autofill_context_length": 8192,
            "grading_context_length": 8192,
            "mcq_context_length": 8192,
            "discuss_context_length": 8192,
            "ask_ai_planner_context_length": 4400,
            "ask_ai_answer_context_length": 9216,
            "ask_ai_image_context_length": 8192,
            "wiki_breakdown_context_length": 6000,
            "followup_context_length": 9216,
            "reinforcement_context_length": 8192,
            "files_to_cards_ocr_context_length": 8192,
            "files_to_cards_paper_context_length": 8192,
            "files_to_cards_cards_context_length": 8192,
            "stats_context_length": 4000,
            "autofill_model_key": "",
            "grading_model_key": "",
            "mcq_model_key": "",
            "ask_ai_planner_model_key": "",
            "ask_ai_answer_model_key": "",
            "ask_ai_image_model_key": "",
            "wiki_breakdown_model_key": "",
            "followup_model_key": "",
            "followup_reasoning_mode": "instant",
            "reinforcement_model_key": "",
            "files_to_cards_ocr_model_key": "",
            "files_to_cards_paper_model_key": "",
            "files_to_cards_cards_model_key": "",
            "stats_model_key": "",
            "files_to_cards_ocr": True,
            "neural_acceleration": True,
            "image_search_term_count": 4,
            "updated_at": cls.now_iso(),
        }

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                section TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                subject TEXT NOT NULL,
                category TEXT NOT NULL,
                subtopic TEXT NOT NULL,
                natural_difficulty INTEGER NOT NULL,
                hints_json TEXT NOT NULL,
                search_terms_json TEXT NOT NULL,
                search_terms_text TEXT NOT NULL DEFAULT '',
                run_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                extra_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_cards_subject ON cards(subject);
            CREATE INDEX IF NOT EXISTS idx_cards_subject_category ON cards(subject, category, subtopic);
            CREATE INDEX IF NOT EXISTS idx_cards_run_id ON cards(run_id);

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT,
                attempt_index INTEGER,
                session_id TEXT,
                timestamp TEXT NOT NULL,
                temporary INTEGER NOT NULL DEFAULT 0,
                marks_out_of_10 REAL,
                how_good REAL,
                topic_cluster_key TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_card_id ON attempts(card_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_timestamp ON attempts(timestamp DESC);

            CREATE TABLE IF NOT EXISTS embeddings (
                cache_key TEXT PRIMARY KEY,
                card_id TEXT NOT NULL,
                model_tag TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                embedded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_embeddings_card_id ON embeddings(card_id);

            CREATE TABLE IF NOT EXISTS cache_entries (
                key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self._set_meta("schema_version", str(SQL_SCHEMA_VERSION))
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS card_fts USING fts5(
                    card_id UNINDEXED,
                    title,
                    question,
                    answer,
                    search_terms
                )
                """
            )
            self._fts_enabled = True
        except sqlite3.OperationalError:
            self._fts_enabled = False
        self._conn.commit()

    def _migrate_legacy_json_if_needed(self) -> None:
        if self._meta("json_migration_complete") == "1":
            return
        if not self._legacy_json_exists():
            self._set_meta("json_migration_complete", "1")
            self._set_meta("json_migration_completed_at", self.now_iso())
            self._conn.commit()
            return

        backup_target = self._backup_legacy_json()
        setup = self._read_json(self.paths.setup_config, self.default_setup())
        profile = self._read_json(self.paths.profile_config, self.default_profile())
        ai_settings = self._read_json(self.paths.ai_settings_config, self.default_ai_settings())
        cards = self._legacy_cards()
        attempts = self._legacy_attempts()
        embeddings = self._legacy_embeddings()
        legacy_card_ids = {str(card.get("id", "")).strip() for card in cards if str(card.get("id", "")).strip()}
        legacy_embedding_keys = {str(cache_key).strip() for cache_key in embeddings if str(cache_key).strip()}

        with self._conn:
            self._save_section_locked("setup", self._merge_dict(self.default_setup(), setup))
            self._save_section_locked("profile", self._merge_dict(self.default_profile(), profile))
            self._save_section_locked("ai_settings", self._merge_dict(self.default_ai_settings(), ai_settings))
            existing_attempt_signatures = self._existing_attempt_signatures_locked()
            initial_attempt_count = len(existing_attempt_signatures)
            inserted_attempt_count = 0
            for card in cards:
                self._upsert_card_locked(card)
            for attempt in attempts:
                signature = self._attempt_signature(attempt)
                if signature in existing_attempt_signatures:
                    continue
                saved_attempt = self._insert_attempt_locked(attempt)
                existing_attempt_signatures.add(self._attempt_signature(saved_attempt))
                inserted_attempt_count += 1
            for cache_key, record in embeddings.items():
                self._upsert_embedding_locked(cache_key, record)
            missing_settings = [section for section in ("setup", "profile", "ai_settings") if self._load_section_locked(section) is None]
            if missing_settings:
                raise RuntimeError(f"Legacy migration failed: missing SQL settings sections: {', '.join(missing_settings)}")
            missing_card_ids = legacy_card_ids - self._existing_card_ids_locked(legacy_card_ids)
            if missing_card_ids:
                raise RuntimeError("Legacy migration failed: some cards were not imported into SQLite.")
            missing_embedding_keys = legacy_embedding_keys - self._existing_embedding_keys_locked(legacy_embedding_keys)
            if missing_embedding_keys:
                raise RuntimeError("Legacy migration failed: some embeddings were not imported into SQLite.")
            if self._scalar("SELECT COUNT(1) FROM attempts") < initial_attempt_count + inserted_attempt_count:
                raise RuntimeError("Legacy migration failed: some study attempts were not imported into SQLite.")
            self._set_meta("json_migration_complete", "1")
            self._set_meta("json_migration_completed_at", self.now_iso())
            if backup_target is not None:
                self._set_meta("legacy_backup_path", str(backup_target))
        self._clear_caches()

    def _ensure_default_settings(self) -> None:
        if self._load_section_locked("setup") is None:
            self._save_section_locked("setup", self.default_setup())
        if self._load_section_locked("profile") is None:
            self._save_section_locked("profile", self.default_profile())
        if self._load_section_locked("ai_settings") is None:
            self._save_section_locked("ai_settings", self.default_ai_settings())
        self._conn.commit()

    def _legacy_json_exists(self) -> bool:
        if self.paths.setup_config.exists() or self.paths.profile_config.exists() or self.paths.ai_settings_config.exists():
            return True
        if self.paths.study_history_file.exists() or self.paths.embedding_cache_file.exists():
            return True
        return any(True for _ in self._legacy_subject_files())

    def _has_sql_user_data(self) -> bool:
        return any(self._scalar(f"SELECT COUNT(1) FROM {table}") > 0 for table in ("settings", "cards", "attempts", "embeddings"))

    def _backup_legacy_json(self) -> Path | None:
        if not self._legacy_json_exists():
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.paths.backups / f"{timestamp}_legacy_json"
        target.mkdir(parents=True, exist_ok=True)
        for source in [self.paths.config, self.paths.subjects, self.paths.study_history]:
            if source.exists():
                shutil.copytree(source, target / source.name, dirs_exist_ok=True)
        if self.paths.embedding_cache_file.exists():
            runtime_target = target / "runtime"
            runtime_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.paths.embedding_cache_file, runtime_target / self.paths.embedding_cache_file.name)
        return target

    def _legacy_cards(self) -> list[dict]:
        cards: list[dict] = []
        for path in self._legacy_subject_files():
            raw = self._read_json(path, [])
            if not isinstance(raw, list):
                continue
            cards.extend(dict(item) for item in raw if isinstance(item, dict))
        return cards

    def _legacy_subject_files(self) -> list[Path]:
        if not self.paths.subjects.exists():
            return []
        return sorted(path for path in self.paths.subjects.glob("*.json") if path.is_file())

    def _legacy_attempts(self) -> list[dict]:
        raw = self._read_json(self.paths.study_history_file, [])
        return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    def _legacy_embeddings(self) -> dict[str, dict[str, Any]]:
        raw = self._read_json(self.paths.embedding_cache_file, {})
        if not isinstance(raw, dict):
            return {}
        return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}

    def _meta(self, key: str) -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return "" if row is None else str(row["value"])

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _load_section_locked(self, section: str) -> dict | None:
        row = self._conn.execute("SELECT payload_json FROM settings WHERE section = ?", (section,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _save_section_locked(self, section: str, payload: dict) -> None:
        updated = copy.deepcopy(payload)
        updated["updated_at"] = self.now_iso()
        self._conn.execute(
            """
            INSERT INTO settings(section, payload_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(section) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (section, json.dumps(updated, ensure_ascii=False), updated["updated_at"]),
        )
        self._settings_cache[section] = updated

    @staticmethod
    def _merge_dict(default: dict, override: dict) -> dict:
        merged = copy.deepcopy(default)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = DataStore._merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _load_section(self, section: str, default: dict) -> dict:
        with self._lock:
            payload = self._settings_cache.get(section)
            if payload is None:
                payload = self._load_section_locked(section)
                if payload is None:
                    payload = copy.deepcopy(default)
                    self._save_section_locked(section, payload)
                    self._conn.commit()
                self._settings_cache[section] = payload
            merged = self._merge_dict(default, payload)
            if section == "ai_settings":
                normalized = normalize_ai_settings(merged)
                if normalized != payload:
                    self._save_section_locked(section, normalized)
                    self._conn.commit()
                merged = normalized
            return merged

    def _save_section(self, section: str, payload: dict) -> None:
        with self._lock:
            if section == "ai_settings":
                payload = normalize_ai_settings(payload)
            self._save_section_locked(section, payload)
            self._conn.commit()

    def load_setup(self) -> dict:
        return self._load_section("setup", self.default_setup())

    def save_setup(self, payload: dict) -> None:
        self._save_section("setup", payload)

    def load_profile(self) -> dict:
        return self._load_section("profile", self.default_profile())

    def save_profile(self, payload: dict) -> None:
        self._save_section("profile", payload)

    def load_ai_settings(self) -> dict:
        return self._load_section("ai_settings", self.default_ai_settings())

    def save_ai_settings(self, payload: dict) -> None:
        self._save_section("ai_settings", payload)

    @staticmethod
    def subject_slug(subject: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in subject).strip("_")
        return cleaned or "general"

    def subject_path(self, subject: str) -> Path:
        return self.paths.subjects / f"{self.subject_slug(subject)}.json"

    def _normalize_card(self, card_payload: dict) -> dict:
        payload = dict(card_payload)
        record = {
            "id": str(payload.get("id") or uuid.uuid4()),
            "question": str(payload.get("question", "")).strip(),
            "title": str(payload.get("title", "")).strip(),
            "subject": str(payload.get("subject", "Mathematics")).strip() or "Mathematics",
            "category": str(payload.get("category", "All")).strip() or "All",
            "subtopic": str(payload.get("subtopic", "All")).strip() or "All",
            "hints": [str(item).strip() for item in list(payload.get("hints", [])) if str(item).strip()],
            "search_terms": [str(term).strip() for term in list(payload.get("search_terms", [])) if str(term).strip()][:5],
            "answer": str(payload.get("answer", "")).strip(),
            "natural_difficulty": int(payload.get("natural_difficulty", 5)),
            "run_id": str(payload.get("run_id", "")).strip(),
            "created_at": str(payload.get("created_at") or self.now_iso()),
            "updated_at": self.now_iso(),
        }
        extras = {key: value for key, value in payload.items() if key not in CARD_CORE_FIELDS}
        record.update(extras)
        return record

    def _split_card(self, card_payload: dict) -> tuple[dict, str]:
        normalized = self._normalize_card(card_payload)
        extras = {key: value for key, value in normalized.items() if key not in CARD_CORE_FIELDS}
        return normalized, json.dumps(extras, ensure_ascii=False)

    def _card_from_row(self, row: sqlite3.Row) -> dict:
        card = {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "question": str(row["question"]),
            "answer": str(row["answer"]),
            "subject": str(row["subject"]),
            "category": str(row["category"]),
            "subtopic": str(row["subtopic"]),
            "natural_difficulty": int(row["natural_difficulty"]),
            "hints": _json_list(row["hints_json"]),
            "search_terms": _json_list(row["search_terms_json"]),
            "run_id": str(row["run_id"] or ""),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        card.update(_json_dict(row["extra_json"]))
        return card

    def _upsert_card_locked(self, card_payload: dict) -> dict:
        card, extras_json = self._split_card(card_payload)
        self._conn.execute(
            """
            INSERT INTO cards(
                id, title, question, answer, subject, category, subtopic,
                natural_difficulty, hints_json, search_terms_json, search_terms_text,
                run_id, created_at, updated_at, extra_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                question = excluded.question,
                answer = excluded.answer,
                subject = excluded.subject,
                category = excluded.category,
                subtopic = excluded.subtopic,
                natural_difficulty = excluded.natural_difficulty,
                hints_json = excluded.hints_json,
                search_terms_json = excluded.search_terms_json,
                search_terms_text = excluded.search_terms_text,
                run_id = excluded.run_id,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                extra_json = excluded.extra_json
            """,
            (
                card["id"],
                card["title"],
                card["question"],
                card["answer"],
                card["subject"],
                card["category"],
                card["subtopic"],
                int(card["natural_difficulty"]),
                json.dumps(card["hints"], ensure_ascii=False),
                json.dumps(card["search_terms"], ensure_ascii=False),
                " ".join(card["search_terms"]),
                card["run_id"],
                card["created_at"],
                card["updated_at"],
                extras_json,
            ),
        )
        if self._fts_enabled:
            self._conn.execute("DELETE FROM card_fts WHERE card_id = ?", (card["id"],))
            self._conn.execute(
                """
                INSERT INTO card_fts(card_id, title, question, answer, search_terms)
                VALUES(?, ?, ?, ?, ?)
                """,
                (card["id"], card["title"], card["question"], card["answer"], " ".join(card["search_terms"])),
            )
        self._invalidate_cards_cache()
        return card

    def save_card(self, card_payload: dict) -> dict:
        with self._lock:
            saved = self._upsert_card_locked(card_payload)
            self._conn.commit()
            return saved

    def _load_cards_locked(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM cards ORDER BY datetime(updated_at) DESC, rowid DESC").fetchall()
        cards = [self._card_from_row(row) for row in rows]
        self._cards_cache = cards
        self._subject_counts_cache = None
        return cards

    def list_all_cards(self) -> list[dict]:
        with self._lock:
            if self._cards_cache is None:
                self._load_cards_locked()
            return [copy.deepcopy(card) for card in (self._cards_cache or [])]

    def load_subject_cards(self, subject: str) -> list[dict]:
        return [card for card in self.list_all_cards() if str(card.get("subject", "")) == subject]

    def save_subject_cards(self, subject: str, cards: list[dict]) -> None:
        with self._lock:
            existing = {str(card.get("id", "")): card for card in self.load_subject_cards(subject)}
            incoming = {str(card.get("id", "")): dict(card) for card in cards if str(card.get("id", "")).strip()}
            for card_id, payload in incoming.items():
                payload["subject"] = subject
                if card_id in existing:
                    payload.setdefault("created_at", existing[card_id].get("created_at"))
                self._upsert_card_locked(payload)
            for card_id in set(existing) - set(incoming):
                self._delete_card_locked(card_id)
            self._conn.commit()

    def card_counts_by_subject(self) -> dict[str, int]:
        with self._lock:
            if self._subject_counts_cache is None:
                counts = {subject: 0 for subject in SUBJECT_TAXONOMY}
                rows = self._conn.execute("SELECT subject, COUNT(1) AS count_value FROM cards GROUP BY subject").fetchall()
                for row in rows:
                    subject = str(row["subject"])
                    if subject in counts:
                        counts[subject] = int(row["count_value"])
                self._subject_counts_cache = counts
            return dict(self._subject_counts_cache)

    def _delete_card_locked(self, card_id: str) -> None:
        self._conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        if self._fts_enabled:
            self._conn.execute("DELETE FROM card_fts WHERE card_id = ?", (card_id,))
        self._conn.execute("DELETE FROM embeddings WHERE card_id = ?", (card_id,))
        if self._embedding_cache is not None:
            if self._embedding_card_index is None:
                self._load_embeddings_locked()
            for cache_key in list((self._embedding_card_index or {}).get(card_id, set())):
                self._embedding_cache.pop(cache_key, None)
            if self._embedding_card_index is not None:
                self._embedding_card_index.pop(card_id, None)
        self._invalidate_cards_cache()

    def delete_cards_by_run(self, run_id: str) -> int:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM cards WHERE run_id = ?", (run_id,)).fetchall()
            for row in rows:
                self._delete_card_locked(str(row["id"]))
            self._conn.commit()
            return len(rows)

    def delete_card(self, card_id: str, subject: str) -> bool:
        del subject
        with self._lock:
            row = self._conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
            if row is None:
                return False
            self._delete_card_locked(card_id)
            self._conn.commit()
            return True

    def move_card(self, card_id: str, old_subject: str, new_subject: str, updates: dict) -> dict | None:
        del old_subject
        with self._lock:
            row = self._conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            if row is None:
                return None
            card = self._card_from_row(row)
            card["subject"] = new_subject
            card["category"] = updates.get("category", card.get("category", "All"))
            card["subtopic"] = updates.get("subtopic", card.get("subtopic", "All"))
            moved = self._upsert_card_locked(card)
            self._conn.commit()
            return moved

    def _load_attempts_locked(self) -> list[dict]:
        rows = self._conn.execute("SELECT payload_json FROM attempts ORDER BY datetime(timestamp) ASC, id ASC").fetchall()
        attempts: list[dict] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                attempts.append(payload)
        self._attempts_cache = attempts
        return attempts

    def load_attempts(self) -> list[dict]:
        with self._lock:
            if self._attempts_cache is None:
                self._load_attempts_locked()
            return [copy.deepcopy(item) for item in (self._attempts_cache or [])]

    def _insert_attempt_locked(self, attempt: dict) -> dict:
        payload = dict(attempt)
        card_id = str(payload.get("card_id", "")).strip()
        if "attempt_index" not in payload or payload.get("attempt_index") in (None, 0, ""):
            prior = self._scalar("SELECT COUNT(1) FROM attempts WHERE card_id = ?", (card_id,)) if card_id else 0
            payload["attempt_index"] = prior + 1 if card_id else 1
        payload.setdefault("timestamp", self.now_iso())
        self._conn.execute(
            """
            INSERT INTO attempts(
                card_id, attempt_index, session_id, timestamp, temporary,
                marks_out_of_10, how_good, topic_cluster_key, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                int(payload.get("attempt_index", 1) or 1),
                str(payload.get("session_id", "")).strip(),
                str(payload.get("timestamp", self.now_iso())),
                1 if bool(payload.get("temporary", False)) else 0,
                _coerce_float(payload.get("marks_out_of_10")),
                _coerce_float(payload.get("how_good")),
                str(payload.get("topic_cluster_key", "")).strip(),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self._attempts_cache = None
        return payload

    @staticmethod
    def _attempt_signature(attempt: dict) -> str:
        return json.dumps(attempt, ensure_ascii=False, sort_keys=True)

    def _existing_attempt_signatures_locked(self) -> set[str]:
        rows = self._conn.execute("SELECT payload_json FROM attempts").fetchall()
        signatures: set[str] = set()
        for row in rows:
            payload_json = str(row["payload_json"] or "")
            if not payload_json:
                continue
            try:
                parsed = json.loads(payload_json)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                signatures.add(self._attempt_signature(parsed))
        return signatures

    def save_attempt(self, attempt: dict) -> None:
        with self._lock:
            self._insert_attempt_locked(attempt)
            self._conn.commit()

    def save_attempts(self, attempts: list[dict]) -> None:
        with self._lock:
            for attempt in attempts:
                self._insert_attempt_locked(attempt)
            self._conn.commit()

    def _load_embeddings_locked(self) -> dict[str, dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM embeddings").fetchall()
        cache: dict[str, dict[str, Any]] = {}
        card_index: dict[str, set[str]] = {}
        for row in rows:
            try:
                vector = json.loads(str(row["vector_json"]))
            except json.JSONDecodeError:
                continue
            if not isinstance(vector, list):
                continue
            cache_key = str(row["cache_key"])
            card_id = str(row["card_id"])
            cache[cache_key] = {
                "card_id": card_id,
                "model_tag": str(row["model_tag"]),
                "content_hash": str(row["content_hash"]),
                "vector": [float(item) for item in vector],
                "embedded_at": str(row["embedded_at"]),
            }
            card_index.setdefault(card_id, set()).add(cache_key)
        self._embedding_cache = cache
        self._embedding_card_index = card_index
        return cache

    def load_embedding_cache(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if self._embedding_cache is None:
                self._load_embeddings_locked()
            return copy.deepcopy(self._embedding_cache or {})

    def has_embedding_cache_record(self, cache_key: str) -> bool:
        with self._lock:
            if self._embedding_cache is None:
                self._load_embeddings_locked()
            return bool(self._embedding_cache and cache_key in self._embedding_cache)

    def get_embedding_cache_record(self, cache_key: str) -> dict[str, Any] | None:
        with self._lock:
            if self._embedding_cache is None:
                self._load_embeddings_locked()
            if not self._embedding_cache:
                return None
            record = self._embedding_cache.get(cache_key)
            if not isinstance(record, dict):
                return None
            return {
                "card_id": str(record.get("card_id", "")),
                "model_tag": str(record.get("model_tag", "")),
                "content_hash": str(record.get("content_hash", "")),
                "vector": [float(item) for item in list(record.get("vector", []))],
                "embedded_at": str(record.get("embedded_at", "")),
            }

    def _upsert_embedding_locked(self, cache_key: str, record: dict[str, Any]) -> None:
        vector = [float(item) for item in list(record.get("vector", []))]
        self._conn.execute(
            """
            INSERT INTO embeddings(cache_key, card_id, model_tag, content_hash, vector_json, embedded_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                card_id = excluded.card_id,
                model_tag = excluded.model_tag,
                content_hash = excluded.content_hash,
                vector_json = excluded.vector_json,
                embedded_at = excluded.embedded_at
            """,
            (
                cache_key,
                str(record.get("card_id", "")),
                str(record.get("model_tag", "")),
                str(record.get("content_hash", "")),
                json.dumps(vector),
                str(record.get("embedded_at", self.now_iso())),
            ),
        )
        if self._embedding_cache is not None:
            self._embedding_cache[cache_key] = {
                "card_id": str(record.get("card_id", "")),
                "model_tag": str(record.get("model_tag", "")),
                "content_hash": str(record.get("content_hash", "")),
                "vector": vector,
                "embedded_at": str(record.get("embedded_at", self.now_iso())),
            }
            if self._embedding_card_index is None:
                self._embedding_card_index = {}
            self._embedding_card_index.setdefault(str(record.get("card_id", "")), set()).add(cache_key)

    def upsert_embedding_cache_record(self, cache_key: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._upsert_embedding_locked(cache_key, record)
            self._conn.commit()

    def remove_embedding_cache_record(self, cache_key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM embeddings WHERE cache_key = ?", (cache_key,))
            if self._embedding_cache is not None and cache_key in self._embedding_cache:
                record = self._embedding_cache.pop(cache_key)
                if self._embedding_card_index is not None:
                    card_id = str(record.get("card_id", ""))
                    keys = self._embedding_card_index.get(card_id)
                    if keys is not None:
                        keys.discard(cache_key)
                        if not keys:
                            self._embedding_card_index.pop(card_id, None)
            self._conn.commit()

    def load_cache_entry(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT payload_json FROM cache_entries WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                return None
            return payload if isinstance(payload, dict) else None

    def put_cache_entry(self, key: str, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO cache_entries(key, payload_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(payload, ensure_ascii=False), self.now_iso()),
            )
            self._conn.commit()

    def search_cards_fts(
        self,
        query: str,
        *,
        limit: int = 64,
        subject: str | None = None,
        category: str | None = None,
        subtopic: str | None = None,
    ) -> list[dict]:
        normalized = _normalize_fts_query(query)
        if not normalized:
            return []
        with self._lock:
            if self._fts_enabled:
                sql = """
                    SELECT c.*
                    FROM card_fts f
                    JOIN cards c ON c.id = f.card_id
                    WHERE card_fts MATCH ?
                """
                params: list[Any] = [normalized]
                if subject and subject != "All Subjects":
                    sql += " AND c.subject = ?"
                    params.append(subject)
                if category and category != "All":
                    sql += " AND c.category = ?"
                    params.append(category)
                if subtopic and subtopic != "All":
                    sql += " AND c.subtopic = ?"
                    params.append(subtopic)
                sql += " ORDER BY bm25(card_fts), datetime(c.updated_at) DESC LIMIT ?"
                params.append(limit)
                rows = self._conn.execute(sql, tuple(params)).fetchall()
                return [self._card_from_row(row) for row in rows]
        lowered = query.lower().strip()
        results: list[dict] = []
        for card in self.list_all_cards():
            if subject and subject != "All Subjects" and card.get("subject") != subject:
                continue
            if category and category != "All" and card.get("category") != category:
                continue
            if subtopic and subtopic != "All" and card.get("subtopic") != subtopic:
                continue
            haystack = " ".join(
                [
                    str(card.get("title", "")).lower(),
                    str(card.get("question", "")).lower(),
                    str(card.get("answer", "")).lower(),
                    " ".join(str(term).lower() for term in card.get("search_terms", [])),
                ]
            )
            if lowered in haystack:
                results.append(card)
            if len(results) >= limit:
                break
        return results

    def warm_cards_in_memory(self) -> list[dict]:
        with self._lock:
            return self._load_cards_locked()

    def warm_attempts_in_memory(self) -> list[dict]:
        with self._lock:
            return self._load_attempts_locked()

    def warm_embeddings_in_memory(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return self._load_embeddings_locked()

    def warm_subject_counts(self) -> dict[str, int]:
        return self.card_counts_by_subject()

    def startup_snapshot(self, *, visible_limit: int = 48, startup_workers: int = 8, persist: bool = True) -> dict[str, Any]:
        del startup_workers
        results = {
            "settings": self.load_setup(),
            "profile": self.load_profile(),
            "ai_settings": self.load_ai_settings(),
            "cards": self.warm_cards_in_memory(),
            "attempts": self.warm_attempts_in_memory(),
            "embeddings": self.warm_embeddings_in_memory(),
            "subject_counts": self.warm_subject_counts(),
        }

        cards = list(results["cards"])
        attempts = list(results["attempts"])
        embeddings = dict(results["embeddings"])
        snapshot = {
            "settings": results["settings"],
            "profile": results["profile"],
            "ai_settings": results["ai_settings"],
            "visible_cards": [copy.deepcopy(card) for card in cards[: max(1, visible_limit)]],
            "subject_counts": dict(results["subject_counts"]),
            "attempt_count": len(attempts),
            "embedding_count": len(embeddings),
            "nna_preview": self._simulate_nna_preview(cards, attempts),
            "created_at": self.now_iso(),
        }
        if persist:
            self.put_cache_entry("startup_snapshot", snapshot)
        return snapshot

    def _simulate_nna_preview(self, cards: list[dict], attempts: list[dict]) -> dict[str, Any]:
        recent_attempts = attempts[-64:]
        weak_card_ids: list[str] = []
        for attempt in recent_attempts:
            score = _coerce_float(attempt.get("how_good"))
            if score is None or score >= 88.8888:
                continue
            card_id = str(attempt.get("card_id", "")).strip()
            if card_id and card_id not in weak_card_ids:
                weak_card_ids.append(card_id)
        return {
            "card_count": len(cards),
            "recent_attempts": len(recent_attempts),
            "weak_cards": weak_card_ids[:12],
        }

    def close(self) -> None:
        with self._lock:
            if getattr(self, "_conn", None) is None:
                return
            try:
                self._conn.commit()
            except sqlite3.Error:
                pass
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None  # type: ignore[assignment]

    def _scalar(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        row = self._conn.execute(sql, params).fetchone()
        if row is None:
            return 0
        value = row[0]
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _invalidate_cards_cache(self) -> None:
        self._cards_cache = None
        self._subject_counts_cache = None

    def _clear_caches(self) -> None:
        self._settings_cache = {}
        self._cards_cache = None
        self._attempts_cache = None
        self._embedding_cache = None
        self._embedding_card_index = None
        self._subject_counts_cache = None

    def _existing_card_ids_locked(self, card_ids: set[str]) -> set[str]:
        if not card_ids:
            return set()
        placeholders = ", ".join("?" for _ in card_ids)
        rows = self._conn.execute(f"SELECT id FROM cards WHERE id IN ({placeholders})", tuple(card_ids)).fetchall()
        return {str(row["id"]) for row in rows}

    def _existing_embedding_keys_locked(self, cache_keys: set[str]) -> set[str]:
        if not cache_keys:
            return set()
        placeholders = ", ".join("?" for _ in cache_keys)
        rows = self._conn.execute(
            f"SELECT cache_key FROM embeddings WHERE cache_key IN ({placeholders})",
            tuple(cache_keys),
        ).fetchall()
        return {str(row["cache_key"]) for row in rows}


def _json_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _json_dict(value: object) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _coerce_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_fts_query(query: str) -> str:
    terms = [term.strip().replace('"', " ") for term in str(query).split() if term.strip()]
    cleaned = []
    for term in terms[:8]:
        letters = "".join(ch for ch in term if ch.isalnum() or ch in {"_", "-"})
        if letters:
            cleaned.append(f'"{letters}"')
    return " ".join(cleaned)
