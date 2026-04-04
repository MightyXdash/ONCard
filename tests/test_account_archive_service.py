from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.account_archive_service import AccountArchiveService
from studymate.utils.paths import AppPaths


class AccountArchiveServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()
        self.archive = AccountArchiveService()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _seed_account_data(self, paths: AppPaths) -> None:
        paths.ensure()
        paths.config.mkdir(parents=True, exist_ok=True)
        paths.runtime.mkdir(parents=True, exist_ok=True)
        paths.subjects.mkdir(parents=True, exist_ok=True)
        paths.profile_config.write_text(
            json.dumps({"name": "Ava", "age": "16", "grade": "Grade 10", "hobbies": "Science"}),
            encoding="utf-8",
        )
        paths.setup_config.write_text(json.dumps({"onboarding_complete": True}), encoding="utf-8")
        paths.database_file.write_text("sqlite", encoding="utf-8")
        (paths.subjects / "science.json").write_text("[]", encoding="utf-8")
        (paths.runtime / "cache.json").write_text("{}", encoding="utf-8")

    def test_export_and_import_round_trip(self) -> None:
        source_paths = self.paths.for_account("a" * 34)
        self._seed_account_data(source_paths)
        account = {"id": "a" * 34, "name": "Ava"}
        export_name = self.archive.build_export_filename({"age": "16", "grade": "Grade 10"})
        self.assertRegex(export_name, r"^ONCARD_\d{8}_\d{6}_[a-z]{7}_A16_G10\.zip$")

        zip_path = self.root / export_name
        self.archive.export_account(account=account, paths=source_paths, destination_zip=zip_path)
        inspection = self.archive.inspect_archive(zip_path)
        self.assertTrue(inspection.valid)
        self.assertEqual("Ava", str(inspection.profile.get("name", "")))

        target_paths = self.paths.for_account("b" * 34)
        target_paths.ensure()
        self.archive.import_archive_into_account(archive_path=zip_path, paths=target_paths, overwrite=True)
        self.assertTrue(target_paths.database_file.exists())
        self.assertTrue((target_paths.runtime / "cache.json").exists())
        imported_profile = json.loads(target_paths.profile_config.read_text(encoding="utf-8"))
        self.assertEqual("Ava", imported_profile.get("name"))

    def test_rejects_non_account_zip_and_accepts_relaxed_filename(self) -> None:
        bad_zip = self.root / "random.zip"
        with zipfile.ZipFile(bad_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("foo.txt", "bar")
        inspection = self.archive.inspect_archive(bad_zip)
        self.assertFalse(inspection.valid)

        relaxed = self.root / "my_custom_backup_name.zip"
        with zipfile.ZipFile(relaxed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("config/profile.json", json.dumps({"name": "Mina"}))
            archive.writestr("config/setup.json", json.dumps({"onboarding_complete": True}))
            archive.writestr("oncard.sqlite", "sqlite")
        inspection = self.archive.inspect_archive(relaxed)
        self.assertTrue(inspection.valid)
        self.assertEqual("Mina", str(inspection.profile.get("name", "")))


if __name__ == "__main__":
    unittest.main()
