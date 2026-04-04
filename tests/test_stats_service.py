from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.stats_service import StatsService


class StatsServiceTests(unittest.TestCase):
    def test_missing_marks_are_counted_as_zero(self) -> None:
        fixed_now = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        service = StatsService(now=fixed_now)
        attempts = [
            {
                "timestamp": "2026-04-04T11:30:00+00:00",
                "card_id": "card-1",
                "subject": "Science",
                "marks_out_of_10": 8.0,
            },
            {
                "timestamp": "2026-04-04T11:50:00+00:00",
                "card_id": "card-2",
                "subject": "Science",
                "marks_out_of_10": None,
            },
        ]
        cards = [{"id": "card-1", "subject": "Science"}, {"id": "card-2", "subject": "Science"}]
        summary = service.summarize(range_key="hourly", attempts=attempts, cards=cards)
        self.assertEqual(2, summary["attempt_count"])
        self.assertAlmostEqual(4.0, summary["avg_marks"], places=4)

    def test_context_length_mapping(self) -> None:
        fixed_now = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        service = StatsService(now=fixed_now)
        empty_attempts: list[dict] = []
        empty_cards: list[dict] = []
        monthly = service.summarize(range_key="monthly", attempts=empty_attempts, cards=empty_cards)
        twoweeks = service.summarize(range_key="2weeks", attempts=empty_attempts, cards=empty_cards)
        weekly = service.summarize(range_key="weekly", attempts=empty_attempts, cards=empty_cards)
        self.assertEqual(6000, monthly["range"]["context_length"])
        self.assertEqual(5400, twoweeks["range"]["context_length"])
        self.assertEqual(4000, weekly["range"]["context_length"])

    def test_subject_scores_fallback_to_card_subject(self) -> None:
        fixed_now = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        service = StatsService(now=fixed_now)
        attempts = [
            {
                "timestamp": "2026-04-04T10:30:00+00:00",
                "card_id": "card-1",
                "marks_out_of_10": 9.0,
            },
            {
                "timestamp": "2026-04-04T10:40:00+00:00",
                "card_id": "card-2",
                "marks_out_of_10": 7.0,
            },
        ]
        cards = [
            {"id": "card-1", "subject": "Mathematics"},
            {"id": "card-2", "subject": "Science"},
        ]
        summary = service.summarize(range_key="daily", attempts=attempts, cards=cards)
        subjects = {item["subject"] for item in summary["subject_scores"]}
        self.assertIn("Mathematics", subjects)
        self.assertIn("Science", subjects)


if __name__ == "__main__":
    unittest.main()

