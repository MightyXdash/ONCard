from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

from studymate.constants import EMBEDDING_MODEL, SIMILARITY_MIN_SCORE, SIMILARITY_TOP_K
from studymate.services.data_store import DataStore
from studymate.services.ollama_service import OllamaService


@dataclass(frozen=True)
class EmbeddingRecord:
    cache_key: str
    card_id: str
    model_tag: str
    content_hash: str
    vector: list[float]
    embedded_at: str


@dataclass(frozen=True)
class SimilarCard:
    card: dict
    score: float


class EmbeddingService:
    def __init__(self, datastore: DataStore, ollama: OllamaService, model_tag: str = EMBEDDING_MODEL) -> None:
        self.datastore = datastore
        self.ollama = ollama
        self.model_tag = model_tag

    @staticmethod
    def card_content_text(card: dict) -> str:
        hints = " | ".join(str(hint).strip() for hint in card.get("hints", []) if str(hint).strip())
        parts = [
            str(card.get("title", "")).strip(),
            str(card.get("question", "")).strip(),
            hints,
            str(card.get("answer", "")).strip(),
            str(card.get("subject", "")).strip(),
            str(card.get("category", "")).strip(),
            str(card.get("subtopic", "")).strip(),
        ]
        return "\n".join(part for part in parts if part)

    def content_hash_for_card(self, card: dict) -> str:
        text = self.card_content_text(card)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def cache_key_for_card(self, card: dict) -> str:
        card_id = str(card.get("id", "")).strip()
        return f"{card_id}:{self.content_hash_for_card(card)}:{self.model_tag}"

    def get_card_record(self, card: dict) -> EmbeddingRecord | None:
        cache = self.datastore.load_embedding_cache()
        record = cache.get(self.cache_key_for_card(card))
        if not isinstance(record, dict):
            return None
        vector = record.get("vector")
        if not isinstance(vector, list):
            return None
        return EmbeddingRecord(
            cache_key=self.cache_key_for_card(card),
            card_id=str(record.get("card_id", "")),
            model_tag=str(record.get("model_tag", self.model_tag)),
            content_hash=str(record.get("content_hash", "")),
            vector=[float(item) for item in vector],
            embedded_at=str(record.get("embedded_at", "")),
        )

    def is_card_cached(self, card: dict) -> bool:
        return self.get_card_record(card) is not None

    def ensure_card_embedding(self, card: dict) -> EmbeddingRecord:
        existing = self.get_card_record(card)
        if existing is not None:
            return existing
        vector = self.ollama.embed_text(self.model_tag, self.card_content_text(card))
        record = EmbeddingRecord(
            cache_key=self.cache_key_for_card(card),
            card_id=str(card.get("id", "")),
            model_tag=self.model_tag,
            content_hash=self.content_hash_for_card(card),
            vector=vector,
            embedded_at=self.datastore.now_iso(),
        )
        self.datastore.upsert_embedding_cache_record(
            record.cache_key,
            {
                "card_id": record.card_id,
                "model_tag": record.model_tag,
                "content_hash": record.content_hash,
                "vector": record.vector,
                "embedded_at": record.embedded_at,
            },
        )
        return record

    def missing_cards(self, cards: list[dict]) -> list[dict]:
        return [card for card in cards if not self.is_card_cached(card)]

    def ensure_cards_embedded(self, cards: list[dict]) -> list[EmbeddingRecord]:
        return [self.ensure_card_embedding(card) for card in cards]

    def find_similar_cards(
        self,
        target_card: dict,
        candidates: list[dict],
        max_results: int = 6,
        exclude_ids: set[str] | None = None,
        min_score: float = 0.0,
    ) -> list[SimilarCard]:
        target_record = self.get_card_record(target_card)
        if target_record is None:
            return []
        excluded = set(exclude_ids or set())
        target_id = str(target_card.get("id", ""))
        excluded.add(target_id)
        scored: list[SimilarCard] = []
        for candidate in candidates:
            candidate_id = str(candidate.get("id", ""))
            if candidate_id in excluded:
                continue
            record = self.get_card_record(candidate)
            if record is None:
                continue
            score = cosine_similarity(target_record.vector, record.vector)
            if math.isnan(score) or score < min_score:
                continue
            scored.append(SimilarCard(card=candidate, score=score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:max_results]

    def topic_clusters(
        self,
        cards: list[dict],
        *,
        max_neighbors: int = SIMILARITY_TOP_K,
        min_score: float = SIMILARITY_MIN_SCORE,
    ) -> dict[str, str]:
        records: dict[str, EmbeddingRecord] = {}
        for card in cards:
            card_id = str(card.get("id", "")).strip()
            if not card_id:
                continue
            record = self.get_card_record(card)
            if record is not None:
                records[card_id] = record

        parents: dict[str, str] = {card_id: card_id for card_id in records}

        def find(card_id: str) -> str:
            while parents[card_id] != card_id:
                parents[card_id] = parents[parents[card_id]]
                card_id = parents[card_id]
            return card_id

        def union(left: str, right: str) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        card_lookup = {str(card.get("id", "")): card for card in cards}
        embedded_cards = [card_lookup[card_id] for card_id in records]
        for card in embedded_cards:
            card_id = str(card.get("id", ""))
            neighbors = self.find_similar_cards(
                card,
                embedded_cards,
                max_results=max_neighbors,
                min_score=min_score,
            )
            for neighbor in neighbors:
                neighbor_id = str(neighbor.card.get("id", ""))
                if neighbor_id:
                    union(card_id, neighbor_id)

        cluster_map: dict[str, str] = {}
        for card in cards:
            card_id = str(card.get("id", "")).strip()
            if not card_id:
                continue
            if card_id in parents:
                cluster_map[card_id] = f"cluster:{find(card_id)}"
            else:
                cluster_map[card_id] = fallback_cluster_key(card)
        return cluster_map


def fallback_cluster_key(card: dict) -> str:
    return "::".join(
        [
            str(card.get("subject", "General")).strip() or "General",
            str(card.get("category", "All")).strip() or "All",
            str(card.get("subtopic", "All")).strip() or "All",
        ]
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return float("nan")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return float("nan")
    return dot / (left_norm * right_norm)
