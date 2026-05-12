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


@dataclass(frozen=True)
class ActiveTextModelInfo:
    model_tag: str
    display_name: str
    preflight_key: str
    cloud: bool = False


QN_SUMMARIZER_MODEL_KEY = "qn_summarizer_1"
QN_SUMMARIZER_MODEL_TAG = "QyrouNnet/summarizer:400m"
QN_SUMMARIZER_CONTEXT_LENGTH = 8000
QN_SUMMARIZER_MAX_WORDS = 6000
QN_SUMMARIZER_AUTO_SELECTED_SETTING = "qn_summarizer_auto_selected"


MODELS: dict[str, ModelSpec] = {
    "gemma4_e2b": ModelSpec(
        key="gemma4_e2b",
        display_name="Gemma4:e2b",
        primary_tag="gemma4:e2b",
        candidate_tags=["gemma4:e2b"],
        size_label="2.0GB",
        size_gb=2.0,
        required=False,
        optional=True,
        min_ram_gb=6,
    ),
    "gemma4_e4b": ModelSpec(
        key="gemma4_e4b",
        display_name="Gemma4:e4b",
        primary_tag="gemma4:e4b",
        candidate_tags=["gemma4:e4b"],
        size_label="4.0GB",
        size_gb=4.0,
        required=False,
        optional=True,
        min_ram_gb=7,
    ),
    "gemma4_26b": ModelSpec(
        key="gemma4_26b",
        display_name="Gemma4:26b",
        primary_tag="gemma4:26b",
        candidate_tags=["gemma4:26b"],
        size_label="16.0GB",
        size_gb=16.0,
        required=False,
        optional=True,
        min_ram_gb=24,
    ),
    "qwen3_5_2b": ModelSpec(
        key="qwen3_5_2b",
        display_name="Qwen3.5:2b",
        primary_tag="qwen3.5:2b",
        candidate_tags=["qwen3.5:2b"],
        size_label="1.8GB",
        size_gb=1.8,
        required=False,
        optional=True,
        min_ram_gb=6,
    ),
    "qwen3_5_4b": ModelSpec(
        key="qwen3_5_4b",
        display_name="Qwen3.5:4b",
        primary_tag="qwen3.5:4b",
        candidate_tags=["qwen3.5:4b"],
        size_label="3.0GB",
        size_gb=3.0,
        required=False,
        optional=True,
        min_ram_gb=7,
    ),
    "qwen3_5_9b": ModelSpec(
        key="qwen3_5_9b",
        display_name="Qwen3.5:9b",
        primary_tag="qwen3.5:9b",
        candidate_tags=["qwen3.5:9b"],
        size_label="6.0GB",
        size_gb=6.0,
        required=False,
        optional=True,
        min_ram_gb=12,
    ),
    "qwen3_5_27b": ModelSpec(
        key="qwen3_5_27b",
        display_name="Qwen3.5:27b",
        primary_tag="qwen3.5:27b",
        candidate_tags=["qwen3.5:27b"],
        size_label="16.0GB",
        size_gb=16.0,
        required=False,
        optional=True,
        min_ram_gb=24,
    ),
    "qwen3_5_35b": ModelSpec(
        key="qwen3_5_35b",
        display_name="Qwen3.5:35b",
        primary_tag="qwen3.5:35b",
        candidate_tags=["qwen3.5:35b"],
        size_label="20.0GB",
        size_gb=20.0,
        required=False,
        optional=True,
        min_ram_gb=32,
    ),
    "nomic_embed_text_v2_moe": ModelSpec(
        key="nomic_embed_text_v2_moe",
        display_name="Nomic Embed Text v2 MoE",
        primary_tag="nomic-embed-text-v2-moe",
        candidate_tags=["nomic-embed-text-v2-moe", "nomic-embed-text-v2-moe:latest"],
        size_label="1.0GB",
        size_gb=1.0,
        required=True,
        optional=False,
        min_ram_gb=4,
    ),
    QN_SUMMARIZER_MODEL_KEY: ModelSpec(
        key=QN_SUMMARIZER_MODEL_KEY,
        display_name="QN-Summarizer-1",
        primary_tag=QN_SUMMARIZER_MODEL_TAG,
        candidate_tags=[QN_SUMMARIZER_MODEL_TAG, "QyrouNnet/summarizer:latest"],
        size_label="400M",
        size_gb=0.4,
        required=False,
        optional=True,
        min_ram_gb=4,
    ),
}

DEFAULT_TEXT_LLM_KEY = "gemma4_e2b"
NON_EMBEDDING_LLM_KEYS = [
    "gemma4_e2b",
    "gemma4_e4b",
    "gemma4_26b",
    "qwen3_5_2b",
    "qwen3_5_4b",
    "qwen3_5_9b",
    "qwen3_5_27b",
    "qwen3_5_35b",
]
WIKI_SUMMARIZER_LLM_KEYS = [*NON_EMBEDDING_LLM_KEYS, QN_SUMMARIZER_MODEL_KEY]
OCR_LLM_KEYS = list(NON_EMBEDDING_LLM_KEYS)
FEATURE_MODEL_SETTING_KEYS = {
    "autofill_context_length": "autofill_model_key",
    "grading_context_length": "grading_model_key",
    "mcq_context_length": "mcq_model_key",
    "ask_ai_planner_context_length": "ask_ai_planner_model_key",
    "ask_ai_answer_context_length": "ask_ai_answer_model_key",
    "ask_ai_image_context_length": "ask_ai_image_model_key",
    "wiki_breakdown_context_length": "wiki_breakdown_model_key",
    "followup_context_length": "followup_model_key",
    "reinforcement_context_length": "reinforcement_model_key",
    "files_to_cards_ocr_context_length": "files_to_cards_ocr_model_key",
    "files_to_cards_paper_context_length": "files_to_cards_paper_model_key",
    "files_to_cards_cards_context_length": "files_to_cards_cards_model_key",
    "stats_context_length": "stats_model_key",
}
CLOUD_MODELS: dict[str, ModelSpec] = {
    "gemini_3_flash_preview_cloud": ModelSpec(
        key="gemini_3_flash_preview_cloud",
        display_name="Gemini 3 Flash Preview",
        primary_tag="gemini-3-flash-preview",
        candidate_tags=["gemini-3-flash-preview"],
        size_label="Cloud",
        size_gb=0.0,
        required=False,
        optional=True,
    ),
    "qwen3_5_cloud": ModelSpec(
        key="qwen3_5_cloud",
        display_name="Qwen3.5 Cloud",
        primary_tag="qwen3.5:cloud",
        candidate_tags=["qwen3.5:cloud"],
        size_label="Cloud",
        size_gb=0.0,
        required=False,
        optional=True,
    ),
    "gemma4_31b_cloud": ModelSpec(
        key="gemma4_31b_cloud",
        display_name="Gemma4:31b Cloud",
        primary_tag="gemma4:31b-cloud",
        candidate_tags=["gemma4:31b-cloud"],
        size_label="Cloud",
        size_gb=0.0,
        required=False,
        optional=True,
    ),
}
CLOUD_LLM_KEYS = list(CLOUD_MODELS.keys())
CLOUD_COMPATIBLE_LOCAL_LLM_KEYS = [key for key in NON_EMBEDDING_LLM_KEYS if key in MODELS]
LEGACY_TEXT_LLM_KEYS = {
    "ministral_3_3b": DEFAULT_TEXT_LLM_KEY,
    "ministral_3_8b": DEFAULT_TEXT_LLM_KEY,
    "ministral_3_14b": DEFAULT_TEXT_LLM_KEY,
}


def recommended_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    return [DEFAULT_TEXT_LLM_KEY, "nomic_embed_text_v2_moe"]


def required_models_for_ram(ram_gb: int) -> list[str]:
    if ram_gb < 7:
        return []
    return [DEFAULT_TEXT_LLM_KEY]


def total_selected_size_gb(model_keys: list[str]) -> float:
    return round(sum(MODELS[key].size_gb for key in model_keys if key in MODELS), 1)


def non_embedding_llm_keys() -> list[str]:
    return [key for key in NON_EMBEDDING_LLM_KEYS if key in MODELS]


def wiki_summarizer_llm_keys() -> list[str]:
    return [key for key in WIKI_SUMMARIZER_LLM_KEYS if key in MODELS]


def ocr_llm_keys() -> list[str]:
    return [key for key in OCR_LLM_KEYS if key in MODELS]


def cloud_llm_specs() -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    for key in CLOUD_COMPATIBLE_LOCAL_LLM_KEYS:
        spec = MODELS.get(key)
        if spec is not None:
            specs.append(spec)
    for key in CLOUD_LLM_KEYS:
        spec = CLOUD_MODELS.get(key)
        if spec is not None:
            specs.append(spec)
    return specs


def cloud_llm_spec_for_model_tag(model_tag: str) -> ModelSpec | None:
    tag = str(model_tag or "").strip()
    if not tag:
        return None
    for spec in cloud_llm_specs():
        if tag == spec.primary_tag or tag in spec.candidate_tags:
            return spec
    return None


def cloud_label_for_model_tag(model_tag: str) -> str:
    tag = str(model_tag or "").strip()
    spec = cloud_llm_spec_for_model_tag(tag)
    if spec is not None:
        return f"{spec.display_name} (Cloud)"
    return f"{tag} (Cloud)" if tag else "Cloud model"


def smallest_supported_ocr_llm_key(installed_keys: list[str] | set[str] | tuple[str, ...] | None = None) -> str:
    supported = ocr_llm_keys()
    if installed_keys is not None:
        installed = {str(key) for key in installed_keys}
        supported = [key for key in supported if key in installed]
    if not supported:
        return DEFAULT_TEXT_LLM_KEY
    return min(supported, key=lambda key: MODELS[key].size_gb)


def feature_model_setting_key(feature_key: str) -> str:
    return str(FEATURE_MODEL_SETTING_KEYS.get(str(feature_key or "").strip(), "")).strip()


def normalize_text_llm_key(model_key: str, fallback: str | None = None) -> str:
    key = str(model_key or "").strip()
    if key in LEGACY_TEXT_LLM_KEYS:
        key = LEGACY_TEXT_LLM_KEYS[key]
    if key in NON_EMBEDDING_LLM_KEYS and key in MODELS:
        return key
    fallback_key = str(fallback or DEFAULT_TEXT_LLM_KEY).strip()
    if fallback_key in NON_EMBEDDING_LLM_KEYS and fallback_key in MODELS:
        return fallback_key
    return DEFAULT_TEXT_LLM_KEY


def normalize_cloud_model_tag(model_tag: str) -> str:
    tag = str(model_tag or "").strip()
    if not tag:
        return ""
    return tag if cloud_llm_spec_for_model_tag(tag) is not None else ""


def normalize_ai_settings(ai_settings: dict | None = None) -> dict:
    settings = dict(ai_settings or {})
    settings["selected_text_llm_key"] = normalize_text_llm_key(settings.get("selected_text_llm_key", DEFAULT_TEXT_LLM_KEY))
    settings["selected_ocr_llm_key"] = normalize_text_llm_key(settings.get("selected_ocr_llm_key", DEFAULT_TEXT_LLM_KEY))
    settings["ollama_cloud_selected_model_tag"] = normalize_cloud_model_tag(settings.get("ollama_cloud_selected_model_tag", ""))
    return settings


def has_any_supported_text_model(
    installed_models: dict | None = None,
    installed_tags: set[str] | list[str] | tuple[str, ...] | None = None,
) -> bool:
    models = dict(installed_models or {})
    tags = {str(tag).strip() for tag in (installed_tags or []) if str(tag).strip()}
    for key in non_embedding_llm_keys():
        spec = MODELS.get(key)
        if spec is None:
            continue
        if bool(models.get(key, False)):
            return True
        if any(tag in tags for tag in [spec.primary_tag, *spec.candidate_tags]):
            return True
    return False


def resolve_active_text_llm_key(ai_settings: dict | None = None) -> str:
    settings = normalize_ai_settings(ai_settings)
    if not bool(settings.get("use_selected_llm_for_text_features", False)):
        return DEFAULT_TEXT_LLM_KEY
    return normalize_text_llm_key(settings.get("selected_text_llm_key", DEFAULT_TEXT_LLM_KEY))


def resolve_active_text_llm_spec(ai_settings: dict | None = None) -> ModelSpec:
    return MODELS[resolve_active_text_llm_key(ai_settings)]


def resolve_feature_text_llm_key(ai_settings: dict | None = None, feature_key: str = "") -> str:
    settings = ai_settings or {}
    setting_key = feature_model_setting_key(feature_key)
    explicit_key = str(settings.get(setting_key, "")).strip() if setting_key else ""
    allowed_keys = WIKI_SUMMARIZER_LLM_KEYS if str(feature_key) == "wiki_breakdown_context_length" else NON_EMBEDDING_LLM_KEYS
    if explicit_key in allowed_keys and explicit_key in MODELS:
        return explicit_key
    return resolve_active_text_llm_key(settings)


def resolve_feature_text_llm_spec(ai_settings: dict | None = None, feature_key: str = "") -> ModelSpec:
    return MODELS[resolve_feature_text_llm_key(ai_settings, feature_key)]


def resolve_active_ocr_llm_key(
    ai_settings: dict | None = None,
    installed_keys: list[str] | set[str] | tuple[str, ...] | None = None,
) -> str:
    settings = normalize_ai_settings(ai_settings)
    preferred = str(settings.get("selected_ocr_llm_key", "")).strip()
    available = set(ocr_llm_keys() if installed_keys is None else [str(key) for key in installed_keys])
    if preferred in available and preferred in MODELS:
        return preferred
    return smallest_supported_ocr_llm_key(installed_keys)


def resolve_active_ocr_llm_spec(
    ai_settings: dict | None = None,
    installed_keys: list[str] | set[str] | tuple[str, ...] | None = None,
) -> ModelSpec:
    return MODELS[resolve_active_ocr_llm_key(ai_settings, installed_keys)]


def ollama_cloud_enabled(ai_settings: dict | None = None) -> bool:
    settings = ai_settings or {}
    return bool(settings.get("ollama_cloud_enabled", False))


def resolve_active_text_model_tag(ai_settings: dict | None = None) -> str:
    settings = normalize_ai_settings(ai_settings)
    cloud_tag = str(settings.get("ollama_cloud_selected_model_tag", "")).strip()
    if ollama_cloud_enabled(settings) and cloud_tag:
        return cloud_tag
    return resolve_active_text_llm_spec(settings).primary_tag


def resolve_active_text_model_info(ai_settings: dict | None = None) -> ActiveTextModelInfo:
    settings = normalize_ai_settings(ai_settings)
    cloud_tag = str(settings.get("ollama_cloud_selected_model_tag", "")).strip()
    if ollama_cloud_enabled(settings) and cloud_tag:
        mapped_key = text_llm_key_for_model_tag(cloud_tag)
        return ActiveTextModelInfo(
            model_tag=cloud_tag,
            display_name=cloud_label_for_model_tag(cloud_tag),
            preflight_key=mapped_key or resolve_active_text_llm_key(settings),
            cloud=True,
        )
    spec = resolve_active_text_llm_spec(settings)
    return ActiveTextModelInfo(
        model_tag=spec.primary_tag,
        display_name=spec.display_name,
        preflight_key=spec.key,
        cloud=False,
    )


def resolve_feature_text_model_info(ai_settings: dict | None = None, feature_key: str = "") -> ActiveTextModelInfo:
    settings = ai_settings or {}
    setting_key = feature_model_setting_key(feature_key)
    explicit_key = str(settings.get(setting_key, "")).strip() if setting_key else ""
    allowed_keys = WIKI_SUMMARIZER_LLM_KEYS if str(feature_key) == "wiki_breakdown_context_length" else NON_EMBEDDING_LLM_KEYS
    if explicit_key in allowed_keys and explicit_key in MODELS:
        spec = MODELS[explicit_key]
        return ActiveTextModelInfo(
            model_tag=spec.primary_tag,
            display_name=spec.display_name,
            preflight_key=spec.key,
            cloud=False,
        )
    return resolve_active_text_model_info(settings)


def resolve_active_ocr_model_tag(
    ai_settings: dict | None = None,
    installed_keys: list[str] | set[str] | tuple[str, ...] | None = None,
) -> str:
    return resolve_active_ocr_llm_spec(ai_settings, installed_keys).primary_tag


def resolve_feature_text_model_tag(ai_settings: dict | None = None, feature_key: str = "") -> str:
    return resolve_feature_text_model_info(ai_settings, feature_key).model_tag


def text_llm_key_for_model_tag(model_tag: str) -> str:
    tag = str(model_tag or "").strip()
    if not tag:
        return ""
    for key in NON_EMBEDDING_LLM_KEYS:
        spec = MODELS.get(key)
        if spec is None:
            continue
        if tag == spec.primary_tag or tag in spec.candidate_tags:
            return key
    return ""
