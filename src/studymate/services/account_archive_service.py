from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
from urllib.parse import unquote
import zipfile
from typing import Any

from studymate.utils.paths import AppPaths


ARCHIVE_FILENAME_PATTERN = re.compile(
    r"^ONCARD_(?P<date>\d{8})_(?P<time>\d{6})_(?P<rand>[a-z]{7})_A(?P<age>\d{1,2})_G(?P<grade>\d{1,2})\.zip$"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _safe_sql_section_load(database_file: Path, section: str, default: dict) -> dict:
    db_path = Path(database_file)
    if not db_path.exists():
        return dict(default)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(str(db_path))
        row = connection.execute("SELECT payload_json FROM settings WHERE section = ?", (str(section),)).fetchone()
        if row is None:
            return dict(default)
        payload = json.loads(str(row[0]))
        if isinstance(payload, dict):
            return dict(payload)
    except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError):
        return dict(default)
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
    return dict(default)


def _coerce_grade_number(value: str) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:2] or "0"


def _coerce_age_number(value: str) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:2] or "0"


@dataclass(frozen=True)
class ArchiveInspection:
    valid: bool
    error: str
    manifest: dict[str, Any]
    profile: dict[str, Any]
    payload_root: str


class AccountArchiveService:
    MANIFEST_NAME = "oncard_manifest.json"
    FORMAT_VERSION = 1

    def build_export_filename(self, profile: dict, *, now: datetime | None = None) -> str:
        current = now or datetime.now()
        stamp_date = current.strftime("%Y%m%d")
        stamp_time = current.strftime("%H%M%S")
        random_part = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(7))
        age = _coerce_age_number(str(profile.get("age", "")))
        grade = _coerce_grade_number(str(profile.get("grade", "")))
        return f"ONCARD_{stamp_date}_{stamp_time}_{random_part}_A{age}_G{grade}.zip"

    def validate_filename(self, filename: str) -> bool:
        return ARCHIVE_FILENAME_PATTERN.fullmatch(str(filename or "").strip()) is not None

    def inspect_archive(self, archive_path: Path) -> ArchiveInspection:
        path = Path(archive_path)
        if not path.exists() or not path.is_file():
            return ArchiveInspection(valid=False, error="Selected file does not exist.", manifest={}, profile={}, payload_root="")
        if path.suffix.lower() != ".zip":
            return ArchiveInspection(valid=False, error="Only .zip files are supported.", manifest={}, profile={}, payload_root="")
        try:
            with zipfile.ZipFile(path, "r") as archive:
                names = [name for name in archive.namelist() if name and not name.endswith("/")]
                if not names:
                    return ArchiveInspection(valid=False, error="Zip file is empty.", manifest={}, profile={}, payload_root="")

                manifest: dict[str, Any] = {}
                if self.MANIFEST_NAME in names:
                    try:
                        parsed_manifest = json.loads(archive.read(self.MANIFEST_NAME).decode("utf-8"))
                        if isinstance(parsed_manifest, dict):
                            manifest = dict(parsed_manifest)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        manifest = {}

                has_account_prefix = any(name.startswith("account/") for name in names)
                payload_root = "account" if has_account_prefix else ""

                required_candidates = [
                    "oncard.sqlite",
                    "config/profile.json",
                    "config/setup.json",
                    "config/ai_settings.json",
                ]
                required_paths = {
                    f"{payload_root}/{candidate}".strip("/")
                    for candidate in required_candidates
                }
                if not any(path in names for path in required_paths):
                    return ArchiveInspection(
                        valid=False,
                        error="Zip does not look like an ONCard account export.",
                        manifest=manifest,
                        profile={},
                        payload_root=payload_root,
                    )

                profile = manifest.get("profile", {}) if isinstance(manifest.get("profile", {}), dict) else {}
                if not profile:
                    profile_path = f"{payload_root}/config/profile.json".strip("/")
                    if profile_path in names:
                        try:
                            loaded_profile = json.loads(archive.read(profile_path).decode("utf-8"))
                            if isinstance(loaded_profile, dict):
                                profile = dict(loaded_profile)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            profile = {}

                return ArchiveInspection(valid=True, error="", manifest=manifest, profile=dict(profile), payload_root=payload_root)
        except zipfile.BadZipFile:
            return ArchiveInspection(valid=False, error="Zip file is corrupted.", manifest={}, profile={}, payload_root="")
        except OSError as exc:
            return ArchiveInspection(valid=False, error=f"Could not read archive: {exc}", manifest={}, profile={}, payload_root="")

    def export_account(self, *, account: dict, paths: AppPaths, destination_zip: Path) -> Path:
        destination = Path(destination_zip)
        destination.parent.mkdir(parents=True, exist_ok=True)
        profile = _safe_sql_section_load(paths.database_file, "profile", {})
        if not profile:
            profile = _safe_json_load(paths.profile_config, {})
        setup = _safe_sql_section_load(paths.database_file, "setup", {})
        if not setup:
            setup = _safe_json_load(paths.setup_config, {})
        ai_settings = _safe_sql_section_load(paths.database_file, "ai_settings", {})
        if not ai_settings:
            ai_settings = _safe_json_load(paths.ai_settings_config, {})
        manifest = {
            "app": "ONCard",
            "format_version": self.FORMAT_VERSION,
            "account_id": str(account.get("id", "")).strip(),
            "account_name": str(account.get("name", "")).strip(),
            "exported_at": _now_iso(),
            "profile": profile if isinstance(profile, dict) else {},
            "setup": setup if isinstance(setup, dict) else {},
            "ai_settings": ai_settings if isinstance(ai_settings, dict) else {},
        }
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(self.MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
            root = paths.data
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                relative = item.relative_to(root)
                if str(relative).startswith("__pycache__"):
                    continue
                archive.write(item, Path("account") / relative)
        return destination

    def create_temp_export(self, *, account: dict, paths: AppPaths) -> Path:
        profile = _safe_sql_section_load(paths.database_file, "profile", {})
        if not profile:
            profile = _safe_json_load(paths.profile_config, {})
        filename = self.build_export_filename(profile if isinstance(profile, dict) else {})
        temp_dir = Path(tempfile.mkdtemp(prefix="oncard_export_"))
        target = temp_dir / filename
        return self.export_account(account=account, paths=paths, destination_zip=target)

    def import_archive_into_account(self, *, archive_path: Path, paths: AppPaths, overwrite: bool = True) -> None:
        inspection = self.inspect_archive(Path(archive_path))
        if not inspection.valid:
            raise ValueError(inspection.error or "Invalid archive.")

        target_root = paths.data
        temp_dir = Path(tempfile.mkdtemp(prefix="oncard_import_"))
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                self._safe_extract_zip(archive, temp_dir)
            extracted_root = (temp_dir / inspection.payload_root) if inspection.payload_root else temp_dir
            if not extracted_root.exists() or not extracted_root.is_dir():
                raise ValueError("Archive payload is missing account data.")
            if overwrite:
                self._clear_directory(target_root)
            target_root.mkdir(parents=True, exist_ok=True)
            for entry in extracted_root.iterdir():
                destination = target_root / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, destination, dirs_exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(entry, destination)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _clear_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        resolved_root = path.resolve()
        for item in list(path.iterdir()):
            resolved = item.resolve()
            if not str(resolved).startswith(str(resolved_root)):
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)

    @staticmethod
    def _safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        for member in archive.infolist():
            raw_name = str(member.filename or "")
            if not raw_name or raw_name.endswith("/"):
                continue
            normalized = Path(unquote(raw_name))
            target = (destination / normalized).resolve()
            if not str(target).startswith(str(destination_root)):
                raise ValueError("Archive contains unsafe paths.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
