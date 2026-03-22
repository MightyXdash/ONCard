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
    "gemma3_270m": ModelSpec(
        key="gemma3_270m",
        display_name="Gemma3:270m",
        primary_tag="gemma3:270m",
        candidate_tags=["gemma3:270m"],
        size_label="200MB",
        size_gb=0.2,
        required=True,
    ),
    "gemma3_4b": ModelSpec(
        key="gemma3_4b",
        display_name="Gemma3:4b",
        primary_tag="gemma3:4b",
        candidate_tags=["gemma3:4b"],
        size_label="3.8GB",
        size_gb=3.8,
        required=True,
    ),
    "gemma3n_e2b": ModelSpec(
        key="gemma3n_e2b",
        display_name="gemma3n:e2b",
        primary_tag="gemma3n:e2b",
        candidate_tags=["gemma3n:e2b"],
        size_label="6GB",
        size_gb=6.0,
        required=True,
        min_ram_gb=15,
    ),
    "qwen35_2b": ModelSpec(
        key="qwen35_2b",
        display_name="qwen3.5:2b",
        primary_tag="qwen3.5:2b",
        candidate_tags=["qwen3.5:2b", "qwen3:1.7b", "qwen2.5:3b"],
        size_label="2GB",
        size_gb=2.0,
        required=True,
    ),
    "qwen35_4b": ModelSpec(
        key="qwen35_4b",
        display_name="qwen3.5:4b",
        primary_tag="qwen3.5:4b",
        candidate_tags=["qwen3.5:4b", "qwen3:4b"],
        size_label="4.5GB",
        size_gb=4.5,
        required=True,
        min_ram_gb=15,
    ),
    "qwen35_9b": ModelSpec(
        key="qwen35_9b",
        display_name="qwen3.5:9b",
        primary_tag="qwen3.5:9b",
        candidate_tags=["qwen3.5:9b", "qwen3:8b"],
        size_label="10GB",
        size_gb=10.0,
        required=False,
        optional=True,
        min_ram_gb=23,
    ),
    "deepseek_ocr": ModelSpec(
        key="deepseek_ocr",
        display_name="deepseek-ocr",
        primary_tag="deepseek-ocr:latest",
        candidate_tags=["deepseek-ocr:latest", "deepseek-ocr"],
        size_label="7GB",
        size_gb=7.0,
        required=False,
        optional=True,
        min_ram_gb=15,
    ),
}


def recommended_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    if ram_gb < 15:
        return ["gemma3_270m", "gemma3_4b", "qwen35_2b"]
    if ram_gb >= 23:
        return ["gemma3_270m", "gemma3_4b", "gemma3n_e2b", "qwen35_4b", "deepseek_ocr"]
    return ["gemma3_270m", "gemma3_4b", "gemma3n_e2b", "qwen35_4b"]


def required_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    if ram_gb < 15:
        return ["gemma3_270m", "gemma3_4b", "qwen35_2b"]
    return ["gemma3_270m", "gemma3_4b", "gemma3n_e2b", "qwen35_4b"]


def total_selected_size_gb(model_keys: list[str]) -> float:
    return round(sum(MODELS[key].size_gb for key in model_keys if key in MODELS), 1)
