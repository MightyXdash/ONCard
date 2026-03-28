from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.data_store import DataStore
from studymate.services.embedding_service import EmbeddingService
from studymate.services.recommendation_service import build_global_recommendations
from studymate.services.study_intelligence import build_session_state, enqueue_similar_cards, refresh_topic_clusters, register_grade_result
from studymate.ui.study_tab import StudyTab
from studymate.utils.paths import AppPaths


class FakeOllama:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_text(self, model_tag: str, text: str) -> list[float]:
        self.calls.append(f"{model_tag}:{text}")
        lowered = text.lower()
        if "topic a bridge" in lowered:
            return [0.94, 0.06, 0.0]
        if "topic a strong" in lowered:
            return [0.98, 0.02, 0.0]
        if "topic a" in lowered:
            return [1.0, 0.0, 0.0]
        if "topic b" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.5, 0.5, 0.0]


class NnaServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()
        self.datastore = DataStore(self.paths)
        self.ollama = FakeOllama()
        self.embedding_service = EmbeddingService(self.datastore, self.ollama)

    def tearDown(self) -> None:
        self.datastore.close()
        self.tempdir.cleanup()

    def _card(self, card_id: str, topic: str) -> dict:
        return {
            "id": card_id,
            "title": f"{topic} title",
            "question": f"{topic} question",
            "answer": f"{topic} answer",
            "subject": "Science",
            "category": "Chemistry",
            "subtopic": topic,
            "hints": ["hint one", "hint two", "hint three"],
            "natural_difficulty": 5,
        }

    def test_embedding_reuses_cached_record_until_content_changes(self) -> None:
        card = self._card("1", "Topic A")
        first = self.embedding_service.ensure_card_embedding(card)
        second = self.embedding_service.ensure_card_embedding(card)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(1, len(self.ollama.calls))

        changed = dict(card)
        changed["answer"] = "Topic A answer updated"
        third = self.embedding_service.ensure_card_embedding(changed)
        self.assertNotEqual(first.content_hash, third.content_hash)
        self.assertEqual(2, len(self.ollama.calls))

    def test_nna_enables_only_when_pool_has_more_than_five_cards(self) -> None:
        small = [self._card(str(idx), f"Topic {idx}") for idx in range(5)]
        large = [self._card(str(idx), f"Topic {idx}") for idx in range(6)]
        self.assertFalse(build_session_state(small, "scope").nna_enabled)
        self.assertTrue(build_session_state(large, "scope").nna_enabled)

    def test_three_consecutive_weak_scores_trigger_reinforcement(self) -> None:
        cards = [self._card(str(idx), "Topic A") for idx in range(6)]
        for card in cards:
            self.embedding_service.ensure_card_embedding(card)
        state = build_session_state(cards, "Science")
        refresh_topic_clusters(state, self.embedding_service)

        result = None
        for card in cards[:3]:
            result = register_grade_result(state, card, {"how_good": 70.0})

        self.assertIsNotNone(result)
        self.assertTrue(result["weak"])
        self.assertTrue(result["trigger_reinforcement"])

    def test_weak_topic_enqueue_prioritizes_similar_unseen_cards(self) -> None:
        cards = [
            self._card("1", "Topic A"),
            self._card("2", "Topic A"),
            self._card("3", "Topic A"),
            self._card("4", "Topic B"),
            self._card("5", "Topic B"),
            self._card("6", "Topic C"),
        ]
        for card in cards:
            self.embedding_service.ensure_card_embedding(card)
        state = build_session_state(cards, "Science")
        refresh_topic_clusters(state, self.embedding_service)
        cluster_key, count = enqueue_similar_cards(state, cards[0], self.embedding_service)

        self.assertTrue(cluster_key)
        self.assertGreaterEqual(count, 1)
        self.assertIn("2", state.priority_ids + state.deferred_ids)

    def test_recommendations_return_weak_cards_with_strong_similar_anchors(self) -> None:
        weak_card = self._card("weak", "Topic A bridge")
        strong_card = self._card("strong", "Topic A strong")
        unrelated_card = self._card("other", "Topic B")
        for card in [weak_card, strong_card, unrelated_card]:
            self.embedding_service.ensure_card_embedding(card)

        attempts = [
            {
                "card_id": "weak",
                "marks_out_of_10": 5.0,
                "how_good": 72.0,
                "temporary": False,
                "timestamp": "2026-01-03T00:00:00+00:00",
            },
            {
                "card_id": "strong",
                "marks_out_of_10": 9.0,
                "how_good": 97.0,
                "temporary": False,
                "timestamp": "2026-01-02T00:00:00+00:00",
            },
            {
                "card_id": "other",
                "marks_out_of_10": 4.0,
                "how_good": 60.0,
                "temporary": False,
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
        ]

        recommendations = build_global_recommendations(
            [weak_card, strong_card, unrelated_card],
            attempts,
            self.embedding_service,
            limit=10,
        )

        self.assertEqual(1, len(recommendations))
        self.assertEqual("weak", recommendations[0].card["id"])
        self.assertEqual("strong", recommendations[0].reason_anchor_card_id)
        self.assertGreaterEqual(recommendations[0].reason_similarity, 0.80)

    def test_recommendations_ignore_temporary_attempts(self) -> None:
        weak_card = self._card("weak", "Topic A bridge")
        strong_card = self._card("strong", "Topic A strong")
        for card in [weak_card, strong_card]:
            self.embedding_service.ensure_card_embedding(card)

        attempts = [
            {
                "card_id": "weak",
                "marks_out_of_10": 3.0,
                "how_good": 55.0,
                "temporary": True,
                "timestamp": "2026-01-03T00:00:00+00:00",
            },
            {
                "card_id": "strong",
                "marks_out_of_10": 9.0,
                "how_good": 97.0,
                "temporary": False,
                "timestamp": "2026-01-02T00:00:00+00:00",
            },
        ]

        recommendations = build_global_recommendations(
            [weak_card, strong_card],
            attempts,
            self.embedding_service,
            limit=10,
        )

        self.assertEqual([], recommendations)

    def test_recommendations_skip_missing_embeddings_without_crashing(self) -> None:
        weak_card = self._card("weak", "Topic A bridge")
        strong_card = self._card("strong", "Topic A strong")
        self.embedding_service.ensure_card_embedding(strong_card)

        attempts = [
            {
                "card_id": "weak",
                "marks_out_of_10": 5.0,
                "how_good": 72.0,
                "temporary": False,
                "timestamp": "2026-01-03T00:00:00+00:00",
            },
            {
                "card_id": "strong",
                "marks_out_of_10": 9.0,
                "how_good": 97.0,
                "temporary": False,
                "timestamp": "2026-01-02T00:00:00+00:00",
            },
        ]

        recommendations = build_global_recommendations(
            [weak_card, strong_card],
            attempts,
            self.embedding_service,
            limit=10,
        )

        self.assertEqual([], recommendations)

    def test_next_only_silent_grades_real_answers(self) -> None:
        self.assertTrue(StudyTab._should_grade_answer_on_next("Photosynthesis converts light energy into chemical energy."))
        self.assertFalse(StudyTab._should_grade_answer_on_next("   "))
        self.assertFalse(StudyTab._should_grade_answer_on_next("....."))
        self.assertFalse(StudyTab._should_grade_answer_on_next("asdfghjkl"))


if __name__ == "__main__":
    unittest.main()
