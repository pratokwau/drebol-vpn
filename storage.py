from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import AUTH_FILE, SETTINGS_FILE, XUI_SETTINGS_FILE

UPDATE_STATE_FILE = Path("data/update_state.json")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value: Any) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def authorized_path() -> Path:
    return Path(AUTH_FILE)


def load_authorized_users() -> list[int]:
    raw = _read_json(authorized_path(), [])
    return [int(x) for x in raw] if isinstance(raw, list) else []


def save_authorized_users(users: list[int]) -> None:
    _write_json(authorized_path(), [int(x) for x in users])


def load_settings() -> dict[str, Any]:
    raw = _read_json(Path(SETTINGS_FILE), {})
    return raw if isinstance(raw, dict) else {}


def save_settings(data: dict[str, Any]) -> None:
    _write_json(Path(SETTINGS_FILE), data)


def load_xui_settings() -> dict[str, str]:
    raw = _read_json(Path(XUI_SETTINGS_FILE), {})
    if not isinstance(raw, dict):
        return {}
    settings = {str(k): str(v) for k, v in raw.items()}
    settings.setdefault("XUI_SUB_PORT", "")
    return settings


def save_xui_settings(data: dict[str, str]) -> None:
    _write_json(Path(XUI_SETTINGS_FILE), {str(k): str(v) for k, v in data.items()})


def load_update_state() -> dict[str, Any]:
    raw = _read_json(UPDATE_STATE_FILE, {})
    return raw if isinstance(raw, dict) else {}


def save_update_state(data: dict[str, Any]) -> None:
    _write_json(UPDATE_STATE_FILE, data)


def clear_update_state() -> None:
    if UPDATE_STATE_FILE.exists():
        UPDATE_STATE_FILE.unlink()
