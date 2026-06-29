from __future__ import annotations

import json
from pathlib import Path

INBOUND_SETTINGS_FILE = Path("data/inbound_settings.json")


def _load() -> dict[str, str]:
    if not INBOUND_SETTINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(INBOUND_SETTINGS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save(data: dict[str, str]) -> None:
    INBOUND_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    INBOUND_SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_inbound_sub_port(inbound_id) -> str:
    return str(_load().get(str(inbound_id), "")).strip()


def set_inbound_sub_port(inbound_id, sub_port: str) -> None:
    data = _load()
    data[str(inbound_id)] = str(sub_port).strip()
    _save(data)
