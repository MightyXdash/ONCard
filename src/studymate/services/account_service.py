from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import shutil
from typing import Any

from studymate.utils.paths import AppPaths


ACCOUNT_ID_PATTERN = re.compile(r"^[a-z]{34}$")
_ACCOUNT_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_json_load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


@dataclass(frozen=True)
class AccountRecord:
    id: str
    name: str
    created_at: str
    updated_at: str
    last_used_at: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AccountRecord | None":
        account_id = str(payload.get("id", "")).strip()
        if not ACCOUNT_ID_PATTERN.fullmatch(account_id):
            return None
        name = str(payload.get("name", "")).strip()
        created_at = str(payload.get("created_at", "")).strip() or _now_iso()
        updated_at = str(payload.get("updated_at", "")).strip() or created_at
        last_used_at = str(payload.get("last_used_at", "")).strip() or updated_at
        return cls(
            id=account_id,
            name=name or f"Account {account_id[:6]}",
            created_at=created_at,
            updated_at=updated_at,
            last_used_at=last_used_at,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
        }


class AccountService:
    INDEX_VERSION = 1

    def __init__(self, base_paths: AppPaths) -> None:
        self.base_paths = base_paths
        self.accounts_root = self.base_paths.accounts
        self.index_file = self.base_paths.accounts_index_file
        self.accounts_root.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()
        self._bootstrap()

    def _default_index(self) -> dict[str, Any]:
        return {
            "version": self.INDEX_VERSION,
            "active_account_id": "",
            "accounts": [],
            "updated_at": _now_iso(),
        }

    def _load_index(self) -> dict[str, Any]:
        raw = _safe_json_load(self.index_file, self._default_index())
        if not isinstance(raw, dict):
            return self._default_index()
        index = self._default_index()
        index["active_account_id"] = str(raw.get("active_account_id", "")).strip()
        index["updated_at"] = str(raw.get("updated_at", "")).strip() or _now_iso()
        parsed_accounts: list[dict[str, str]] = []
        for item in raw.get("accounts", []):
            if not isinstance(item, dict):
                continue
            parsed = AccountRecord.from_dict(item)
            if parsed is not None:
                parsed_accounts.append(parsed.to_dict())
        index["accounts"] = parsed_accounts
        return index

    def _save_index(self) -> None:
        self._index["updated_at"] = _now_iso()
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(json.dumps(self._index, indent=2, ensure_ascii=False), encoding="utf-8")

    def _bootstrap(self) -> None:
        accounts = self._index_accounts()
        scanned = self._scan_existing_accounts()
        known_by_id = {item["id"]: item for item in accounts}
        for candidate in scanned:
            if candidate["id"] in known_by_id:
                continue
            accounts.append(candidate)
            known_by_id[candidate["id"]] = candidate

        self._index["accounts"] = accounts
        if not accounts and self._legacy_data_exists():
            migrated = self._migrate_legacy_data()
            if migrated is not None:
                accounts.append(migrated.to_dict())
                self._index["active_account_id"] = migrated.id

        active = str(self._index.get("active_account_id", "")).strip()
        valid_ids = {item["id"] for item in self._index["accounts"]}
        if active not in valid_ids:
            self._index["active_account_id"] = self._index["accounts"][0]["id"] if self._index["accounts"] else ""
        self._save_index()

    def _index_accounts(self) -> list[dict[str, str]]:
        accounts: list[dict[str, str]] = []
        for item in self._index.get("accounts", []):
            if not isinstance(item, dict):
                continue
            parsed = AccountRecord.from_dict(item)
            if parsed is None:
                continue
            accounts.append(parsed.to_dict())
        return accounts

    def _scan_existing_accounts(self) -> list[dict[str, str]]:
        discovered: list[dict[str, str]] = []
        if not self.accounts_root.exists():
            return discovered
        for folder in sorted(path for path in self.accounts_root.iterdir() if path.is_dir()):
            account_id = folder.name
            if not ACCOUNT_ID_PATTERN.fullmatch(account_id):
                continue
            now = _now_iso()
            discovered.append(
                AccountRecord(
                    id=account_id,
                    name=self._profile_name_from_account_root(folder) or f"Account {account_id[:6]}",
                    created_at=now,
                    updated_at=now,
                    last_used_at=now,
                ).to_dict()
            )
        return discovered

    def _profile_name_from_account_root(self, account_root: Path) -> str:
        profile_path = account_root / "config" / "profile.json"
        payload = _safe_json_load(profile_path, {})
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("name", "")).strip()

    def _legacy_data_exists(self) -> bool:
        base = self.base_paths.base_data
        explicit_files = [
            base / "oncard.sqlite",
            base / "config" / "setup.json",
            base / "config" / "profile.json",
            base / "config" / "ai_settings.json",
            base / "study_history" / "attempts.json",
            base / "runtime" / "embedding_cache.json",
            base / "runtime" / "update_state.json",
        ]
        if any(file_path.exists() and file_path.is_file() for file_path in explicit_files):
            return True
        subject_dir = base / "subjects"
        if subject_dir.exists() and subject_dir.is_dir():
            if any(path.is_file() for path in subject_dir.glob("*.json")):
                return True
        for maybe_nonempty in (base / "runtime", base / "updates"):
            if maybe_nonempty.exists() and maybe_nonempty.is_dir():
                if any(path.is_file() for path in maybe_nonempty.rglob("*")):
                    return True
        if self.base_paths.base_local_data != self.base_paths.base_data:
            local_markers = [
                self.base_paths.base_local_data / "runtime",
                self.base_paths.base_local_data / "updates",
            ]
            for marker in local_markers:
                if marker.exists() and marker.is_dir():
                    if any(path.is_file() for path in marker.rglob("*")):
                        return True
        return False

    def _next_account_id(self) -> str:
        existing = {item["id"] for item in self._index_accounts()}
        while True:
            candidate = "".join(secrets.choice(_ACCOUNT_ID_ALPHABET) for _ in range(34))
            if candidate not in existing:
                return candidate

    def _migrate_legacy_data(self) -> AccountRecord | None:
        account_id = self._next_account_id()
        account_root = self.accounts_root / account_id
        account_root.mkdir(parents=True, exist_ok=True)

        profile_name = ""
        profile_path = self.base_paths.base_data / "config" / "profile.json"
        profile_payload = _safe_json_load(profile_path, {})
        if isinstance(profile_payload, dict):
            profile_name = str(profile_payload.get("name", "")).strip()
        now = _now_iso()
        record = AccountRecord(
            id=account_id,
            name=profile_name or f"Account {account_id[:6]}",
            created_at=now,
            updated_at=now,
            last_used_at=now,
        )

        data_entries = [
            "config",
            "subjects",
            "study_history",
            "backups",
            "runtime",
            "updates",
            "oncard.sqlite",
        ]
        for name in data_entries:
            source = self.base_paths.base_data / name
            if not source.exists():
                continue
            destination = account_root / name
            self._move_or_copy_path(source, destination, prefer_copy=True)

        if self.base_paths.base_local_data != self.base_paths.base_data:
            for name in ("runtime", "updates"):
                source = self.base_paths.base_local_data / name
                if not source.exists():
                    continue
                destination = account_root / name
                self._move_or_copy_path(source, destination, prefer_copy=True)
        return record

    @staticmethod
    def _move_or_copy_path(source: Path, destination: Path, *, prefer_copy: bool = False) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination, ignore_errors=True)
            else:
                destination.unlink(missing_ok=True)
        if source.is_dir():
            if prefer_copy:
                shutil.copytree(source, destination, dirs_exist_ok=True)
                return
            try:
                shutil.move(str(source), str(destination))
                return
            except OSError:
                shutil.copytree(source, destination, dirs_exist_ok=True)
                shutil.rmtree(source, ignore_errors=True)
                return
        if prefer_copy:
            shutil.copy2(source, destination)
            return
        try:
            shutil.move(str(source), str(destination))
        except OSError:
            shutil.copy2(source, destination)
            source.unlink(missing_ok=True)

    def list_accounts(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._index_accounts()]

    def get_account(self, account_id: str) -> dict[str, str] | None:
        target = str(account_id or "").strip()
        for item in self._index_accounts():
            if item["id"] == target:
                return dict(item)
        return None

    def get_active_account_id(self) -> str:
        return str(self._index.get("active_account_id", "")).strip()

    def get_active_account(self) -> dict[str, str] | None:
        active_id = self.get_active_account_id()
        if not active_id:
            return None
        return self.get_account(active_id)

    def ensure_seed_account(self, *, name: str = "Account 1") -> dict[str, str]:
        active = self.get_active_account()
        if active is not None:
            return active
        return self.create_account(name=name, make_active=True)

    def account_paths(self, account_id: str) -> AppPaths:
        return self.base_paths.for_account(account_id)

    def name_exists(self, name: str, *, exclude_account_id: str = "") -> bool:
        target = str(name or "").strip()
        if not target:
            return False
        excluded = str(exclude_account_id or "").strip()
        for item in self._index_accounts():
            if item["id"] == excluded:
                continue
            if str(item.get("name", "")).strip() == target:
                return True
        return False

    def create_account(self, *, name: str, make_active: bool = True) -> dict[str, str]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Account name is required")
        if self.name_exists(clean_name):
            raise ValueError("An account with this name already exists.")
        account_id = self._next_account_id()
        account_paths = self.account_paths(account_id)
        account_paths.ensure()
        now = _now_iso()
        record = AccountRecord(
            id=account_id,
            name=clean_name,
            created_at=now,
            updated_at=now,
            last_used_at=now,
        ).to_dict()
        accounts = self._index_accounts()
        accounts.append(record)
        self._index["accounts"] = accounts
        if make_active:
            self._index["active_account_id"] = account_id
        self._save_index()
        return dict(record)

    def rename_account(self, account_id: str, new_name: str) -> dict[str, str]:
        target = str(account_id or "").strip()
        updated_name = str(new_name or "").strip()
        if not target:
            raise ValueError("account_id is required")
        if not updated_name:
            raise ValueError("name is required")
        if self.name_exists(updated_name, exclude_account_id=target):
            raise ValueError("An account with this name already exists.")
        now = _now_iso()
        accounts = self._index_accounts()
        updated: dict[str, str] | None = None
        for item in accounts:
            if item["id"] != target:
                continue
            item["name"] = updated_name
            item["updated_at"] = now
            updated = item
            break
        if updated is None:
            raise ValueError("Account was not found.")
        self._index["accounts"] = accounts
        self._save_index()
        return dict(updated)

    def touch_last_used(self, account_id: str) -> None:
        target = str(account_id or "").strip()
        now = _now_iso()
        accounts = self._index_accounts()
        changed = False
        for item in accounts:
            if item["id"] != target:
                continue
            item["last_used_at"] = now
            item["updated_at"] = now
            changed = True
            break
        if changed:
            self._index["accounts"] = accounts
            self._save_index()

    def set_active_account(self, account_id: str) -> dict[str, str]:
        target = str(account_id or "").strip()
        account = self.get_account(target)
        if account is None:
            raise ValueError("Account was not found.")
        self._index["active_account_id"] = target
        self.touch_last_used(target)
        return account

    def _pick_last_used_account(self, account_ids: set[str]) -> str:
        if not account_ids:
            return ""
        ranked: list[tuple[tuple[datetime, datetime, int], str]] = []
        for index, item in enumerate(self._index_accounts()):
            if item["id"] not in account_ids:
                continue
            ranked.append(
                (
                    (
                        _parse_iso(str(item.get("last_used_at", ""))),
                        _parse_iso(str(item.get("updated_at", ""))),
                        index,
                    ),
                    item["id"],
                )
            )
        if not ranked:
            return ""
        ranked.sort(reverse=True)
        return ranked[0][1]

    def delete_account(self, account_id: str) -> str:
        target = str(account_id or "").strip()
        if not target:
            raise ValueError("account_id is required")
        accounts = self._index_accounts()
        remaining = [item for item in accounts if item["id"] != target]
        if len(remaining) == len(accounts):
            raise ValueError("Account was not found.")
        account_root = self.accounts_root / target
        if account_root.exists():
            resolved_target = account_root.resolve()
            resolved_root = self.accounts_root.resolve()
            if str(resolved_target).startswith(str(resolved_root)):
                shutil.rmtree(account_root, ignore_errors=True)
        remaining_ids = {item["id"] for item in remaining}
        next_active = self._pick_last_used_account(remaining_ids)
        self._index["accounts"] = remaining
        self._index["active_account_id"] = next_active
        self._save_index()
        return next_active
