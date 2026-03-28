from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.data_store import DataStore
from studymate.utils.paths import AppPaths


class SqlDataStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_defaults_include_sql_backed_performance_settings(self) -> None:
        store = DataStore(self.paths)
        setup = store.load_setup()
        performance = dict(setup.get("performance", {}))
        self.assertEqual("auto", performance.get("mode"))
        self.assertEqual(8, performance.get("startup_workers"))
        self.assertEqual(2, performance.get("background_workers"))
        self.assertTrue(performance.get("warm_cache_on_startup"))
        self.assertFalse(performance.get("reduced_motion"))
        self.assertTrue(self.paths.database_file.exists())
        store.close()

    def test_migrates_legacy_json_into_sql_and_keeps_backup(self) -> None:
        setup_payload = {"onboarding_complete": True, "performance": {"mode": "manual", "background_workers": 4}}
        profile_payload = {"name": "Ava", "age": "17", "grade": "Grade 11"}
        ai_payload = {"files_to_cards_ocr": False, "followup_context_length": 16384}
        cards_payload = [
            {
                "id": "card-1",
                "title": "Photosynthesis",
                "question": "What does photosynthesis do?",
                "answer": "Turns light into chemical energy.",
                "subject": "Science",
                "category": "Biology",
                "subtopic": "Plants",
                "hints": ["Think chloroplasts"],
                "search_terms": ["photosynthesis", "plants"],
                "natural_difficulty": 4,
            }
        ]
        attempts_payload = [
            {
                "card_id": "card-1",
                "timestamp": "2026-03-01T00:00:00+00:00",
                "marks_out_of_10": 8.0,
                "how_good": 97.0,
                "temporary": False,
            }
        ]
        embeddings_payload = {
            "card-1:hash:nomic": {
                "card_id": "card-1",
                "model_tag": "nomic-embed-text-v2-moe",
                "content_hash": "hash",
                "vector": [0.1, 0.2, 0.3],
                "embedded_at": "2026-03-01T00:00:00+00:00",
            }
        }

        self.paths.setup_config.write_text(json.dumps(setup_payload), encoding="utf-8")
        self.paths.profile_config.write_text(json.dumps(profile_payload), encoding="utf-8")
        self.paths.ai_settings_config.write_text(json.dumps(ai_payload), encoding="utf-8")
        (self.paths.subjects / "science.json").write_text(json.dumps(cards_payload), encoding="utf-8")
        self.paths.study_history_file.write_text(json.dumps(attempts_payload), encoding="utf-8")
        self.paths.embedding_cache_file.write_text(json.dumps(embeddings_payload), encoding="utf-8")

        store = DataStore(self.paths)

        loaded_setup = store.load_setup()
        self.assertTrue(loaded_setup["onboarding_complete"])
        self.assertEqual("manual", loaded_setup["performance"]["mode"])
        self.assertEqual(4, loaded_setup["performance"]["background_workers"])
        self.assertEqual("Ava", store.load_profile()["name"])
        self.assertFalse(store.load_ai_settings()["files_to_cards_ocr"])
        self.assertEqual(1, len(store.list_all_cards()))
        self.assertEqual(1, len(store.load_attempts()))
        self.assertEqual(1, len(store.load_embedding_cache()))

        backups = [path for path in self.paths.backups.iterdir() if path.is_dir()]
        self.assertTrue(backups)
        store.close()

    def test_migration_imports_legacy_subject_files_not_in_taxonomy(self) -> None:
        legacy_card = {
            "id": "legacy-card",
            "title": "Legacy",
            "question": "Legacy question?",
            "answer": "Legacy answer.",
            "subject": "Legacy Subject",
            "category": "Archive",
            "subtopic": "Older",
        }
        (self.paths.subjects / "legacy_subject.json").write_text(json.dumps([legacy_card]), encoding="utf-8")

        store = DataStore(self.paths)
        cards = store.list_all_cards()
        self.assertEqual(1, len(cards))
        self.assertEqual("legacy-card", cards[0]["id"])
        store.close()

    def test_embedding_record_lookup_does_not_require_full_cache_copy(self) -> None:
        store = DataStore(self.paths)
        store.upsert_embedding_cache_record(
            "card-1:hash:model",
            {
                "card_id": "card-1",
                "model_tag": "model",
                "content_hash": "hash",
                "vector": [0.1, 0.2],
                "embedded_at": "2026-03-01T00:00:00+00:00",
            },
        )
        record = store.get_embedding_cache_record("card-1:hash:model")
        self.assertIsNotNone(record)
        self.assertTrue(store.has_embedding_cache_record("card-1:hash:model"))
        self.assertEqual([0.1, 0.2], record["vector"])
        store.close()

    def test_startup_snapshot_warms_visible_cards_and_nna_preview(self) -> None:
        store = DataStore(self.paths)
        for index in range(6):
            store.save_card(
                {
                    "id": f"card-{index}",
                    "title": f"Card {index}",
                    "question": f"Question {index}",
                    "answer": f"Answer {index}",
                    "subject": "Science",
                    "category": "Biology",
                    "subtopic": "Plants",
                }
            )
        store.save_attempt(
            {
                "card_id": "card-1",
                "timestamp": "2026-03-01T00:00:00+00:00",
                "how_good": 70.0,
                "marks_out_of_10": 5.0,
                "temporary": False,
            }
        )

        snapshot = store.startup_snapshot(visible_limit=3, startup_workers=4, persist=True)
        self.assertEqual(3, len(snapshot["visible_cards"]))
        self.assertEqual(6, snapshot["nna_preview"]["card_count"])
        self.assertEqual(["card-1"], snapshot["nna_preview"]["weak_cards"])
        self.assertIsNotNone(store.load_cache_entry("startup_snapshot"))
        store.close()


if __name__ == "__main__":
    unittest.main()
