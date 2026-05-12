from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

from packaging.version import InvalidVersion, Version
import requests

from studymate.services.update_notes import parse_update_notes
from studymate.utils.paths import AppPaths
from studymate.version import GITHUB_RELEASES_API, INSTALLER_NAME_PREFIX, is_beta_version, normalize_release_version, pep440_version


class UpdateError(RuntimeError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag_name: str
    html_url: str
    asset_name: str
    asset_url: str
    body: str
    prompt_image_url: str
    update_kind: str


class UpdateService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    @staticmethod
    def normalize_version(raw: str) -> str:
        return normalize_release_version(raw)

    def get_latest_release(self, current_version: str) -> ReleaseInfo | None:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ONCard-Updater"}
        try:
            response = requests.get(GITHUB_RELEASES_API, headers=headers, timeout=8)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise UpdateError(f"Update check failed: {exc}") from exc
        except ValueError as exc:
            raise UpdateError(f"Update check failed: invalid release response: {exc}") from exc

        if isinstance(payload, dict):
            releases = [payload]
        elif isinstance(payload, list):
            releases = [item for item in payload if isinstance(item, dict)]
        else:
            return None

        best_release: ReleaseInfo | None = None
        for item in releases:
            if bool(item.get("draft", False)):
                continue
            tag_name = str(item.get("tag_name", "")).strip()
            if not tag_name:
                continue
            latest_version = self.normalize_version(tag_name)
            if not self.is_newer_version(current_version, latest_version):
                continue
            asset = self._pick_installer_asset(item.get("assets", []))
            if asset is None:
                continue
            body = str(item.get("body", "") or "")
            candidate = ReleaseInfo(
                version=latest_version,
                tag_name=tag_name,
                html_url=str(item.get("html_url", "")),
                asset_name=str(asset.get("name", "")),
                asset_url=str(asset.get("browser_download_url", "")),
                body=body,
                prompt_image_url=self.extract_first_release_image(body),
                update_kind=self.classify_update(current_version, latest_version),
            )
            if best_release is None or self.is_newer_version(best_release.version, candidate.version):
                best_release = candidate
        return best_release

    def _pick_installer_asset(self, assets: list[dict]) -> dict | None:
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).strip()
            asset_url = str(asset.get("browser_download_url", "")).strip()
            if not name or not self._is_valid_download_url(asset_url):
                continue
            if name.lower().endswith(".exe") and INSTALLER_NAME_PREFIX.lower() in name.lower():
                return asset
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).strip()
            asset_url = str(asset.get("browser_download_url", "")).strip()
            if not name or not self._is_valid_download_url(asset_url):
                continue
            if name.lower().endswith(".exe"):
                return asset
        return None

    @staticmethod
    def _is_valid_download_url(raw: str) -> bool:
        parsed = urlparse(str(raw).strip())
        return parsed.scheme == "https" and bool(parsed.netloc)

    def is_newer_version(self, current_version: str, latest_version: str) -> bool:
        try:
            return Version(pep440_version(latest_version)) > Version(pep440_version(current_version))
        except InvalidVersion:
            return self.normalize_version(latest_version) != self.normalize_version(current_version)

    @staticmethod
    def extract_first_release_image(markdown: str) -> str:
        parsed = parse_update_notes(markdown)
        return parsed.image_urls[0] if parsed.image_urls else ""

    def classify_update(self, current_version: str, latest_version: str) -> str:
        try:
            current = Version(pep440_version(current_version))
            latest = Version(pep440_version(latest_version))
        except InvalidVersion:
            return "manual"
        if latest <= current:
            return "none"
        if is_beta_version(latest_version):
            return "beta"
        if current.major == latest.major and current.minor == latest.minor and latest.micro > current.micro:
            return "patch"
        return "manual"

    def is_patch_update(self, current_version: str, latest_version: str) -> bool:
        return self.classify_update(current_version, latest_version) == "patch"

    def download_release_prompt_image(self, release: ReleaseInfo) -> Path | None:
        image_url = str(release.prompt_image_url or "").strip()
        if not image_url:
            return None
        suffix = Path(urlparse(image_url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            suffix = ".img"
        safe_tag = re.sub(r"[^a-zA-Z0-9._-]+", "_", release.tag_name or release.version or "release")
        destination = self.paths.runtime / f"release_prompt_{safe_tag}{suffix}"
        temp_destination = destination.with_suffix(destination.suffix + ".part")
        headers = {"User-Agent": "ONCard-Updater"}
        try:
            with requests.get(image_url, headers=headers, stream=True, timeout=20) as response:
                response.raise_for_status()
                destination.parent.mkdir(parents=True, exist_ok=True)
                with temp_destination.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            handle.write(chunk)
                temp_destination.replace(destination)
        except requests.RequestException:
            try:
                if temp_destination.exists():
                    temp_destination.unlink()
            except OSError:
                pass
            return None
        except OSError:
            try:
                if temp_destination.exists():
                    temp_destination.unlink()
            except OSError:
                pass
            return None
        return destination

    def download_installer(self, release: ReleaseInfo, on_progress=None) -> Path:
        destination = self.paths.updates / release.asset_name
        temp_destination = destination.with_suffix(destination.suffix + ".part")
        headers = {"User-Agent": "ONCard-Updater"}
        try:
            with requests.get(release.asset_url, headers=headers, stream=True, timeout=60) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or 0)
                received = 0
                destination.parent.mkdir(parents=True, exist_ok=True)
                with temp_destination.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        received += len(chunk)
                        if on_progress:
                            percent = int((received / total) * 100) if total > 0 else 0
                            on_progress(percent, f"Downloading {release.asset_name}...")
        except requests.RequestException as exc:
            self._cleanup_partial_download(temp_destination)
            raise UpdateError(f"Update download failed: {exc}") from exc
        except OSError as exc:
            self._cleanup_partial_download(temp_destination)
            raise UpdateError(f"Update download failed: {exc}") from exc
        if total > 0 and received < total:
            self._cleanup_partial_download(temp_destination)
            raise UpdateError("Update download failed: installer download was incomplete.")
        try:
            if destination.exists():
                destination.unlink()
            temp_destination.replace(destination)
        except OSError as exc:
            self._cleanup_partial_download(temp_destination)
            raise UpdateError(f"Update download failed: {exc}") from exc
        return destination

    @staticmethod
    def _cleanup_partial_download(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            return

    def create_post_exit_launcher(self, installer_path: Path, current_pid: int, *, silent: bool = False) -> Path:
        launcher_path = self.paths.updates / "run_update.ps1"
        launcher_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = self.paths.runtime / "update_launcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def _ps_quote(value: Path | str) -> str:
            return "'" + str(value).replace("'", "''") + "'"

        argument_list = ["/UPDATEFLOW", "/CLOSEAPPLICATIONS"]
        if silent:
            argument_list = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/SILENTPATCH", *argument_list]
        ps_arguments = "@(" + ", ".join(_ps_quote(argument) for argument in argument_list) + ")"

        script = "\r\n".join(
            [
                "$ErrorActionPreference = 'SilentlyContinue'",
                f"$pidToWait = {current_pid}",
                f"$installerPath = {_ps_quote(installer_path)}",
                f"$logPath = {_ps_quote(log_path)}",
                "Add-Content -Path $logPath -Value ('Launcher started ' + (Get-Date -Format o))",
                "while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {",
                "    Start-Sleep -Milliseconds 500",
                "}",
                "Add-Content -Path $logPath -Value ('Launching installer ' + $installerPath)",
                f"$process = Start-Process -FilePath $installerPath -ArgumentList {ps_arguments} -PassThru -Wait",
                "Add-Content -Path $logPath -Value ('Installer finished with code ' + $process.ExitCode)",
            ]
        )
        launcher_path.write_text(script, encoding="utf-8")
        return launcher_path

    def launch_helper(self, launcher_path: Path) -> None:
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher_path)],
                cwd=str(launcher_path.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise UpdateError(f"Could not launch updater helper: {exc}") from exc

    def save_update_state(self, payload: dict) -> None:
        self.paths.update_state.parent.mkdir(parents=True, exist_ok=True)
        self.paths.update_state.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_update_state(self) -> dict:
        if not self.paths.update_state.exists():
            return {}
        try:
            return json.loads(self.paths.update_state.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def clear_update_state(self) -> None:
        try:
            if self.paths.update_state.exists():
                self.paths.update_state.unlink()
        except OSError:
            return

    def load_ready_silent_patch(self, current_version: str) -> dict:
        state = self.load_update_state()
        if not state.get("pending_silent_install", False):
            return {}
        latest_version = str(state.get("latest_version", ""))
        if not self.is_patch_update(current_version, latest_version):
            self.clear_update_state()
            return {}
        installer_path = Path(str(state.get("installer_path", "")).strip()) if state.get("installer_path") else None
        if installer_path is None or not installer_path.exists() or not self._is_managed_update_path(installer_path):
            self.clear_update_state()
            return {}
        return state

    def _is_managed_update_path(self, path: Path) -> bool:
        try:
            return path.resolve().is_relative_to(self.paths.updates.resolve())
        except AttributeError:
            resolved = str(path.resolve())
            prefix = str(self.paths.updates.resolve())
            return resolved.startswith(prefix)
