from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import socket
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


DISCOVERY_PROTOCOL = "oncard-account-transfer"
DISCOVERY_VERSION = 1
DEFAULT_DISCOVERY_PORT = 48231
REQUEST_EXPIRY_SECONDS = 900


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _format_http_error(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            message = str(parsed.get("error", "")).strip()
            if message:
                return message
    except Exception:
        pass
    return str(exc.reason or f"HTTP {exc.code}")


def _cleanup_temp_archive(path: Path | None) -> None:
    if path is None:
        return
    try:
        parent = path.parent
        if path.exists():
            path.unlink(missing_ok=True)
        if parent.exists() and parent.name.startswith("oncard_export_"):
            shutil.rmtree(parent, ignore_errors=True)
    except OSError:
        return


def _two_digit_code() -> str:
    return f"{secrets.randbelow(100):02d}"


@dataclass
class TransferSession:
    session_id: str
    auth_token: str
    peer_name: str
    confirmation_codes: list[str]
    estimated_size_bytes: int
    status: str = "pending"
    error: str = ""
    requested_at: float = field(default_factory=time.time)
    confirmed_at: float = 0.0
    archive_path: str = ""
    archive_size_bytes: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "peer_name": self.peer_name,
            "confirmation_codes": list(self.confirmation_codes),
            "estimated_size_bytes": int(self.estimated_size_bytes),
            "status": self.status,
            "error": self.error,
            "requested_at": float(self.requested_at),
            "confirmed_at": float(self.confirmed_at),
            "archive_size_bytes": int(self.archive_size_bytes),
        }


class _TransferHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, service: "AccountTransferHostService") -> None:
        super().__init__(server_address, handler_class)
        self.service = service


class AccountTransferHostService:
    def __init__(
        self,
        *,
        host_name: str,
        estimate_size_bytes: Callable[[], int],
        create_export_archive: Callable[[], Path],
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        request_expiry_seconds: int = REQUEST_EXPIRY_SECONDS,
    ) -> None:
        self.host_name = str(host_name or "").strip() or "ONCard Account"
        self._estimate_size_bytes = estimate_size_bytes
        self._create_export_archive = create_export_archive
        self.discovery_port = int(discovery_port)
        self.request_expiry_seconds = int(request_expiry_seconds)
        self._lock = threading.RLock()
        self._sessions: dict[str, TransferSession] = {}
        self._server: _TransferHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._udp_socket: socket.socket | None = None
        self._udp_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._instance_id = secrets.token_hex(8)
        self._device_name = socket.gethostname()

    @property
    def http_port(self) -> int:
        server = self._server
        if server is None:
            return 0
        return int(server.server_address[1])

    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            self._stopping.clear()
            try:
                self._server = _TransferHTTPServer(("0.0.0.0", 0), self._build_handler(), self)
                self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
                self._server_thread.start()

                self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._udp_socket.bind(("", self.discovery_port))
                self._udp_socket.settimeout(0.5)
                self._udp_thread = threading.Thread(target=self._run_udp_loop, daemon=True)
                self._udp_thread.start()
            except Exception:
                self._stopping.set()
                if self._udp_socket is not None:
                    try:
                        self._udp_socket.close()
                    except OSError:
                        pass
                    self._udp_socket = None
                if self._server is not None:
                    self._server.shutdown()
                    self._server.server_close()
                    self._server = None
                raise

    def stop(self) -> None:
        server: _TransferHTTPServer | None = None
        udp_socket: socket.socket | None = None
        with self._lock:
            self._stopping.set()
            server = self._server
            udp_socket = self._udp_socket
            self._server = None
            self._udp_socket = None
        if udp_socket is not None:
            try:
                udp_socket.close()
            except OSError:
                pass
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._server_thread is not None and self._server_thread.is_alive():
            self._server_thread.join(timeout=1.5)
        if self._udp_thread is not None and self._udp_thread.is_alive():
            self._udp_thread.join(timeout=1.5)
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            _cleanup_temp_archive(Path(session.archive_path) if session.archive_path else None)

    def list_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            self._cleanup_expired_locked()
            sessions = sorted(self._sessions.values(), key=lambda item: item.requested_at, reverse=True)
            return [session.snapshot() for session in sessions]

    def approve_request(self, session_id: str) -> None:
        target = str(session_id or "").strip()
        with self._lock:
            session = self._sessions.get(target)
            if session is None:
                raise ValueError("Transfer request was not found.")
            if session.status != "pending":
                raise ValueError("Only pending requests can be confirmed.")
            session.status = "preparing"
            session.confirmed_at = time.time()
        worker = threading.Thread(target=self._prepare_archive_worker, args=(target,), daemon=True)
        worker.start()

    def reject_request(self, session_id: str) -> None:
        target = str(session_id or "").strip()
        with self._lock:
            session = self._sessions.get(target)
            if session is None:
                raise ValueError("Transfer request was not found.")
            if session.status in {"completed", "expired"}:
                return
            session.status = "rejected"
            session.error = "The host rejected this transfer request."

    def _prepare_archive_worker(self, session_id: str) -> None:
        try:
            archive_path = Path(self._create_export_archive())
            archive_size = archive_path.stat().st_size if archive_path.exists() else 0
        except Exception as exc:
            with self._lock:
                session = self._sessions.get(session_id)
                if session is None:
                    return
                session.status = "error"
                session.error = str(exc)
            return

        should_cleanup = False
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                should_cleanup = True
            elif session.status != "preparing":
                should_cleanup = True
            else:
                session.archive_path = str(archive_path)
                session.archive_size_bytes = int(archive_size)
                session.status = "ready"
        if should_cleanup:
            _cleanup_temp_archive(archive_path)

    def _cleanup_expired_locked(self) -> None:
        now = time.time()
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.requested_at > self.request_expiry_seconds
        ]
        for session_id in expired_ids:
            session = self._sessions.pop(session_id, None)
            if session is None:
                continue
            if session.archive_path:
                _cleanup_temp_archive(Path(session.archive_path))

    def _create_session(self, peer_name: str) -> TransferSession:
        with self._lock:
            self._cleanup_expired_locked()
            session = TransferSession(
                session_id=secrets.token_hex(10),
                auth_token=secrets.token_hex(16),
                peer_name=str(peer_name or "").strip() or "Unknown device",
                confirmation_codes=[_two_digit_code(), _two_digit_code(), _two_digit_code()],
                estimated_size_bytes=max(0, int(self._estimate_size_bytes())),
            )
            self._sessions[session.session_id] = session
            return session

    def _status_for_peer(self, session_id: str, auth_token: str) -> dict[str, Any]:
        target = str(session_id or "").strip()
        token = str(auth_token or "").strip()
        with self._lock:
            self._cleanup_expired_locked()
            session = self._sessions.get(target)
            if session is None or session.auth_token != token:
                raise ValueError("Transfer request was not found.")
            return session.snapshot()

    def _download_path_for_peer(self, session_id: str, auth_token: str) -> Path:
        target = str(session_id or "").strip()
        token = str(auth_token or "").strip()
        with self._lock:
            self._cleanup_expired_locked()
            session = self._sessions.get(target)
            if session is None or session.auth_token != token:
                raise ValueError("Transfer request was not found.")
            if session.status != "ready":
                raise ValueError("The transfer data is not ready yet.")
            archive_path = Path(session.archive_path)
            if not archive_path.exists():
                session.status = "error"
                session.error = "The prepared account copy is no longer available."
                raise ValueError(session.error)
            return archive_path

    def _mark_download_complete(self, session_id: str, auth_token: str) -> None:
        target = str(session_id or "").strip()
        token = str(auth_token or "").strip()
        with self._lock:
            session = self._sessions.get(target)
            if session is None or session.auth_token != token:
                return
            if session.status == "ready":
                session.status = "completed"

    def _run_udp_loop(self) -> None:
        while not self._stopping.is_set():
            udp_socket = self._udp_socket
            if udp_socket is None:
                return
            try:
                payload, address = udp_socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            if str(message.get("protocol", "")).strip() != DISCOVERY_PROTOCOL:
                continue
            if str(message.get("type", "")).strip() != "discover":
                continue
            try:
                reply_port = int(message.get("reply_port", 0))
            except (TypeError, ValueError):
                continue
            if reply_port <= 0:
                continue
            response = {
                "protocol": DISCOVERY_PROTOCOL,
                "version": DISCOVERY_VERSION,
                "type": "host",
                "instance_id": self._instance_id,
                "device_name": self._device_name,
                "host_name": self.host_name,
                "http_port": self.http_port,
            }
            try:
                udp_socket.sendto(_json_bytes(response), (address[0], reply_port))
            except OSError:
                continue

    def _build_handler(self):
        service = self

        class TransferRequestHandler(BaseHTTPRequestHandler):
            server: _TransferHTTPServer

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                if parsed.path == "/request":
                    payload = self._read_json_body()
                    peer_name = ""
                    if isinstance(payload, dict):
                        peer_name = str(payload.get("peer_name", "")).strip()
                    session = service._create_session(peer_name)
                    response = session.snapshot()
                    response["auth_token"] = session.auth_token
                    response["host_name"] = service.host_name
                    self._write_json(200, response)
                    return
                if parsed.path.endswith("/complete"):
                    parts = [part for part in parsed.path.split("/") if part]
                    if len(parts) == 3 and parts[0] == "request" and parts[2] == "complete":
                        token = str(parse_qs(parsed.query).get("token", [""])[0]).strip()
                        service._mark_download_complete(parts[1], token)
                        self._write_json(200, {"ok": True})
                        return
                self._write_json(404, {"error": "Transfer endpoint was not found."})

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                parts = [part for part in parsed.path.split("/") if part]
                if len(parts) == 2 and parts[0] == "request":
                    token = str(parse_qs(parsed.query).get("token", [""])[0]).strip()
                    try:
                        payload = service._status_for_peer(parts[1], token)
                    except ValueError as exc:
                        self._write_json(404, {"error": str(exc)})
                        return
                    self._write_json(200, payload)
                    return
                if len(parts) == 2 and parts[0] == "download":
                    token = str(parse_qs(parsed.query).get("token", [""])[0]).strip()
                    try:
                        archive_path = service._download_path_for_peer(parts[1], token)
                    except ValueError as exc:
                        self._write_json(409, {"error": str(exc)})
                        return
                    try:
                        file_size = archive_path.stat().st_size
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(file_size))
                        self.send_header("Content-Disposition", f'attachment; filename="{archive_path.name}"')
                        self.end_headers()
                        with archive_path.open("rb") as handle:
                            shutil.copyfileobj(handle, self.wfile)
                    except OSError as exc:
                        self._write_json(500, {"error": f"Could not stream transfer archive: {exc}"})
                    return
                self._write_json(404, {"error": "Transfer endpoint was not found."})

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def _read_json_body(self) -> dict[str, Any]:
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    content_length = 0
                if content_length <= 0:
                    return {}
                try:
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return {}
                return payload if isinstance(payload, dict) else {}

            def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
                data = _json_bytes(payload)
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return TransferRequestHandler


class AccountTransferPeerClient:
    def __init__(
        self,
        *,
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        request_timeout_seconds: float = 4.0,
        include_same_device: bool = False,
    ) -> None:
        self.discovery_port = int(discovery_port)
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.include_same_device = bool(include_same_device)
        self._device_name = socket.gethostname()

    def discover_hosts(self, *, timeout_seconds: float = 1.2) -> list[dict[str, Any]]:
        hosts: dict[tuple[str, int], dict[str, Any]] = {}
        deadline = time.time() + max(0.2, float(timeout_seconds))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.2)
            sock.bind(("", 0))
            reply_port = int(sock.getsockname()[1])
            payload = _json_bytes(
                {
                    "protocol": DISCOVERY_PROTOCOL,
                    "version": DISCOVERY_VERSION,
                    "type": "discover",
                    "reply_port": reply_port,
                }
            )
            for target in ("255.255.255.255", "127.0.0.1"):
                try:
                    sock.sendto(payload, (target, self.discovery_port))
                except OSError:
                    continue
            while time.time() < deadline:
                try:
                    data, address = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    message = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(message, dict):
                    continue
                if str(message.get("protocol", "")).strip() != DISCOVERY_PROTOCOL:
                    continue
                if str(message.get("type", "")).strip() != "host":
                    continue
                try:
                    http_port = int(message.get("http_port", 0))
                except (TypeError, ValueError):
                    continue
                if http_port <= 0:
                    continue
                device_name = str(message.get("device_name", "")).strip()
                if not self.include_same_device and device_name and device_name == self._device_name:
                    continue
                key = (address[0], http_port)
                hosts[key] = {
                    "address": address[0],
                    "http_port": http_port,
                    "host_name": str(message.get("host_name", "")).strip() or "ONCard Account",
                    "instance_id": str(message.get("instance_id", "")).strip(),
                    "device_name": device_name,
                }
        return sorted(hosts.values(), key=lambda item: (str(item.get("host_name", "")).lower(), str(item.get("address", ""))))

    def request_transfer(self, host: dict[str, Any], *, peer_name: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            self._base_url(host) + "/request",
            payload={"peer_name": str(peer_name or "").strip()},
        )

    def request_status(self, host: dict[str, Any], *, session_id: str, auth_token: str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            self._base_url(host) + f"/request/{session_id}?token={auth_token}",
        )

    def mark_complete(self, host: dict[str, Any], *, session_id: str, auth_token: str) -> None:
        self._request_json(
            "POST",
            self._base_url(host) + f"/request/{session_id}/complete?token={auth_token}",
            payload={},
        )

    def download_archive(
        self,
        host: dict[str, Any],
        *,
        session_id: str,
        auth_token: str,
        destination: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        url = self._base_url(host) + f"/download/{session_id}?token={auth_token}"
        request = Request(url, method="GET")
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response, target.open("wb") as handle:
                try:
                    total = int(response.headers.get("Content-Length", "0"))
                except ValueError:
                    total = 0
                downloaded = 0
                if callable(progress_callback):
                    progress_callback(downloaded, total)
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if callable(progress_callback):
                        progress_callback(downloaded, total)
        except HTTPError as exc:
            target.unlink(missing_ok=True)
            raise RuntimeError(_format_http_error(exc)) from exc
        except URLError as exc:
            target.unlink(missing_ok=True)
            raise RuntimeError(str(exc.reason or "The transfer host is unreachable.")) from exc
        return target

    def _request_json(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = _json_bytes(payload or {}) if payload is not None else None
        request = Request(url, data=body, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(_format_http_error(exc)) from exc
        except URLError as exc:
            raise RuntimeError(str(exc.reason or "The transfer host is unreachable.")) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("The transfer host returned an invalid response.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("The transfer host returned an invalid response.")
        return parsed

    @staticmethod
    def _base_url(host: dict[str, Any]) -> str:
        address = str(host.get("address", "")).strip()
        try:
            http_port = int(host.get("http_port", 0))
        except (TypeError, ValueError):
            http_port = 0
        if not address or http_port <= 0:
            raise RuntimeError("The selected transfer host is missing its network address.")
        return f"http://{address}:{http_port}"
