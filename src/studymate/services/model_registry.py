from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    key: str
    display_name: str
    primary_tag: str
    candidate_tags: list[str]
    size_label: str
    size_gb: float
    required: bool = True
    optional: bool = False
    min_ram_gb: int = 7
    supports_native_tools: bool = False


MODELS: dict[str, ModelSpec] = {
    "gemma3_4b": ModelSpec(
        key="gemma3_4b",
        display_name="Gemma3:4b",
        primary_tag="gemma3:4b",
        candidate_tags=["gemma3:4b"],
        size_label="3.8GB",
        size_gb=3.8,
        required=True,
    ),
    "ministral_3_3b": ModelSpec(
        key="ministral_3_3b",
        display_name="Ministral-3:3b",
        primary_tag="ministral-3:3b",
        candidate_tags=["ministral-3:3b"],
        size_label="3.0GB",
        size_gb=3.0,
        required=False,
        optional=True,
        min_ram_gb=6,
        supports_native_tools=True,
    ),
    "ministral_3_8b": ModelSpec(
        key="ministral_3_8b",
        display_name="Ministral-3:8b",
        primary_tag="ministral-3:8b",
        candidate_tags=["ministral-3:8b"],
        size_label="6.0GB",
        size_gb=6.0,
        required=False,
        optional=True,
        min_ram_gb=8,
        supports_native_tools=True,
    ),
    "ministral_3_14b": ModelSpec(
        key="ministral_3_14b",
        display_name="Ministral-3:14b",
        primary_tag="ministral-3:14b",
        candidate_tags=["ministral-3:14b"],
        size_label="9.1GB",
        size_gb=9.1,
        required=False,
        optional=True,
        min_ram_gb=16,
        supports_native_tools=True,
    ),
    "nomic_embed_text_v2_moe": ModelSpec(
        key="nomic_embed_text_v2_moe",
        display_name="Nomic Embed Text v2 MoE",
        primary_tag="nomic-embed-text-v2-moe",
        candidate_tags=["nomic-embed-text-v2-moe"],
        size_label="1.0GB",
        size_gb=1.0,
        required=True,
        optional=False,
        min_ram_gb=4,
    ),
}

DEFAULT_TEXT_LLM_KEY = "gemma3_4b"
NON_EMBEDDING_LLM_KEYS = [
    "gemma3_4b",
    "ministral_3_3b",
    "ministral_3_8b",
    "ministral_3_14b",
]


def recommended_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    return ["gemma3_4b", "nomic_embed_text_v2_moe"]


def required_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    return ["gemma3_4b"]


def total_selected_size_gb(model_keys: list[str]) -> float:
    return round(sum(MODELS[key].size_gb for key in model_keys if key in MODELS), 1)


def non_embedding_llm_keys() -> list[str]:
    return [key for key in NON_EMBEDDING_LLM_KEYS if key in MODELS]


def resolve_active_text_llm_key(ai_settings: dict | None = None) -> str:
    settings = ai_settings or {}
    if not bool(settings.get("use_selected_llm_for_text_features", False)):
        return DEFAULT_TEXT_LLM_KEY
    preferred = str(settings.get("selected_text_llm_key", DEFAULT_TEXT_LLM_KEY)).strip()
    if preferred in NON_EMBEDDING_LLM_KEYS and preferred in MODELS:
        return preferred
    return DEFAULT_TEXT_LLM_KEY


def resolve_active_text_llm_spec(ai_settings: dict | None = None) -> ModelSpec:
    return MODELS[resolve_active_text_llm_key(ai_settings)]
