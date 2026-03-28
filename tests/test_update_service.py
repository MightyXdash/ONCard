from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.update_content import load_packaged_update_content
from studymate.services.update_service import UpdateError, UpdateService
from studymate.utils.paths import AppPaths


class UpdateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()
        self.service = UpdateService(self.paths)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_patch_classification_only_when_last_number_changes(self) -> None:
        self.assertTrue(self.service.is_patch_update("1.0.0", "1.0.1"))
        self.assertFalse(self.service.is_patch_update("1.0.0", "1.1.0"))
        self.assertFalse(self.service.is_patch_update("1.0.0", "2.0.0"))
        self.assertFalse(self.service.is_patch_update("1.0.1", "1.0.1"))

    def test_extract_first_release_image_from_markdown(self) -> None:
        markdown = "\n".join(
            [
                "# Release",
                "![first](https://example.com/first.png)",
                "Some text",
                "![second](https://example.com/second.png)",
            ]
        )
        self.assertEqual("https://example.com/first.png", self.service.extract_first_release_image(markdown))

    def test_packaged_update_content_falls_back_from_legacy_manifest(self) -> None:
        updates = self.root / "assets" / "updates"
        common = updates / "common"
        version_dir = updates / "1.2.3"
        common.mkdir(parents=True, exist_ok=True)
        version_dir.mkdir(parents=True, exist_ok=True)

        (common / "update_prompt_banner_16x9.png").write_bytes(b"banner")
        (common / "whats_new_top_banner_16x9.png").write_bytes(b"banner1")
        (common / "whats_new_showcase_16x9.png").write_bytes(b"banner2")

        (common / "manifest.json").write_text(json.dumps({"prompt": {"banner": "update_prompt_banner_16x9.png"}}), encoding="utf-8")
        legacy_manifest = {
            "whats_new": {
                "title": "Welcome to 1.2.3",
                "description": "Line one",
                "points": ["Point A", "Point B"],
                "top_banner": "whats_new_top_banner_16x9.png",
                "showcase_banner": "whats_new_showcase_16x9.png",
            }
        }
        (version_dir / "manifest.json").write_text(json.dumps(legacy_manifest), encoding="utf-8")

        content = load_packaged_update_content(self.root / "assets", "1.2.3")
        self.assertEqual("Welcome to 1.2.3", content.update_name)
        self.assertEqual("Line one", content.text1)
        self.assertEqual("- Point A\n- Point B", content.text2)
        self.assertTrue(content.banner1.exists())
        self.assertIsNotNone(content.banner2)

    def test_load_ready_silent_patch_rejects_paths_outside_updates_dir(self) -> None:
        rogue_installer = self.root / "rogue.exe"
        rogue_installer.write_bytes(b"x")
        self.service.save_update_state(
            {
                "pending_silent_install": True,
                "latest_version": "1.0.1",
                "installer_path": str(rogue_installer),
            }
        )
        self.assertEqual({}, self.service.load_ready_silent_patch("1.0.0"))
        self.assertEqual({}, self.service.load_update_state())

    def test_launch_helper_raises_update_error_for_missing_script_parent(self) -> None:
        launcher = self.root / "missing-dir" / "run_update.ps1"
        with self.assertRaises(UpdateError):
            self.service.launch_helper(launcher)


if __name__ == "__main__":
    unittest.main()
