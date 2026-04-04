from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


def _parse_timestamp(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _marks_or_zero(value: object) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return max(0.0, min(float(value), 10.0))
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class RangeConfig:
    key: str
    label: str
    duration: timedelta
    bucket_count: int
    context_length: int


RANGE_CONFIGS: dict[str, RangeConfig] = {
    "hourly": RangeConfig("hourly", "Hourly", timedelta(hours=1), 12, 4000),
    "daily": RangeConfig("daily", "Daily (3 days)", timedelta(days=3), 3, 4000),
    "weekly": RangeConfig("weekly", "Weekly", timedelta(days=7), 7, 4000),
    "2weeks": RangeConfig("2weeks", "2 Weeks", timedelta(days=14), 14, 5400),
    "monthly": RangeConfig("monthly", "Monthly", timedelta(days=30), 30, 6000),
}


class StatsService:
    def __init__(self, *, now: datetime | None = None) -> None:
        self._fixed_now = now

    def now(self) -> datetime:
        if self._fixed_now is not None:
            return self._fixed_now
        return datetime.now(timezone.utc)

    def summarize(self, *, range_key: str, attempts: list[dict], cards: list[dict]) -> dict[str, Any]:
        config = RANGE_CONFIGS.get(range_key, RANGE_CONFIGS["hourly"])
        now = self.now()
        start = now - config.duration

        card_subject_by_id = {
            str(card.get("id", "")).strip(): str(card.get("subject", "")).strip()
            for card in cards
            if str(card.get("id", "")).strip()
        }

        filtered: list[dict[str, Any]] = []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            ts = _parse_timestamp(str(attempt.get("timestamp", "")))
            if ts < start or ts > now:
                continue
            marks = _marks_or_zero(attempt.get("marks_out_of_10"))
            subject = str(attempt.get("subject", "")).strip()
            if not subject:
                subject = card_subject_by_id.get(str(attempt.get("card_id", "")).strip(), "General") or "General"
            filtered.append(
                {
                    "timestamp": ts,
                    "marks": marks,
                    "subject": subject,
                    "card_id": str(attempt.get("card_id", "")).strip(),
                    "graded": bool(attempt.get("graded", False)),
                    "temporary": bool(attempt.get("temporary", False)),
                }
            )

        filtered.sort(key=lambda item: item["timestamp"])
        line_points = self._build_line_points(filtered, start=start, end=now, bucket_count=config.bucket_count, label=config.label)
        subject_scores = self._subject_scores(filtered)

        avg_marks = sum(item["marks"] for item in filtered) / len(filtered) if filtered else 0.0
        return {
            "range": {
                "key": config.key,
                "label": config.label,
                "start_iso": start.isoformat(),
                "end_iso": now.isoformat(),
                "context_length": config.context_length,
            },
            "attempt_count": len(filtered),
            "avg_marks": round(avg_marks, 3),
            "line_points": line_points,
            "subject_scores": subject_scores,
            "summary_payload": self._summary_payload(config=config, filtered=filtered, avg_marks=avg_marks, subject_scores=subject_scores),
        }

    def _build_line_points(
        self,
        filtered: list[dict[str, Any]],
        *,
        start: datetime,
        end: datetime,
        bucket_count: int,
        label: str,
    ) -> list[dict[str, Any]]:
        bucket_count = max(1, int(bucket_count))
        total_seconds = max((end - start).total_seconds(), 1.0)
        bucket_seconds = total_seconds / bucket_count
        sums = [0.0 for _ in range(bucket_count)]
        counts = [0 for _ in range(bucket_count)]
        for item in filtered:
            ts: datetime = item["timestamp"]
            index = int((ts - start).total_seconds() / bucket_seconds)
            index = max(0, min(bucket_count - 1, index))
            sums[index] += float(item["marks"])
            counts[index] += 1

        points: list[dict[str, Any]] = []
        for idx in range(bucket_count):
            avg = sums[idx] / counts[idx] if counts[idx] > 0 else 0.0
            if label == "Hourly":
                point_label = f"{idx * 5:02d}m"
            elif label == "Daily (3 days)":
                point_label = f"D{idx + 1}"
            elif label == "Weekly":
                point_label = f"D{idx + 1}"
            elif label == "2 Weeks":
                point_label = f"D{idx + 1}"
            else:
                point_label = f"D{idx + 1}"
            points.append(
                {
                    "label": point_label,
                    "value": round(avg, 3),
                    "count": counts[idx],
                }
            )
        return points

    def _subject_scores(self, filtered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        for item in filtered:
            subject = str(item["subject"] or "General").strip() or "General"
            sums[subject] = sums.get(subject, 0.0) + float(item["marks"])
            counts[subject] = counts.get(subject, 0) + 1
        results = []
        for subject, total in sums.items():
            count = counts.get(subject, 1)
            results.append(
                {
                    "subject": subject,
                    "avg_marks": round(total / count, 3),
                    "attempts": count,
                }
            )
        results.sort(key=lambda item: (-float(item["avg_marks"]), item["subject"]))
        return results

    def _summary_payload(
        self,
        *,
        config: RangeConfig,
        filtered: list[dict[str, Any]],
        avg_marks: float,
        subject_scores: list[dict[str, Any]],
    ) -> dict[str, Any]:
        strongest = subject_scores[:3]
        weakest = sorted(subject_scores, key=lambda item: float(item["avg_marks"]))[:3]
        return {
            "range_key": config.key,
            "range_label": config.label,
            "attempt_count": len(filtered),
            "average_marks_out_of_10": round(avg_marks, 3),
            "subjects": subject_scores,
            "strongest_subjects": strongest,
            "weakest_subjects": weakest,
            "marks_trend_points": [
                {"timestamp": item["timestamp"].isoformat(), "marks": item["marks"], "subject": item["subject"]}
                for item in filtered[-32:]
            ],
        }
