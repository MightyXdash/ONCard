from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from studymate.constants import SIMILARITY_MIN_SCORE, WEAK_THRESHOLD
from studymate.services.embedding_service import EmbeddingService, cosine_similarity


@dataclass(frozen=True)
class RecommendedCard:
    card: dict
    score: float
    reason_anchor_card_id: str
    reason_similarity: float


@dataclass(frozen=True)
class CardPerformanceSummary:
    card: dict
    latest_how_good: float
    latest_marks: float
    rolling_how_good: float
    rolling_marks: float
    recent_rank: int


def build_global_recommendations(
    cards: list[dict],
    attempts: list[dict],
    embedding_service: EmbeddingService,
    *,
    limit: int = 10,
) -> list[RecommendedCard]:
    if not cards or not attempts or limit <= 0:
        return []

    card_lookup = {
        str(card.get("id", "")).strip(): card
        for card in cards
        if str(card.get("id", "")).strip()
    }
    graded_attempts = _valid_graded_attempts(attempts, card_lookup)
    if not graded_attempts:
        return []

    grouped: dict[str, list[dict]] = {}
    recent_rank_by_card: dict[str, int] = {}
    for rank, attempt in enumerate(graded_attempts):
        card_id = str(attempt.get("card_id", "")).strip()
        grouped.setdefault(card_id, []).append(attempt)
        recent_rank_by_card.setdefault(card_id, rank)

    summaries: dict[str, CardPerformanceSummary] = {}
    for card_id, card_attempts in grouped.items():
        card = card_lookup.get(card_id)
        if card is None:
            continue
        latest = card_attempts[0]
        rolling = card_attempts[:3]
        summaries[card_id] = CardPerformanceSummary(
            card=card,
            latest_how_good=float(latest.get("how_good", 0.0) or 0.0),
            latest_marks=float(latest.get("marks_out_of_10", 0.0) or 0.0),
            rolling_how_good=sum(float(item.get("how_good", 0.0) or 0.0) for item in rolling) / len(rolling),
            rolling_marks=sum(float(item.get("marks_out_of_10", 0.0) or 0.0) for item in rolling) / len(rolling),
            recent_rank=recent_rank_by_card.get(card_id, 9999),
        )

    weak_candidates = [
        summary
        for summary in summaries.values()
        if summary.latest_how_good < WEAK_THRESHOLD or summary.rolling_how_good < WEAK_THRESHOLD
    ]
    strong_candidates = [
        summary
        for summary in summaries.values()
        if summary.latest_how_good >= 95.0 and summary.latest_marks >= 8.0
    ]
    if not weak_candidates or not strong_candidates:
        return []

    strong_records = [
        (summary, embedding_service.get_card_record(summary.card))
        for summary in strong_candidates
    ]
    strong_records = [
        (summary, record)
        for summary, record in strong_records
        if record is not None
    ]
    if not strong_records:
        return []

    recommended: list[RecommendedCard] = []
    for weak in weak_candidates:
        weak_record = embedding_service.get_card_record(weak.card)
        if weak_record is None:
            continue
        best_anchor_id = ""
        best_similarity = 0.0
        strong_count = 0
        for strong_summary, strong_record in strong_records:
            strong_id = str(strong_summary.card.get("id", "")).strip()
            weak_id = str(weak.card.get("id", "")).strip()
            if not strong_id or strong_id == weak_id:
                continue
            similarity = cosine_similarity(weak_record.vector, strong_record.vector)
            if similarity < SIMILARITY_MIN_SCORE:
                continue
            strong_count += 1
            if similarity > best_similarity:
                best_similarity = similarity
                best_anchor_id = strong_id
        if strong_count <= 0 or not best_anchor_id:
            continue
        recommended.append(
            RecommendedCard(
                card=weak.card,
                score=_recommendation_score(weak, best_similarity, strong_count),
                reason_anchor_card_id=best_anchor_id,
                reason_similarity=best_similarity,
            )
        )

    recommended.sort(key=lambda item: item.score, reverse=True)
    return recommended[:limit]


def recommendation_candidate_cards(cards: list[dict], attempts: list[dict]) -> list[dict]:
    if not cards or not attempts:
        return []
    card_lookup = {
        str(card.get("id", "")).strip(): card
        for card in cards
        if str(card.get("id", "")).strip()
    }
    graded_attempts = _valid_graded_attempts(attempts, card_lookup)
    seen_ids: set[str] = set()
    candidates: list[dict] = []
    for attempt in graded_attempts:
        card_id = str(attempt.get("card_id", "")).strip()
        if not card_id or card_id in seen_ids:
            continue
        card = card_lookup.get(card_id)
        if card is None:
            continue
        seen_ids.add(card_id)
        candidates.append(card)
    return candidates


def _valid_graded_attempts(attempts: list[dict], card_lookup: dict[str, dict]) -> list[dict]:
    graded: list[tuple[datetime, dict]] = []
    for attempt in attempts:
        card_id = str(attempt.get("card_id", "")).strip()
        if not card_id or card_id not in card_lookup:
            continue
        if bool(attempt.get("temporary", False)):
            continue
        if attempt.get("marks_out_of_10") is None or attempt.get("how_good") is None:
            continue
        graded.append((_parse_timestamp(str(attempt.get("timestamp", ""))), attempt))
    graded.sort(key=lambda item: item[0], reverse=True)
    return [attempt for _timestamp, attempt in graded]


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _recommendation_score(summary: CardPerformanceSummary, best_similarity: float, strong_count: int) -> float:
    weak_baseline = min(summary.latest_how_good, summary.rolling_how_good)
    weakness_component = max(0.0, 100.0 - weak_baseline)
    marks_bonus = 8.0 if min(summary.latest_marks, summary.rolling_marks) <= 6.0 else 0.0
    similarity_component = best_similarity * 38.0
    anchor_bonus = min(strong_count, 4) * 4.5
    recency_bonus = max(0.0, 8.0 - min(float(summary.recent_rank), 8.0))
    recent_seen_penalty = 14.0 if summary.recent_rank == 0 else 7.0 if summary.recent_rank == 1 else 3.0 if summary.recent_rank == 2 else 0.0
    return weakness_component + marks_bonus + similarity_component + anchor_bonus + recency_bonus - recent_seen_penalty
