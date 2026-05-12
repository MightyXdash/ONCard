from __future__ import annotations

from hashlib import blake2b
import math
import re
from typing import Any

from studymate.services.data_store import DataStore
from studymate.services.settings_search_seed import SETTINGS_SEARCH_INDEX_VERSION, SETTINGS_SEARCH_SEED


SETTINGS_SEARCH_CACHE_KEY = "settings_search_index"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_VECTOR_DIMENSIONS = 192


def _tokenize(text: str) -> list[str]:
    normalized = str(text or "").lower()
    return [match.group(0) for match in _TOKEN_RE.finditer(normalized)]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _vectorize_text(text: str, *, dimensions: int = _VECTOR_DIMENSIONS) -> list[float]:
    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * dimensions

    features: list[tuple[str, float]] = [(token, 1.0) for token in tokens]
    features.extend((f"{left}_{right}", 1.35) for left, right in zip(tokens, tokens[1:]))

    vector = [0.0] * dimensions
    for token, weight in features:
        digest = blake2b(token.encode("utf-8"), digest_size=16).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += weight * sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        return [0.0] * dimensions
    return [value / norm for value in vector]


def _dedupe(values: list[str], *, limit: int = 5) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        normalized = " ".join(str(value or "").strip().split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
        if len(cleaned) >= limit:
            break
    return cleaned


def _build_queries(entry: dict[str, Any]) -> list[str]:
    feature = str(entry.get("feature_label", "")).strip()
    feature_lower = feature.lower()
    group_title = str(entry.get("group_title", "")).strip()
    tab_title = str(entry.get("tab_title", "")).strip()
    kind = str(entry.get("kind", "widget")).strip().lower()
    aliases = [str(alias).strip() for alias in list(entry.get("aliases", [])) if str(alias).strip()]

    if kind == "tab":
        queries = [
            f"where is the {tab_title.lower()} tab",
            f"open {tab_title.lower()} settings",
            f"{tab_title.lower()} settings page",
            f"how do I go to {tab_title.lower()} settings",
            f"{tab_title.lower()} settings tab",
            *aliases,
        ]
        return _dedupe(queries)

    if kind == "group":
        queries = [
            f"where is the {group_title.lower()} section",
            f"open {group_title.lower()} settings",
            f"{tab_title.lower()} {group_title.lower()} group",
            f"show me the {group_title.lower()} card",
            f"{group_title.lower()} settings section",
            *aliases,
        ]
        return _dedupe(queries)

    if kind == "action":
        queries = [
            f"where is {feature_lower}",
            f"how do I use {feature_lower}",
            f"{tab_title.lower()} {feature_lower}",
            f"{group_title.lower()} {feature_lower}",
            f"open {feature_lower}",
            *aliases,
        ]
        return _dedupe(queries)

    queries = [
        f"where is {feature_lower} in settings",
        f"what does {feature_lower} do",
        f"how do I change {feature_lower}",
        f"{tab_title.lower()} {feature_lower} setting",
        f"{group_title.lower()} {feature_lower}",
        *aliases,
    ]
    return _dedupe(queries)


def _build_search_text(entry: dict[str, Any], queries: list[str]) -> str:
    aliases = [str(alias).strip() for alias in list(entry.get("aliases", [])) if str(alias).strip()]
    parts = [
        f"Tab: {entry['tab_title']}",
        f"Group: {entry['group_title']}",
        f"Feature: {entry['feature_label']}",
        "Possible searches:",
        *[f"- {query}" for query in queries[:5]],
        *([f"Aliases: {', '.join(aliases)}"] if aliases else []),
        f"Description: {entry['description']}",
    ]
    return "\n".join(parts)


class SettingsSearchService:
    def __init__(self, datastore: DataStore) -> None:
        self.datastore = datastore

    def ensure_index(self) -> dict[str, Any]:
        cached = self.datastore.load_cache_entry(SETTINGS_SEARCH_CACHE_KEY) or {}
        cached_entries = cached.get("entries")
        if cached.get("version") == SETTINGS_SEARCH_INDEX_VERSION and isinstance(cached_entries, list) and cached_entries:
            return cached

        entries = [self._build_index_entry(index, seed_entry) for index, seed_entry in enumerate(SETTINGS_SEARCH_SEED)]
        payload = {
            "version": SETTINGS_SEARCH_INDEX_VERSION,
            "entries": entries,
            "updated_at": self.datastore.now_iso(),
        }
        self.datastore.put_cache_entry(SETTINGS_SEARCH_CACHE_KEY, payload)
        return payload

    def entries(self) -> list[dict[str, Any]]:
        payload = self.ensure_index()
        entries = payload.get("entries")
        return [dict(entry) for entry in entries] if isinstance(entries, list) else []

    def suggestions(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        normalized_query = " ".join(str(query or "").strip().split())
        if not normalized_query:
            return []

        query_lower = normalized_query.lower()
        query_terms = set(_tokenize(normalized_query))
        query_vector = _vectorize_text(normalized_query)

        scored: list[tuple[tuple[int, int, int, float], dict[str, Any]]] = []
        for entry in self.entries():
            searchable = str(entry.get("search_text", "")).lower()
            feature = str(entry.get("feature_label", "")).lower()
            group_title = str(entry.get("group_title", "")).lower()
            queries = [str(item).lower() for item in list(entry.get("queries", []))]
            phrase_match = int(
                query_lower in searchable
                or query_lower in feature
                or any(query_lower in item for item in queries)
            )
            prefix_match = int(
                feature.startswith(query_lower)
                or group_title.startswith(query_lower)
                or any(item.startswith(query_lower) for item in queries)
            )
            token_overlap = len(query_terms.intersection(set(_tokenize(searchable))))
            vector = [float(value) for value in list(entry.get("vector", []))]
            vector_score = _cosine_similarity(query_vector, vector)
            scored.append(((phrase_match, prefix_match, token_overlap, vector_score), entry))

        ranked = sorted(scored, key=lambda item: item[0], reverse=True)
        return [dict(entry) for _score, entry in ranked[: max(1, int(limit or 5))]]

    def top_match(self, query: str) -> dict[str, Any] | None:
        results = self.suggestions(query, limit=1)
        return dict(results[0]) if results else None

    def _build_index_entry(self, order_index: int, seed_entry: dict[str, Any]) -> dict[str, Any]:
        entry = dict(seed_entry)
        queries = _build_queries(entry)
        search_text = _build_search_text(entry, queries)
        return {
            "id": str(entry["id"]),
            "kind": str(entry["kind"]),
            "order_index": int(order_index),
            "tab_key": str(entry["tab_key"]),
            "tab_title": str(entry["tab_title"]),
            "group_title": str(entry["group_title"]),
            "feature_label": str(entry["feature_label"]),
            "target_key": str(entry["target_key"]),
            "description": str(entry["description"]),
            "queries": queries[:5],
            "search_text": search_text,
            "vector": _vectorize_text(search_text),
        }
