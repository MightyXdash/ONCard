from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

from packaging.version import InvalidVersion, Version
import requests

from studymate.utils.paths import AppPaths
from studymate.version import GITHUB_RELEASES_API, INSTALLER_NAME_PREFIX


class UpdateError(RuntimeError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag_name: str
    html_url: str
    asset_name: str
    asset_url: str


class UpdateService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    @staticmethod
    def normalize_version(raw: str) -> str:
        value = raw.strip()
        if value.lower().startswith("v"):
            value = value[1:]
        return value

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

        tag_name = str(payload.get("tag_name", "")).strip()
        if not tag_name:
            return None

        latest_version = self.normalize_version(tag_name)
        if not self.is_newer_version(current_version, latest_version):
            return None

        asset = self._pick_installer_asset(payload.get("assets", []))
        if asset is None:
            return None
        return ReleaseInfo(
            version=latest_version,
            tag_name=tag_name,
            html_url=str(payload.get("html_url", "")),
            asset_name=str(asset.get("name", "")),
            asset_url=str(asset.get("browser_download_url", "")),
        )

    def _pick_installer_asset(self, assets: list[dict]) -> dict | None:
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.lower().endswith(".exe") and INSTALLER_NAME_PREFIX.lower() in name.lower():
                return asset
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.lower().endswith(".exe"):
                return asset
        return None

    def is_newer_version(self, current_version: str, latest_version: str) -> bool:
        try:
            return Version(self.normalize_version(latest_version)) > Version(self.normalize_version(current_version))
        except InvalidVersion:
            return self.normalize_version(latest_version) != self.normalize_version(current_version)

    def download_installer(self, release: ReleaseInfo, on_progress=None) -> Path:
        destination = self.paths.updates / release.asset_name
        headers = {"User-Agent": "ONCard-Updater"}
        try:
            with requests.get(release.asset_url, headers=headers, stream=True, timeout=60) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or 0)
                received = 0
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        received += len(chunk)
                        if on_progress:
                            percent = int((received / total) * 100) if total > 0 else 0
                            on_progress(percent, f"Downloading {release.asset_name}...")
        except requests.RequestException as exc:
            raise UpdateError(f"Update download failed: {exc}") from exc
        return destination

    def create_post_exit_launcher(self, installer_path: Path, current_pid: int, relaunch_path: Path | None = None) -> Path:
        launcher_path = self.paths.updates / "run_update.ps1"
        launcher_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = self.paths.runtime / "update_launcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def _ps_quote(value: Path | str) -> str:
            return "'" + str(value).replace("'", "''") + "'"

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
                "$process = Start-Process -FilePath $installerPath -ArgumentList @('/UPDATEFLOW', '/CLOSEAPPLICATIONS') -PassThru -Wait",
                "Add-Content -Path $logPath -Value ('Installer finished with code ' + $process.ExitCode)",
            ]
        )
        launcher_path.write_text(script, encoding="utf-8")
        return launcher_path

    def launch_helper(self, launcher_path: Path) -> None:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher_path)],
            cwd=str(launcher_path.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

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
