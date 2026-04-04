from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.account_service import AccountService
from studymate.utils.paths import AppPaths


class AccountServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_migrates_legacy_single_account_into_accounts_folder(self) -> None:
        self.paths.config.mkdir(parents=True, exist_ok=True)
        (self.paths.config / "profile.json").write_text(json.dumps({"name": "Ava"}), encoding="utf-8")
        (self.paths.config / "setup.json").write_text(json.dumps({"onboarding_complete": True}), encoding="utf-8")
        self.paths.database_file.write_text("sqlite", encoding="utf-8")

        service = AccountService(self.paths)
        accounts = service.list_accounts()
        self.assertEqual(1, len(accounts))
        account_id = accounts[0]["id"]
        self.assertRegex(account_id, r"^[a-z]{34}$")
        self.assertEqual("Ava", accounts[0]["name"])
        account_paths = service.account_paths(account_id)
        self.assertTrue((account_paths.config / "profile.json").exists())
        self.assertTrue(account_paths.database_file.exists())

    def test_create_account_rejects_exact_duplicate_name(self) -> None:
        service = AccountService(self.paths)
        service.create_account(name="Alex", make_active=True)
        with self.assertRaises(ValueError):
            service.create_account(name="Alex", make_active=False)
        # Exact-match only means case variants are allowed.
        created = service.create_account(name="alex", make_active=False)
        self.assertEqual("alex", created["name"])

    def test_delete_uses_last_used_account_as_fallback(self) -> None:
        service = AccountService(self.paths)
        first = service.create_account(name="One", make_active=True)
        second = service.create_account(name="Two", make_active=False)
        third = service.create_account(name="Three", make_active=False)
        service.set_active_account(second["id"])
        service.set_active_account(third["id"])
        service.set_active_account(first["id"])

        next_id = service.delete_account(first["id"])
        self.assertIn(next_id, {second["id"], third["id"]})
        # third was the last used before switching back to first.
        self.assertEqual(third["id"], next_id)


if __name__ == "__main__":
    unittest.main()

