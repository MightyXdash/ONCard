from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.account_archive_service import AccountArchiveService
from studymate.services.account_transfer_service import AccountTransferHostService, AccountTransferPeerClient
from studymate.utils.paths import AppPaths


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class AccountTransferServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()
        self.archive = AccountArchiveService()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _seed_account_data(self, paths: AppPaths, *, profile_name: str) -> None:
        paths.ensure()
        paths.config.mkdir(parents=True, exist_ok=True)
        paths.runtime.mkdir(parents=True, exist_ok=True)
        paths.subjects.mkdir(parents=True, exist_ok=True)
        paths.profile_config.write_text(
            json.dumps({"name": profile_name, "profile_name": profile_name, "age": "16", "grade": "Grade 10"}),
            encoding="utf-8",
        )
        paths.setup_config.write_text(json.dumps({"onboarding_complete": True}), encoding="utf-8")
        paths.database_file.write_text("sqlite", encoding="utf-8")
        (paths.subjects / "science.json").write_text(json.dumps([{"id": "1", "question": "Q", "answer": "A"}]), encoding="utf-8")
        (paths.runtime / "cache.json").write_text("{}", encoding="utf-8")

    def test_discovery_request_confirm_download_and_import_round_trip(self) -> None:
        source_paths = self.paths.for_account("a" * 34)
        self._seed_account_data(source_paths, profile_name="Ava")
        account = {"id": "a" * 34, "name": "Ava"}
        discovery_port = _free_udp_port()

        def estimate_size() -> int:
            return sum(path.stat().st_size for path in source_paths.data.rglob("*") if path.is_file())

        def create_export() -> Path:
            target = self.root / "exports" / "host_account.zip"
            target.parent.mkdir(parents=True, exist_ok=True)
            return self.archive.export_account(account=account, paths=source_paths, destination_zip=target)

        service = AccountTransferHostService(
            host_name="Ava",
            estimate_size_bytes=estimate_size,
            create_export_archive=create_export,
            discovery_port=discovery_port,
        )
        service.start()
        self.addCleanup(service.stop)

        client = AccountTransferPeerClient(discovery_port=discovery_port, include_same_device=True)
        hosts = client.discover_hosts(timeout_seconds=1.0)
        self.assertTrue(hosts)
        host = next(item for item in hosts if item["host_name"] == "Ava")

        transfer = client.request_transfer(host, peer_name="Peer One")
        self.assertEqual("Ava", transfer["host_name"])
        self.assertEqual(3, len(transfer["confirmation_codes"]))
        self.assertTrue(all(len(str(code)) == 2 for code in transfer["confirmation_codes"]))
        self.assertGreater(int(transfer["estimated_size_bytes"]), 0)

        requests = service.list_requests()
        self.assertEqual(1, len(requests))
        self.assertEqual("Peer One", requests[0]["peer_name"])
        session_id = str(transfer["session_id"])
        service.approve_request(session_id)

        ready_status: dict | None = None
        deadline = time.time() + 5.0
        while time.time() < deadline:
            status = client.request_status(host, session_id=session_id, auth_token=str(transfer["auth_token"]))
            if status.get("status") == "ready":
                ready_status = status
                break
            time.sleep(0.1)
        self.assertIsNotNone(ready_status)
        self.assertGreater(int(ready_status["archive_size_bytes"]), 0)

        destination = self.root / "peer_download.zip"
        client.download_archive(
            host,
            session_id=session_id,
            auth_token=str(transfer["auth_token"]),
            destination=destination,
        )
        self.assertTrue(destination.exists())

        target_paths = self.paths.for_account("b" * 34)
        target_paths.ensure()
        self.archive.import_archive_into_account(archive_path=destination, paths=target_paths, overwrite=True)
        imported_profile = json.loads(target_paths.profile_config.read_text(encoding="utf-8"))
        self.assertEqual("Ava", imported_profile.get("name"))

    def test_rejected_request_is_reported_to_peer(self) -> None:
        source_paths = self.paths.for_account("c" * 34)
        self._seed_account_data(source_paths, profile_name="Mina")
        discovery_port = _free_udp_port()

        def estimate_size() -> int:
            return 128

        def create_export() -> Path:
            target = self.root / "exports" / "mina.zip"
            target.parent.mkdir(parents=True, exist_ok=True)
            return self.archive.export_account(account={"id": "c" * 34, "name": "Mina"}, paths=source_paths, destination_zip=target)

        service = AccountTransferHostService(
            host_name="Mina",
            estimate_size_bytes=estimate_size,
            create_export_archive=create_export,
            discovery_port=discovery_port,
        )
        service.start()
        self.addCleanup(service.stop)

        client = AccountTransferPeerClient(discovery_port=discovery_port, include_same_device=True)
        host = next(item for item in client.discover_hosts(timeout_seconds=1.0) if item["host_name"] == "Mina")
        transfer = client.request_transfer(host, peer_name="Peer Two")
        service.reject_request(str(transfer["session_id"]))

        status = client.request_status(host, session_id=str(transfer["session_id"]), auth_token=str(transfer["auth_token"]))
        self.assertEqual("rejected", status["status"])
        self.assertIn("rejected", str(status["error"]).lower())

    def test_default_discovery_hides_hosts_on_same_device(self) -> None:
        source_paths = self.paths.for_account("d" * 34)
        self._seed_account_data(source_paths, profile_name="Local Host")
        discovery_port = _free_udp_port()

        def create_export() -> Path:
            target = self.root / "exports" / "local.zip"
            target.parent.mkdir(parents=True, exist_ok=True)
            return self.archive.export_account(account={"id": "d" * 34, "name": "Local Host"}, paths=source_paths, destination_zip=target)

        service = AccountTransferHostService(
            host_name="Local Host",
            estimate_size_bytes=lambda: 1,
            create_export_archive=create_export,
            discovery_port=discovery_port,
        )
        service.start()
        self.addCleanup(service.stop)

        default_client = AccountTransferPeerClient(discovery_port=discovery_port)
        self.assertEqual([], default_client.discover_hosts(timeout_seconds=0.5))

        test_client = AccountTransferPeerClient(discovery_port=discovery_port, include_same_device=True)
        self.assertTrue(test_client.discover_hosts(timeout_seconds=0.5))


if __name__ == "__main__":
    unittest.main()
