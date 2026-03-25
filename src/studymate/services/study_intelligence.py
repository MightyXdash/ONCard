from __future__ import annotations

from dataclasses import dataclass, field
import random

from studymate.constants import ROLLING_ATTEMPT_WINDOW, SIMILARITY_MIN_SCORE, WEAK_THRESHOLD
from studymate.services.embedding_service import EmbeddingService, fallback_cluster_key


@dataclass
class SessionCardEntry:
    card: dict
    grade_report: dict | None = None


@dataclass
class StudySessionState:
    scope_label: str
    cards: list[dict]
    card_lookup: dict[str, dict]
    unseen_ids: list[str]
    seed_ids: list[str]
    priority_ids: list[str] = field(default_factory=list)
    deferred_ids: list[str] = field(default_factory=list)
    shown_entries: list[SessionCardEntry] = field(default_factory=list)
    completed_ids: set[str] = field(default_factory=set)
    cluster_map: dict[str, str] = field(default_factory=dict)
    nna_enabled: bool = False
    last_weak_cluster_key: str = ""
    weak_cluster_streak: int = 0
    pending_reinforcement_cluster: str = ""

    def current_entry(self) -> SessionCardEntry | None:
        return self.shown_entries[-1] if self.shown_entries else None


def build_session_state(cards: list[dict], scope_label: str, rng: random.Random | None = None) -> StudySessionState:
    picker = rng or random.Random()
    shuffled = list(cards)
    picker.shuffle(shuffled)
    card_lookup = {str(card.get("id", "")): card for card in shuffled if str(card.get("id", "")).strip()}
    unseen_ids = list(card_lookup.keys())
    bootstrap_count = min(5, len(unseen_ids))
    seed_ids = unseen_ids[:bootstrap_count]
    return StudySessionState(
        scope_label=scope_label,
        cards=shuffled,
        card_lookup=card_lookup,
        unseen_ids=unseen_ids,
        seed_ids=seed_ids,
        nna_enabled=len(shuffled) > 5,
    )


def refresh_topic_clusters(state: StudySessionState, embedding_service: EmbeddingService | None) -> dict[str, str]:
    if embedding_service is None or not state.nna_enabled:
        state.cluster_map = {
            card_id: fallback_cluster_key(card)
            for card_id, card in state.card_lookup.items()
        }
        return state.cluster_map
    state.cluster_map = embedding_service.topic_clusters(state.cards)
    return state.cluster_map


def card_cluster_key(state: StudySessionState, card: dict) -> str:
    card_id = str(card.get("id", "")).strip()
    if card_id and card_id in state.cluster_map:
        return state.cluster_map[card_id]
    return fallback_cluster_key(card)


def next_card_for_session(
    state: StudySessionState,
    embedding_service: EmbeddingService | None = None,
) -> dict | None:
    if not state.card_lookup:
        return None

    if state.priority_ids:
        next_id = _pop_unique_existing_id(state.priority_ids, state)
        if next_id:
            return _select_card(state, next_id)

    if state.seed_ids:
        next_id = _pop_unique_existing_id(state.seed_ids, state)
        if next_id:
            return _select_card(state, next_id)

    candidates = [card_id for card_id in state.unseen_ids if card_id not in state.completed_ids]
    if candidates:
        ranked = sorted(
            candidates,
            key=lambda card_id: _candidate_score(state.card_lookup.get(card_id), state, embedding_service),
            reverse=True,
        )
        if ranked:
            return _select_card(state, ranked[0])

    if state.deferred_ids:
        next_id = _pop_unique_existing_id(state.deferred_ids, state)
        if next_id:
            return _select_card(state, next_id)

    return None


def register_grade_result(state: StudySessionState, card: dict, report: dict) -> dict:
    how_good = max(0.0, min(100.0, float(report.get("how_good", 0.0) or 0.0)))
    weak = how_good < WEAK_THRESHOLD
    cluster_key = card_cluster_key(state, card)

    if weak:
        if cluster_key == state.last_weak_cluster_key:
            state.weak_cluster_streak += 1
        else:
            state.last_weak_cluster_key = cluster_key
            state.weak_cluster_streak = 1
    else:
        state.weak_cluster_streak = 0
        state.last_weak_cluster_key = ""

    return {
        "weak": weak,
        "cluster_key": cluster_key,
        "trigger_reinforcement": weak
        and state.weak_cluster_streak >= 3
        and state.pending_reinforcement_cluster != cluster_key,
    }


def enqueue_similar_cards(
    state: StudySessionState,
    current_card: dict,
    embedding_service: EmbeddingService | None,
    max_immediate: int = 2,
) -> tuple[str, int]:
    cluster_key = card_cluster_key(state, current_card)
    if embedding_service is None:
        return cluster_key, 0

    shown_ids = {str(entry.card.get("id", "")) for entry in state.shown_entries}
    shown_ids.update(state.completed_ids)
    shown_ids.update(state.priority_ids)
    shown_ids.update(state.deferred_ids)
    similar = embedding_service.find_similar_cards(
        current_card,
        state.cards,
        max_results=12,
        exclude_ids=shown_ids,
        min_score=SIMILARITY_MIN_SCORE,
    )
    if not similar:
        return cluster_key, 0

    immediate_ids = [str(item.card.get("id", "")) for item in similar[:max_immediate] if str(item.card.get("id", ""))]
    deferred_ids = [str(item.card.get("id", "")) for item in similar[max_immediate:] if str(item.card.get("id", ""))]
    _push_unique_ids(state.priority_ids, immediate_ids)
    _push_unique_ids(state.deferred_ids, deferred_ids)
    return cluster_key, len(immediate_ids)


def queue_reinforcement_cards(state: StudySessionState, cards: list[dict], cluster_key: str) -> None:
    incoming_ids: list[str] = []
    for card in cards:
        card_id = str(card.get("id", "")).strip()
        if not card_id:
            continue
        state.cards.append(card)
        state.card_lookup[card_id] = card
        if card_id not in state.unseen_ids:
            state.unseen_ids.insert(0, card_id)
        incoming_ids.append(card_id)
    _push_unique_ids(state.priority_ids, incoming_ids, prepend=True)
    state.pending_reinforcement_cluster = cluster_key


def mark_card_completed(state: StudySessionState, card: dict) -> None:
    card_id = str(card.get("id", "")).strip()
    if card_id:
        state.completed_ids.add(card_id)


def session_snapshot(state: StudySessionState | None) -> dict:
    if state is None:
        return {"scope": "", "weak_areas": [], "strong_areas": []}

    weak: list[str] = []
    strong: list[str] = []
    for entry in state.shown_entries:
        if entry.grade_report is None:
            continue
        cluster = card_cluster_key(state, entry.card)
        how_good = float(entry.grade_report.get("how_good", 0.0) or 0.0)
        if how_good < WEAK_THRESHOLD:
            if cluster not in weak:
                weak.append(cluster)
        elif how_good >= 95 and cluster not in strong:
            strong.append(cluster)
    return {
        "scope": state.scope_label,
        "weak_areas": weak[:4],
        "strong_areas": strong[:4],
    }


def _select_card(state: StudySessionState, card_id: str) -> dict | None:
    if not card_id:
        return None
    state.unseen_ids = [item for item in state.unseen_ids if item != card_id]
    return state.card_lookup.get(card_id)


def _pop_unique_existing_id(queue: list[str], state: StudySessionState) -> str:
    while queue:
        candidate = queue.pop(0)
        if candidate in state.card_lookup and candidate not in state.completed_ids:
            return candidate
    return ""


def _push_unique_ids(target: list[str], incoming: list[str], prepend: bool = False) -> None:
    cleaned = [card_id for card_id in incoming if card_id and card_id not in target]
    if not cleaned:
        return
    if prepend:
        target[:0] = cleaned
    else:
        target.extend(cleaned)


def _candidate_score(card: dict | None, state: StudySessionState, embedding_service: EmbeddingService | None) -> float:
    if card is None:
        return float("-inf")

    score = 0.0
    cluster_key = card_cluster_key(state, card)
    if cluster_key == state.last_weak_cluster_key:
        score += 24.0

    recent_entries = [entry for entry in reversed(state.shown_entries[-ROLLING_ATTEMPT_WINDOW:]) if entry.grade_report]
    recent_cluster_keys = [card_cluster_key(state, entry.card) for entry in state.shown_entries[-2:]]
    if cluster_key in recent_cluster_keys:
        score -= 10.0

    for idx, entry in enumerate(recent_entries[:6], start=1):
        prior_cluster = card_cluster_key(state, entry.card)
        prior_how_good = float(entry.grade_report.get("how_good", 100.0) or 100.0)
        if prior_cluster == cluster_key:
            score += max(0.0, 100.0 - prior_how_good) * (1.0 / idx)
        elif prior_how_good < WEAK_THRESHOLD and card.get("subject") == entry.card.get("subject"):
            score += 7.0 / idx

    if embedding_service is not None and state.shown_entries:
        last_card = state.shown_entries[-1].card
        if card_cluster_key(state, last_card) != cluster_key:
            similar = embedding_service.find_similar_cards(last_card, [card], max_results=1)
            if similar and similar[0].score > 0.82:
                score -= 8.0
        weak_entries = [
            entry
            for entry in reversed(state.shown_entries[-4:])
            if entry.grade_report and float(entry.grade_report.get("how_good", 100.0) or 100.0) < WEAK_THRESHOLD
        ]
        for idx, entry in enumerate(weak_entries, start=1):
            similar = embedding_service.find_similar_cards(entry.card, [card], max_results=1)
            if similar:
                score += similar[0].score * (26.0 / idx)

    if str(card.get("id", "")) in state.seed_ids:
        score += 4.0
    return score
