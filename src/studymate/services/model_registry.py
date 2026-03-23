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
}


def recommended_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    return ["gemma3_4b"]


def required_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    return ["gemma3_4b"]


def total_selected_size_gb(model_keys: list[str]) -> float:
    return round(sum(MODELS[key].size_gb for key in model_keys if key in MODELS), 1)
