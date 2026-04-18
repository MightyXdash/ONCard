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
from studymate.ui.study_tab import AiResponseOverlay, StudyTab
from studymate.utils.markdown import markdown_to_html
from studymate.utils.paths import AppPaths
from studymate.workers.ai_search_worker import _extract_image_search_terms_loose


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

    def test_ai_overlay_normalize_markdown_splits_inline_bullets(self) -> None:
        raw = (
            "Improving Your GamingSkills\n"
            "Key points\n"
            "- Practice consistently:Regular play is crucialfor skill development.- Analyze your gameplay: "
            "Identify areas forimprovement through recordings orself-reflection.- Focus on fundamentals: "
            "Master basic mechanicsand strategies.\n"
            "- Learn from others: Watch experienced playersand streamers.\n"
            "Quick explanation\n"
            "Gaming skill improvement requiresa multifaceted approach.\n"
            "Takeaway\n"
            "Dedication and focusedlearning are key tobecoming a better gamer."
        )

        normalized = AiResponseOverlay._normalize_markdown(raw)

        self.assertIn("# Improving Your Gaming Skills", normalized)
        self.assertIn("## Key Points", normalized)
        self.assertIn("## Quick Explanation", normalized)
        self.assertIn("## Takeaway", normalized)
        self.assertRegex(normalized, r"(?m)^- Practice consistently:")
        self.assertRegex(normalized, r"(?m)^- Analyze your gameplay:")
        self.assertRegex(normalized, r"(?m)^- Focus on fundamentals:")
        self.assertNotIn("development.- Analyze", normalized)

    def test_ai_overlay_normalize_markdown_converts_unicode_bullets(self) -> None:
        raw = (
            "Test title\n"
            "Key points\n"
            "\u2022 First point.- Second point.\n"
            "Takeaway\n"
            "\u2022 Keep practicing."
        )

        normalized = AiResponseOverlay._normalize_markdown(raw)

        self.assertIn("# Test title", normalized)
        self.assertRegex(normalized, r"(?m)^- First point\.$")
        self.assertRegex(normalized, r"(?m)^- Second point\.$")
        self.assertRegex(normalized, r"(?m)^- Keep practicing\.$")

    def test_ai_overlay_normalize_markdown_repairs_glued_heading_and_spacing(self) -> None:
        raw = (
            "George Washington\n"
            "Key Points\n"
            "\u2022 He served from1789 to 1797.- He led theContinental Army during theAmerican Revolutionary War."
            "## Quick Explanation\n"
            "\u2022 Washington was unanimouslyelected by the ElectoralCollege.\n"
            "Takeaway\n"
            "\u2022 Washington's presidency shaped thefoundation of American democracy."
        )

        normalized = AiResponseOverlay._normalize_markdown(raw)

        self.assertIn("# George Washington", normalized)
        self.assertIn("## Key Points", normalized)
        self.assertIn("## Quick Explanation", normalized)
        self.assertIn("## Takeaway", normalized)
        self.assertIn("- He served from 1789 to 1797.", normalized)
        self.assertIn("- He led the Continental Army during the American Revolutionary War.", normalized)
        self.assertNotIn("War.## Quick Explanation", normalized)
        self.assertIn("unanimously elected", normalized)
        self.assertIn("Electoral College", normalized)
        self.assertIn("the foundation of American democracy", normalized)

    def test_ai_overlay_normalize_markdown_canonicalizes_common_markers(self) -> None:
        raw = (
            "Plan\n"
            "---\n"
            "1) first item\n"
            "2- second item\n"
            "[x] done task\n"
            ">quoted text\n"
            "***\n"
        )

        normalized = AiResponseOverlay._normalize_markdown(raw)

        self.assertIn("# Plan", normalized)
        self.assertRegex(normalized, r"(?m)^1\. first item$")
        self.assertRegex(normalized, r"(?m)^2\. second item$")
        self.assertRegex(normalized, r"(?m)^- \[x\] done task$")
        self.assertRegex(normalized, r"(?m)^> quoted text$")
        self.assertIn("\n---\n", normalized)

    def test_ai_overlay_normalize_markdown_repairs_emphasized_section_labels(self) -> None:
        raw = (
            "Study guide\n"
            "**Summary:**This section keeps the explanation on the same line.\n"
            "**Takeaway**:Keep practicing the core steps."
        )

        normalized = AiResponseOverlay._normalize_markdown(raw)

        self.assertIn("# Study guide", normalized)
        self.assertIn("## Summary", normalized)
        self.assertIn("This section keeps the explanation on the same line.", normalized)
        self.assertIn("## Takeaway", normalized)
        self.assertRegex(normalized, r"(?m)^- Keep practicing the core steps\.$")
        self.assertNotIn("**Summary:**", normalized)
        self.assertNotIn("**Takeaway**:", normalized)

    def test_ai_overlay_normalize_markdown_splits_inline_numbered_steps(self) -> None:
        raw = "Next steps\n1)First thing 2)Second thing 3)Third thing"

        normalized = AiResponseOverlay._normalize_markdown(raw)

        self.assertIn("## Next Steps", normalized)
        self.assertRegex(normalized, r"(?m)^1\. First thing$")
        self.assertRegex(normalized, r"(?m)^2\. Second thing$")
        self.assertRegex(normalized, r"(?m)^3\. Third thing$")

    def test_ai_overlay_normalize_markdown_preserves_table_blocks(self) -> None:
        raw = "| Topic | Score |\n| --- | --- |\n| Math | 9/10 |"

        normalized = AiResponseOverlay._normalize_markdown(raw)

        self.assertFalse(normalized.startswith("# "))
        self.assertIn("| Topic | Score |", normalized)
        self.assertIn("| --- | --- |", normalized)
        self.assertIn("| Math | 9/10 |", normalized)

    def test_markdown_to_html_renders_headings_lists_and_rules(self) -> None:
        markdown = (
            "Intro line\n"
            "\n"
            "---\n"
            "\n"
            "# Step 1: Roots Soak Up Water + Minerals\n"
            "- First point\n"
            "- Second point with **bold** text\n"
        )

        rendered = markdown_to_html(markdown)

        self.assertIn("<hr />", rendered)
        self.assertIn("<h1>Step 1: Roots Soak Up Water + Minerals</h1>", rendered)
        self.assertIn("<ul><li>First point</li><li>Second point with <strong>bold</strong> text</li></ul>", rendered)
        self.assertNotIn("# Step 1", rendered)

    def test_markdown_to_html_renders_tables(self) -> None:
        markdown = "| Topic | Score |\n| --- | --- |\n| Math | 9/10 |"

        rendered = markdown_to_html(markdown)

        self.assertIn("<table>", rendered)
        self.assertIn("<th>Topic</th>", rendered)
        self.assertIn("<th>Score</th>", rendered)
        self.assertIn("<td>Math</td>", rendered)
        self.assertIn("<td>9/10</td>", rendered)

    def test_markdown_to_html_renders_heading_without_required_space(self) -> None:
        markdown = "##Step 1: Heading still renders"

        rendered = markdown_to_html(markdown)

        self.assertIn("<h2>Step 1: Heading still renders</h2>", rendered)
        self.assertNotIn("##Step 1", rendered)

    def test_markdown_to_html_ignores_zero_width_chars_before_heading(self) -> None:
        markdown = "\ufeff# Step 1: Clean heading"

        rendered = markdown_to_html(markdown)

        self.assertIn("<h1>Step 1: Clean heading</h1>", rendered)
        self.assertNotIn("# Step 1", rendered)

    def test_markdown_to_html_strips_nested_heading_marker_from_heading_text(self) -> None:
        markdown = "## # 1. Master the 2-Minute Rule"

        rendered = markdown_to_html(markdown)

        self.assertIn("<h2>1. Master the 2-Minute Rule</h2>", rendered)
        self.assertNotIn("># 1. Master the 2-Minute Rule<", rendered)

    def test_image_search_terms_parser_accepts_cloud_json_array(self) -> None:
        content = '["photosynthesis diagram", "chloroplast", "plant cell", "sunlight energy"]'

        terms = _extract_image_search_terms_loose(content, limit=4)

        self.assertEqual(["photosynthesis diagram", "chloroplast", "plant cell", "sunlight energy"], terms)

    def test_image_search_terms_parser_accepts_numbered_cloud_text(self) -> None:
        content = "1. quadratic formula\n2. algebra equation\n3. parabola graph\n4. vertex"

        terms = _extract_image_search_terms_loose(content, limit=4)

        self.assertEqual(["quadratic formula", "algebra equation", "parabola graph", "vertex"], terms)


if __name__ == "__main__":
    unittest.main()
