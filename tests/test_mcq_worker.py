from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.workers.mcq_worker import (
    build_mcq_payload,
    cached_mcq_payload,
    generate_mcq_payload,
    mcq_cache_key,
    normalize_mcq_answers,
    save_mcq_payload,
)
from studymate.workers.autofill_worker import generate_card_payload
from studymate.services.data_store import DataStore
from studymate.utils.paths import AppPaths


class FakeOllama:
    def structured_chat(self, **_kwargs):
        return {
            "title": "Plant Energy",
            "subject": "Science",
            "category": "Biology",
            "subtopic": "Plants",
            "hints": ["Think leaves", "Think sunlight", "Think glucose"],
            "search_terms": ["plant", "energy", "sunlight", "glucose", "photosynthesis"],
            "mcq_answers": ["Photosynthesis", "Respiration", "Transpiration", "Fermentation"],
            "natural_difficulty": 4,
            "response_to_user": "Done!",
        }


class FakePlaceholderAutofillOllama:
    def structured_chat(self, **_kwargs):
        return {
            "title": "Generic Placeholder",
            "subject": "Science",
            "category": "Biology",
            "subtopic": "Plants",
            "hints": ["Think about the term.", "Check the context.", "Compare close ideas."],
            "search_terms": ["generic", "placeholder", "science", "biology", "plants"],
            "mcq_answers": ["Core concept", "Similar concept", "Related detail", "Nearby topic"],
            "natural_difficulty": 4,
            "response_to_user": "Done!",
        }


class FakeRetryMcqOllama:
    def __init__(self) -> None:
        self.calls = 0

    def structured_chat(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "answers": [
                    "A quick mental shortcut",
                    "A rule from medieval times",
                    "A coding algorithm for AI",
                    "A strict mathematical formula",
                ]
            }
        return {"answers": ["Availability heuristic", "Representativeness heuristic", "Anchoring heuristic", "Recognition heuristic"]}


class MCQWorkerUtilityTests(unittest.TestCase):
    def test_normalize_mcq_answers_accepts_valid_similar_choices(self) -> None:
        answers = normalize_mcq_answers(["Mitochondria", "Ribosomes", "Lysosomes", "Centrioles"])
        self.assertEqual(["Mitochondria", "Ribosomes", "Lysosomes", "Centrioles"], answers)

    def test_normalize_mcq_answers_accepts_detailed_choices_up_to_backend_limit(self) -> None:
        answers = normalize_mcq_answers(
            [
                "A fast mental shortcut based on limited evidence",
                "A quick judgment pattern based on recent examples",
                "A simple decision rule based on familiar cases",
                "A rough problem solving cue based on experience",
            ]
        )
        self.assertEqual(4, len(answers))

    def test_normalize_mcq_answers_rejects_bad_payloads(self) -> None:
        bad_payloads = [
            ["Only one"],
            ["A", "A", "B", "C"],
            ["", "A", "B", "C"],
            ["this answer is way over forty words " * 5, "A", "B", "C"],
            ["All of the above", "A", "B", "C"],
            ["Core concept", "Similar concept", "Related detail", "Nearby topic"],
            ["A quick mental shortcut", "A rule from medieval times", "A coding algorithm for AI", "A strict mathematical formula"],
            ["Short", "Medium", "Also medium", "This is a wildly disproportionate answer that goes on and on and on and on and on and on"],
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    normalize_mcq_answers(payload)

    def test_build_payload_shuffles_and_preserves_correct_marker(self) -> None:
        card = {"id": "card-1", "question": "Which organelle makes ATP?"}
        payload = build_mcq_payload(card, ["Mitochondria", "Ribosomes", "Lysosomes", "Centrioles"], "gemma3:4b")
        self.assertEqual(4, len(payload["choices"]))
        self.assertEqual("Mitochondria", payload["correct_answer"])
        self.assertEqual("Mitochondria", payload["choices"][payload["correct_index"]])

    def test_generate_mcq_payload_retries_rejected_easy_choices(self) -> None:
        ollama = FakeRetryMcqOllama()
        payload = generate_mcq_payload(
            card={"id": "card-1", "question": "What is the availability heuristic?"},
            ollama=ollama,
            model="gemma3:4b",
        )
        self.assertEqual(2, ollama.calls)
        self.assertEqual("Availability heuristic", payload["correct_answer"])

    def test_cache_key_changes_with_question_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            paths = AppPaths(Path(tempdir))
            paths.ensure()
            store = DataStore(paths)
            card = {"id": "card-1", "question": "Which organelle makes ATP?"}
            changed = {"id": "card-1", "question": "Which organelle stores DNA?"}
            self.assertNotEqual(mcq_cache_key(card, "gemma3:4b"), mcq_cache_key(changed, "gemma3:4b"))

            payload = build_mcq_payload(card, ["Mitochondria", "Ribosomes", "Lysosomes", "Centrioles"], "gemma3:4b")
            save_mcq_payload(store, card, payload)
            cached = cached_mcq_payload(store, card, "gemma3:4b")
            self.assertIsNotNone(cached)
            self.assertEqual(payload["correct_answer"], cached["correct_answer"])
            store.close()

    def test_autofill_uses_correct_mcq_choice_as_short_flashcard_answer(self) -> None:
        payload = generate_card_payload(
            question="What process lets plants make food?",
            ollama=FakeOllama(),
            model="gemma3:4b",
        )
        self.assertEqual("Photosynthesis", payload["answer"])
        self.assertEqual(["Photosynthesis", "Respiration", "Transpiration", "Fermentation"], payload["mcq_answers"])

    def test_autofill_does_not_cache_placeholder_mcq_answers(self) -> None:
        payload = generate_card_payload(
            question="What process lets plants make food?",
            ollama=FakePlaceholderAutofillOllama(),
            model="gemma3:4b",
        )
        self.assertEqual("", payload["answer"])
        self.assertEqual([], payload["mcq_answers"])

    def test_mcq_attempts_share_normal_attempt_pool_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            paths = AppPaths(Path(tempdir))
            paths.ensure()
            store = DataStore(paths)
            store.save_attempt(
                {
                    "timestamp": "2026-03-01T00:00:00+00:00",
                    "session_id": "session-1",
                    "card_id": "card-1",
                    "marks_out_of_10": 10.0,
                    "how_good": 120.0,
                    "state": "correct",
                    "mcq": True,
                    "selected_answer": "Photosynthesis",
                    "correct_answer": "Photosynthesis",
                    "temporary": False,
                }
            )
            attempts = store.load_attempts()
            self.assertEqual(1, len(attempts))
            self.assertTrue(attempts[0]["mcq"])
            self.assertEqual(10.0, attempts[0]["marks_out_of_10"])
            self.assertEqual(120.0, attempts[0]["how_good"])
            store.close()


if __name__ == "__main__":
    unittest.main()
