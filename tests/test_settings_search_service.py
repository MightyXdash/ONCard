from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.data_store import DataStore
from studymate.services.settings_search_service import SETTINGS_SEARCH_CACHE_KEY, SettingsSearchService
from studymate.utils.paths import AppPaths


class SettingsSearchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()
        self.store = DataStore(self.paths)
        self.service = SettingsSearchService(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def test_ensure_index_persists_seed_entries_and_vectors(self) -> None:
        payload = self.service.ensure_index()

        self.assertIn("entries", payload)
        self.assertGreater(len(payload["entries"]), 20)
        self.assertEqual(payload, self.store.load_cache_entry(SETTINGS_SEARCH_CACHE_KEY))

        sample = payload["entries"][0]
        self.assertEqual(5, len(sample["queries"]))
        self.assertTrue(sample["search_text"].startswith("Tab:"))
        self.assertGreater(len(sample["vector"]), 0)
        self.assertTrue(any(abs(float(value)) > 0.0 for value in sample["vector"]))

    def test_top_match_finds_profile_attention_span(self) -> None:
        result = self.service.top_match("how do i change minutes per question")

        self.assertIsNotNone(result)
        self.assertEqual("general.profile.attention_span", result["target_key"])

    def test_top_match_finds_cloud_api_key(self) -> None:
        result = self.service.top_match("where do i paste ollama api key")

        self.assertIsNotNone(result)
        self.assertEqual("ai.cloud.api_key", result["target_key"])

    def test_suggestions_rank_audio_click_sound(self) -> None:
        results = self.service.suggestions("click sound", limit=3)
        targets = [entry["target_key"] for entry in results]

        self.assertIn("audio.click_sound", targets)


if __name__ == "__main__":
    unittest.main()
