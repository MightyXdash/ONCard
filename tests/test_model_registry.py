from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.model_registry import has_any_supported_text_model, resolve_active_text_model_info


class ModelRegistryTests(unittest.TestCase):
    def test_active_text_model_info_uses_cloud_model_tag(self) -> None:
        info = resolve_active_text_model_info(
            {
                "use_selected_llm_for_text_features": True,
                "selected_text_llm_key": "gemma4_e2b",
                "ollama_cloud_enabled": True,
                "ollama_cloud_selected_model_tag": "gemini-3-flash-preview",
            }
        )

        self.assertTrue(info.cloud)
        self.assertEqual("gemini-3-flash-preview", info.model_tag)
        self.assertEqual("Gemini 3 Flash Preview (Cloud)", info.display_name)
        self.assertEqual("gemma4_e2b", info.preflight_key)

    def test_active_text_model_info_uses_local_model_when_cloud_is_off(self) -> None:
        info = resolve_active_text_model_info(
            {
                "use_selected_llm_for_text_features": True,
                "selected_text_llm_key": "gemma4_e4b",
                "ollama_cloud_enabled": False,
                "ollama_cloud_selected_model_tag": "gemini-3-flash-preview",
            }
        )

        self.assertFalse(info.cloud)
        self.assertEqual("gemma4:e4b", info.model_tag)
        self.assertEqual("Gemma4:e4b", info.display_name)
        self.assertEqual("gemma4_e4b", info.preflight_key)

    def test_legacy_text_keys_normalize_to_default(self) -> None:
        info = resolve_active_text_model_info(
            {
                "use_selected_llm_for_text_features": True,
                "selected_text_llm_key": "ministral_3_3b",
                "selected_ocr_llm_key": "ministral_3_14b",
                "ollama_cloud_enabled": True,
                "ollama_cloud_selected_model_tag": "ministral-3:3b",
            }
        )

        self.assertFalse(info.cloud)
        self.assertEqual("gemma4:e2b", info.model_tag)
        self.assertEqual("Gemma4:e2b", info.display_name)
        self.assertEqual("gemma4_e2b", info.preflight_key)

    def test_supported_text_model_detection_accepts_installed_keys_or_tags(self) -> None:
        self.assertTrue(has_any_supported_text_model({"gemma4_e4b": True}, set()))
        self.assertTrue(has_any_supported_text_model({}, {"qwen3.5:4b"}))
        self.assertFalse(has_any_supported_text_model({"ministral_3_3b": True}, {"ministral-3:3b"}))


if __name__ == "__main__":
    unittest.main()
