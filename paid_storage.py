from __future__ import annotations

import json
import secrets
from pathlib import Path

from xui.paid_settings_store import DAY, HOUR

PAID_SUBSCRIPTIONS_FILE = Path("data/paid_subscriptions.json")
PAID_REQUESTS_FILE = Path("data/paid_requests.json")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_paid_subscriptions() -> dict:
    raw = _read_json(PAID_SUBSCRIPTIONS_FILE, {})
    if not isinstance(raw, dict):
        return {}
    changed = False
    for info in raw.values():
        if not isinstance(info, dict):
            continue
        if "trial_seconds" not in info and info.get("trial_days") is not None:
            info["trial_seconds"] = int(info.get("trial_days") or 0) * DAY
            changed = True
        if "payment_seconds" not in info and info.get("payment_days") is not None:
            info["payment_seconds"] = int(info.get("payment_days") or 0) * DAY
            changed = True
        if "grace_seconds" not in info and info.get("grace_hours") is not None:
            info["grace_seconds"] = int(info.get("grace_hours") or 0) * HOUR
            changed = True
    if changed:
        save_paid_subscriptions(raw)
    return raw


def save_paid_subscriptions(data: dict) -> None:
    _write_json(PAID_SUBSCRIPTIONS_FILE, data)


def get_paid_subscription(tg_id: int) -> dict | None:
    return load_paid_subscriptions().get(str(tg_id))


def has_paid_subscription(tg_id: int) -> bool:
    info = get_paid_subscription(tg_id)
    if not info:
        return False
    status = str(info.get("status", "") or "").lower()
    if status in {"blocked", "disabled", "cancelled", "canceled"}:
        return False
    return bool(info.get("active", True)) or status in {"trial", "active", "grace", "pending_payment"}


def load_paid_requests() -> dict:
    raw = _read_json(PAID_REQUESTS_FILE, {})
    return raw if isinstance(raw, dict) else {}


def save_paid_requests(data: dict) -> None:
    _write_json(PAID_REQUESTS_FILE, data)


def get_paid_request(user_id: int) -> dict | None:
    return load_paid_requests().get(str(user_id))


def create_paid_request(user_id: int, username: str = "", first_name: str = "", last_name: str = "") -> tuple[str, dict]:
    data = load_paid_requests()
    key = str(user_id)
    request_id = data.get(key, {}).get("request_id") or secrets.token_hex(6)
    request = {
        "request_id": request_id,
        "user_id": int(user_id),
        "username": username or "",
        "first_name": first_name or "",
        "last_name": last_name or "",
        "status": "pending",
    }
    data[key] = request
    save_paid_requests(data)
    return request_id, request


def delete_paid_request(user_id: int) -> None:
    data = load_paid_requests()
    key = str(user_id)
    if key in data:
        data.pop(key, None)
        save_paid_requests(data)


def get_paid_request_by_id(request_id: str) -> dict | None:
    for request in load_paid_requests().values():
        if str(request.get("request_id", "")) == str(request_id):
            return request
    return None


def set_paid_subscription(user_id: int, data: dict) -> None:
    all_data = load_paid_subscriptions()
    all_data[str(user_id)] = data
    save_paid_subscriptions(all_data)
