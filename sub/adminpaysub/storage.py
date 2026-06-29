from __future__ import annotations

import json
import hashlib
import secrets
from pathlib import Path

PAID_VPN_USERS_FILE = Path("data/paid_vpn_users.json")
PAID_CLIENT_NOTES_FILE = Path("data/paid_client_notes.json")
NOTE_MAX_LEN = 50
DEFAULT_MAX_DEVICES = 1
DEFAULT_LIMIT_IP = 2
DEFAULT_LIMIT_GB = 0.0
DEFAULT_EXPIRY_TIME_MS = 2523456000000
DEFAULT_FLOW = "xtls-rprx-vision"


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


def load_vpn_users() -> dict:
    raw = _read_json(PAID_VPN_USERS_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    if raw:
        return _migrate_vpn_users(raw)
    migrated = _migrate_paid_users_from_shared_storage()
    if migrated:
        save_vpn_users(migrated)
        return _migrate_vpn_users(migrated)
    return _migrate_vpn_users(raw)


def _migrate_vpn_users(data: dict) -> dict:
    changed = False
    migrated: dict = {}
    for tg_id, info in data.items():
        if not isinstance(info, dict):
            migrated[str(tg_id)] = {
                "subscription_type": "admin",
                "username": "",
                "note": "",
                "default_ib_id": 0,
                "max_devices": DEFAULT_MAX_DEVICES,
                "limit_gb": None,
                "expiry_time_ms": None,
                "limit_ip": None,
                "flow": DEFAULT_FLOW,
                "settings_ready": False,
                "admin_disabled": False,
                "has_vpn_access": False,
                "devices": [],
            }
            changed = True
            continue
        normalized_key = _normalize_paid_user_key(str(tg_id), info)
        target_key = normalized_key or str(tg_id)
        info.setdefault("subscription_type", "admin")
        info.setdefault("username", "")
        info.setdefault("note", "")
        info.setdefault("default_ib_id", 0)
        info.setdefault("max_devices", DEFAULT_MAX_DEVICES)
        info.setdefault("limit_gb", None)
        info.setdefault("expiry_time_ms", None)
        info.setdefault("limit_ip", None)
        info.setdefault("flow", DEFAULT_FLOW)
        info.setdefault("settings_ready", bool(info.get("devices")) or bool(info.get("has_vpn_access")))
        info.setdefault("admin_disabled", False)
        info.setdefault("has_vpn_access", False)
        if "devices" not in info:
            old_uuid = info.get("uuid")
            old_email = info.get("email")
            old_ib = info.get("ib_id")
            devices = []
            if old_uuid and old_email and old_ib:
                devices.append({"ib_id": old_ib, "uuid": old_uuid, "email": old_email})
            info["devices"] = devices
            info.pop("uuid", None)
            info.pop("email", None)
            info.pop("ib_id", None)
            changed = True
        if info.get("default_ib_id") in (None, "", 0) and info.get("devices"):
            first_ib = info["devices"][0].get("ib_id", 0)
            if first_ib:
                info["default_ib_id"] = int(first_ib)
                changed = True
        if target_key != str(tg_id):
            changed = True
        migrated[target_key] = info
    if changed:
        save_vpn_users(migrated)
    return migrated


def save_vpn_users(data: dict) -> None:
    _write_json(PAID_VPN_USERS_FILE, data)


def _paid_user_key(tg_id: int | str) -> str:
    key = str(tg_id)
    if key.startswith("paid_") or key.startswith("anon_"):
        return key
    return f"paid_{key}"


def _resolve_user_key(user_key: str | int) -> str:
    key = str(user_key)
    data = load_vpn_users()
    if key in data:
        return key
    paid_key = _paid_user_key(key)
    if paid_key in data:
        return paid_key
    if key.startswith("anon_"):
        return key
    return paid_key


def _normalize_paid_user_key(user_key: str, info: dict) -> str | None:
    key = str(user_key)
    if key.startswith("paid_") or key.startswith("anon_"):
        return key
    if str(info.get("subscription_type", "")).lower() == "paid" and key.isdigit():
        return f"paid_{key}"
    return None


def _migrate_paid_users_from_shared_storage() -> dict:
    try:
        from sub.adminsub.storage import load_vpn_users as load_admin_users, save_vpn_users as save_admin_users
    except Exception:
        return {}
    admin_users = load_admin_users()
    if not isinstance(admin_users, dict):
        return {}
    paid_users: dict = {}
    remaining_users: dict = {}
    for user_key, info in admin_users.items():
        if isinstance(info, dict):
            normalized_key = _normalize_paid_user_key(str(user_key), info)
            if normalized_key:
                paid_users[normalized_key] = info
                if normalized_key != str(user_key):
                    continue
                if str(info.get("subscription_type", "")).lower() == "paid":
                    continue
        remaining_users[str(user_key)] = info
    if paid_users:
        save_admin_users(remaining_users)
    return paid_users


def get_vpn_user(tg_id: int) -> dict | None:
    data = load_vpn_users()
    return data.get(_paid_user_key(tg_id)) or data.get(str(tg_id))


def get_tg_id_by_client(ib_id: int, email: str) -> int | None:
    data = load_vpn_users()
    for tg_id, info in data.items():
        for d in info.get("devices", []):
            if d.get("ib_id") == ib_id and d.get("email") == email:
                try:
                    return int(tg_id)
                except ValueError:
                    return None
    return None


def get_user_key_by_client(ib_id: int, email: str) -> str | None:
    data = load_vpn_users()
    for user_key, info in data.items():
        for d in info.get("devices", []):
            if d.get("ib_id") == ib_id and d.get("email") == email:
                return str(user_key)
    return None


def _anon_user_key(ib_id: int, email: str) -> str:
    digest = hashlib.sha1(f"{ib_id}:{email}".encode("utf-8")).hexdigest()[:10]
    return f"anon_{digest}"


def ensure_anon_user_for_client(ib_id: int, uuid: str, email: str, limit_ip: int | None = None) -> str:
    existing_key = get_user_key_by_client(ib_id, email)
    if existing_key:
        return existing_key
    key = _anon_user_key(ib_id, email)
    add_device_to_user_key(key, ib_id, uuid, email, limit_ip=limit_ip, label=email)
    return key


def _add_device_to_user_key(user_key: str, ib_id: int, uuid: str, email: str, limit_ip: int | None = None, label: str = ""):
    data = load_vpn_users()
    key = _resolve_user_key(user_key)
    if key not in data:
        data[key] = {
            "subscription_type": "paid",
            "username": "",
            "note": "",
            "default_ib_id": int(ib_id or 0),
            "max_devices": DEFAULT_MAX_DEVICES,
            "limit_gb": None,
            "expiry_time_ms": None,
            "limit_ip": None,
            "flow": DEFAULT_FLOW,
            "settings_ready": False,
            "admin_disabled": False,
            "has_vpn_access": False,
            "devices": [],
        }
    if not data[key].get("default_ib_id"):
        data[key]["default_ib_id"] = int(ib_id or 0)
    for d in data[key]["devices"]:
        if d.get("ib_id") == ib_id and d.get("email") == email:
            d["uuid"] = uuid
            if limit_ip is not None:
                d["limit_ip"] = int(limit_ip)
            if label:
                d["label"] = label[:NOTE_MAX_LEN]
            save_vpn_users(data)
            return
    device = {"ib_id": ib_id, "uuid": uuid, "email": email}
    if limit_ip is not None:
        device["limit_ip"] = int(limit_ip)
    if label:
        device["label"] = label[:NOTE_MAX_LEN]
    data[key]["devices"].append(device)
    save_vpn_users(data)


def add_device_to_user(tg_id: int, ib_id: int, uuid: str, email: str, limit_ip: int | None = None, label: str = ""):
    _add_device_to_user_key(str(tg_id), ib_id, uuid, email, limit_ip=limit_ip, label=label)


def add_device_to_user_key(user_key: str, ib_id: int, uuid: str, email: str, limit_ip: int | None = None, label: str = ""):
    _add_device_to_user_key(user_key, ib_id, uuid, email, limit_ip=limit_ip, label=label)


def remove_device_from_user(tg_id: int, ib_id: int, email: str):
    data = load_vpn_users()
    key = str(tg_id)
    if key in data:
        data[key]["devices"] = [
            d for d in data[key].get("devices", [])
            if not (d.get("ib_id") == ib_id and d.get("email") == email)
        ]
        save_vpn_users(data)


def create_user(tg_id: int | None, max_devices: int = DEFAULT_MAX_DEVICES, note: str = "") -> str:
    data = load_vpn_users()
    if tg_id:
        key = _paid_user_key(tg_id)
        if key in data:
            data[key]["max_devices"] = max_devices
            if note:
                data[key]["note"] = note[:NOTE_MAX_LEN]
            save_vpn_users(data)
            return key
    else:
        key = f"anon_{secrets.token_hex(4)}"
    data[key] = {
        "subscription_type": "paid",
        "username": "",
        "default_ib_id": 0,
        "note": note[:NOTE_MAX_LEN],
        "max_devices": max_devices,
        "limit_gb": None,
        "expiry_time_ms": None,
        "limit_ip": None,
        "settings_ready": False,
        "admin_disabled": False,
        "has_vpn_access": False,
        "devices": [],
    }
    save_vpn_users(data)
    return key


def create_user_with_inbound(tg_id: int | None, ib_id: int, note: str = "", subscription_type: str = "paid") -> str:
    data = load_vpn_users()
    if tg_id is None:
        key = f"anon_{secrets.token_hex(4)}"
    else:
        key = _paid_user_key(tg_id)
    if key not in data:
        data[key] = {
            "subscription_type": subscription_type or "paid",
            "username": "",
            "default_ib_id": int(ib_id or 0),
            "note": note[:NOTE_MAX_LEN],
            "max_devices": DEFAULT_MAX_DEVICES,
            "limit_gb": None,
            "expiry_time_ms": None,
            "limit_ip": None,
            "flow": DEFAULT_FLOW,
            "settings_ready": False,
            "admin_disabled": False,
            "has_vpn_access": False,
            "devices": [],
        }
    else:
        data[key]["default_ib_id"] = int(ib_id or 0)
        data[key]["subscription_type"] = subscription_type
        if note:
            data[key]["note"] = note[:NOTE_MAX_LEN]
    save_vpn_users(data)
    return key


def _set_user_field(user_key: str, field: str, value) -> None:
    data = load_vpn_users()
    key = _resolve_user_key(user_key)
    if key in data:
        data[key][field] = value
        save_vpn_users(data)


def _recompute_user_settings_ready(user_key: str) -> bool:
    data = load_vpn_users()
    key = str(user_key)
    info = data.get(key)
    if not info:
        return False
    ready = all(info.get(field) is not None for field in ("max_devices", "limit_gb", "expiry_time_ms", "limit_ip", "flow"))
    info["settings_ready"] = ready
    if ready:
        info["has_vpn_access"] = True
    save_vpn_users(data)
    return ready


def set_user_default_ib_id(user_key: str | int, ib_id: int) -> None:
    _set_user_field(str(user_key), "default_ib_id", int(ib_id or 0))


def set_user_max_devices(user_key: str | int, value: int | None) -> None:
    _set_user_field(str(user_key), "max_devices", None if value is None else int(value))
    _recompute_user_settings_ready(str(user_key))


def set_user_limit_gb(user_key: str | int, value: float | None) -> None:
    _set_user_field(str(user_key), "limit_gb", None if value is None else float(value))
    _recompute_user_settings_ready(str(user_key))


def set_user_expiry_time_ms(user_key: str | int, value: int | None) -> None:
    _set_user_field(str(user_key), "expiry_time_ms", None if value is None else int(value))
    _recompute_user_settings_ready(str(user_key))


def set_user_limit_ip(user_key: str | int, value: int | None) -> None:
    _set_user_field(str(user_key), "limit_ip", None if value is None else int(value))
    _recompute_user_settings_ready(str(user_key))


def set_user_flow(user_key: str | int, value: str | None) -> None:
    _set_user_field(str(user_key), "flow", DEFAULT_FLOW if not value else str(value))
    _recompute_user_settings_ready(str(user_key))


def set_user_settings_ready(user_key: str | int, value: bool) -> None:
    _set_user_field(str(user_key), "settings_ready", bool(value))
    if value:
        _set_user_field(str(user_key), "has_vpn_access", True)


def get_effective_user_setting(info: dict, field: str):
    if field == "max_devices":
        value = info.get("max_devices")
        return DEFAULT_MAX_DEVICES if value in (None, "") else int(value)
    if field == "limit_gb":
        value = info.get("limit_gb")
        return DEFAULT_LIMIT_GB if value in (None, "") else float(value)
    if field == "expiry_time_ms":
        value = info.get("expiry_time_ms")
        return DEFAULT_EXPIRY_TIME_MS if value in (None, "") else int(value)
    if field == "limit_ip":
        value = info.get("limit_ip")
        return DEFAULT_LIMIT_IP if value in (None, "") else int(value)
    if field == "flow":
        value = info.get("flow")
        return DEFAULT_FLOW if value in (None, "") else str(value)
    if field == "default_ib_id":
        value = info.get("default_ib_id")
        return int(value or 0)
    return info.get(field)


def user_settings_ready(info: dict) -> bool:
    return bool(info.get("settings_ready")) and all(
        info.get(field) is not None for field in ("max_devices", "limit_gb", "expiry_time_ms", "limit_ip", "flow")
    )


def set_user_vpn_access(tg_id: int, value: bool = True):
    data = load_vpn_users()
    key = _resolve_user_key(tg_id)
    if key in data:
        data[key]["has_vpn_access"] = bool(value)
        save_vpn_users(data)


def set_user_vpn_access_key(user_key: str, value: bool = True):
    data = load_vpn_users()
    key = _resolve_user_key(user_key)
    if key in data:
        data[key]["has_vpn_access"] = bool(value)
        save_vpn_users(data)


def set_user_subscription_type(user_key: str | int, subscription_type: str) -> None:
    data = load_vpn_users()
    key = _resolve_user_key(user_key)
    if key in data:
        data[key]["subscription_type"] = str(subscription_type or "admin")
        save_vpn_users(data)


def get_users_by_subscription_type(subscription_type: str) -> dict:
    data = load_vpn_users()
    wanted = str(subscription_type or "").lower()
    return {
        user_key: info
        for user_key, info in data.items()
        if str(info.get("subscription_type", "admin")).lower() == wanted
    }


def set_admin_disabled_key(user_key: str, value: bool):
    data = load_vpn_users()
    key = _resolve_user_key(user_key)
    if key in data:
        data[key]["admin_disabled"] = bool(value)
        save_vpn_users(data)


def set_user_note_key(user_key: str, note: str):
    data = load_vpn_users()
    key = _resolve_user_key(user_key)
    if key in data:
        data[key]["note"] = note[:NOTE_MAX_LEN]
        save_vpn_users(data)


def rekey_user(old_key: str, new_key: str) -> bool:
    data = load_vpn_users()
    old_key = _resolve_user_key(old_key)
    new_key = _resolve_user_key(new_key)
    if old_key not in data:
        return False
    payload = data.pop(old_key)
    if new_key in data:
        existing = data[new_key]
        existing_devices = existing.get("devices", [])
        payload_devices = payload.get("devices", [])
        merged_devices = existing_devices + [d for d in payload_devices if d not in existing_devices]
        existing.update(payload)
        existing["devices"] = merged_devices
        data[new_key] = existing
    else:
        data[new_key] = payload
    save_vpn_users(data)
    return True


def delete_user_completely(user_key: str):
    data = load_vpn_users()
    user = data.pop(_resolve_user_key(user_key), None)
    save_vpn_users(data)
    return user


def set_admin_disabled(tg_id: int, value: bool):
    data = load_vpn_users()
    key = _resolve_user_key(tg_id)
    if key in data:
        data[key]["admin_disabled"] = value
        save_vpn_users(data)


def set_user_note(tg_id: int, note: str):
    data = load_vpn_users()
    key = _resolve_user_key(tg_id)
    if key in data:
        data[key]["note"] = note[:NOTE_MAX_LEN]
        save_vpn_users(data)


def get_user_note(user_key: str) -> str:
    data = load_vpn_users()
    return str(data.get(_resolve_user_key(user_key), {}).get("note", ""))


def set_user_username(tg_id: int, username: str):
    data = load_vpn_users()
    key = _resolve_user_key(tg_id)
    if key in data:
        data[key]["username"] = username or ""
        save_vpn_users(data)


async def refresh_username(tg_id: int) -> str:
    try:
        from loader import bot as _bot
        chat = await _bot.get_chat(tg_id)
        username = chat.username or ""
        set_user_username(tg_id, username)
        return username
    except Exception as e:
        print(f"[XUI USERNAME] Не удалось получить username для {tg_id}: {e}")
        return ""


def load_client_notes() -> dict:
    return _read_json(PAID_CLIENT_NOTES_FILE, {}) if PAID_CLIENT_NOTES_FILE.exists() else {}


def save_client_notes(data: dict):
    _write_json(PAID_CLIENT_NOTES_FILE, data)


def get_client_note(ib_id: int, email: str) -> str:
    data = load_client_notes()
    return data.get(f"{ib_id}_{email}", "")


def set_client_note(ib_id: int, email: str, note: str):
    data = load_client_notes()
    key = f"{ib_id}_{email}"
    if note:
        data[key] = note[:NOTE_MAX_LEN]
    else:
        data.pop(key, None)
    save_client_notes(data)


def remove_client_note(ib_id: int, email: str):
    data = load_client_notes()
    data.pop(f"{ib_id}_{email}", None)
    save_client_notes(data)
