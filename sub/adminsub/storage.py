from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

VPN_USERS_FILE = Path("data/vpn_users.json")
CLIENT_NOTES_FILE = Path("data/client_notes.json")
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
    raw = _read_json(VPN_USERS_FILE, {})
    if not isinstance(raw, dict):
        return {}
    migrated = _migrate_vpn_users(raw)
    cleaned = {
        user_key: info
        for user_key, info in migrated.items()
        if isinstance(info, dict)
        and not str(user_key).startswith("paid_")
        and str(info.get("subscription_type", "")).lower() != "paid"
    }
    if cleaned != migrated:
        save_vpn_users(cleaned)
    return cleaned


def _migrate_vpn_users(data: dict) -> dict:
    changed = False
    for tg_id, info in data.items():
        if not isinstance(info, dict):
            data[tg_id] = {
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
        if info.get("max_devices") is None:
            info["max_devices"] = DEFAULT_MAX_DEVICES
            changed = True
        if info.get("limit_gb") is None:
            info["limit_gb"] = DEFAULT_LIMIT_GB
            changed = True
        if info.get("expiry_time_ms") is None:
            info["expiry_time_ms"] = DEFAULT_EXPIRY_TIME_MS
            changed = True
        if info.get("limit_ip") is None:
            info["limit_ip"] = DEFAULT_LIMIT_IP
            changed = True
        if info.get("flow") in (None, ""):
            info["flow"] = DEFAULT_FLOW
            changed = True
        if not info.get("settings_ready"):
            info["settings_ready"] = True
            changed = True
        if not info.get("has_vpn_access"):
            info["has_vpn_access"] = True
            changed = True
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
    if changed:
        save_vpn_users(data)
    return data


def save_vpn_users(data: dict) -> None:
    _write_json(VPN_USERS_FILE, data)


def get_vpn_user(tg_id: int) -> dict | None:
    return load_vpn_users().get(str(tg_id))


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


def resolve_user_key_by_email(email: str) -> str | None:
    data = load_vpn_users()
    email = str(email or "")
    best_key = None
    for user_key, info in data.items():
        if str(user_key).startswith("paid_") or str(info.get("subscription_type", "")).lower() == "paid":
            continue
        key = str(user_key)
        if not key:
            continue
        if email == key or email.startswith(f"{key}_"):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    return best_key


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w-]+", "_", (text or "").strip().lower(), flags=re.UNICODE)
    return slug.strip("_") or "user"


def _anon_user_key(label: str) -> str:
    return f"anon_{_slugify(label)}"


def ensure_anon_user_for_client(ib_id: int, uuid: str, email: str, limit_ip: int | None = None) -> str:
    existing_key = get_user_key_by_client(ib_id, email)
    if existing_key:
        return existing_key
    key = _anon_user_key(email)
    add_device_to_user_key(key, ib_id, uuid, email, limit_ip=limit_ip, label=email)
    return key


def _add_device_to_user_key(user_key: str, ib_id: int, uuid: str, email: str, limit_ip: int | None = None, label: str = ""):
    data = load_vpn_users()
    key = str(user_key)
    if key not in data:
        data[key] = {
            "subscription_type": "admin",
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
        key = str(tg_id)
        if key in data:
            data[key]["max_devices"] = max_devices
            if note:
                data[key]["note"] = note[:NOTE_MAX_LEN]
            data[key]["limit_gb"] = data[key].get("limit_gb", DEFAULT_LIMIT_GB)
            data[key]["expiry_time_ms"] = data[key].get("expiry_time_ms", DEFAULT_EXPIRY_TIME_MS)
            data[key]["limit_ip"] = data[key].get("limit_ip", DEFAULT_LIMIT_IP)
            data[key]["flow"] = data[key].get("flow", DEFAULT_FLOW)
            data[key]["settings_ready"] = True
            data[key]["has_vpn_access"] = True
            save_vpn_users(data)
            return key
    else:
        key = _anon_user_key(note or "user")
    data[key] = {
        "subscription_type": "admin",
        "username": "",
        "default_ib_id": 0,
        "note": note[:NOTE_MAX_LEN],
        "max_devices": max_devices,
        "limit_gb": DEFAULT_LIMIT_GB,
        "expiry_time_ms": DEFAULT_EXPIRY_TIME_MS,
        "limit_ip": DEFAULT_LIMIT_IP,
        "settings_ready": False,
        "admin_disabled": False,
        "has_vpn_access": False,
        "devices": [],
        "flow": DEFAULT_FLOW,
    }
    data[key]["settings_ready"] = True
    data[key]["has_vpn_access"] = True
    save_vpn_users(data)
    return key


def create_user_with_inbound(tg_id: int | None, ib_id: int, note: str = "", subscription_type: str = "admin") -> str:
    data = load_vpn_users()
    if tg_id is None:
        key = _anon_user_key(note or f"inbound_{ib_id}")
    else:
        key = str(tg_id)
    if key not in data:
        data[key] = {
            "subscription_type": subscription_type,
            "username": "",
            "default_ib_id": int(ib_id or 0),
            "note": note[:NOTE_MAX_LEN],
            "max_devices": DEFAULT_MAX_DEVICES,
            "limit_gb": DEFAULT_LIMIT_GB,
            "expiry_time_ms": DEFAULT_EXPIRY_TIME_MS,
            "limit_ip": DEFAULT_LIMIT_IP,
            "flow": DEFAULT_FLOW,
            "settings_ready": True,
            "admin_disabled": False,
            "has_vpn_access": True,
            "devices": [],
        }
    else:
        data[key]["default_ib_id"] = int(ib_id or 0)
        data[key]["subscription_type"] = subscription_type
        if note:
            data[key]["note"] = note[:NOTE_MAX_LEN]
        data[key].setdefault("max_devices", DEFAULT_MAX_DEVICES)
        data[key].setdefault("limit_gb", DEFAULT_LIMIT_GB)
        data[key].setdefault("expiry_time_ms", DEFAULT_EXPIRY_TIME_MS)
        data[key].setdefault("limit_ip", DEFAULT_LIMIT_IP)
        data[key].setdefault("flow", DEFAULT_FLOW)
        data[key]["settings_ready"] = True
        data[key]["has_vpn_access"] = True
    save_vpn_users(data)
    return key


def _set_user_field(user_key: str, field: str, value) -> None:
    data = load_vpn_users()
    key = str(user_key)
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
    key = str(tg_id)
    if key in data:
        data[key]["has_vpn_access"] = bool(value)
        save_vpn_users(data)


def set_user_vpn_access_key(user_key: str, value: bool = True):
    data = load_vpn_users()
    key = str(user_key)
    if key in data:
        data[key]["has_vpn_access"] = bool(value)
        save_vpn_users(data)


def set_user_subscription_type(user_key: str | int, subscription_type: str) -> None:
    data = load_vpn_users()
    key = str(user_key)
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
    key = str(user_key)
    if key in data:
        data[key]["admin_disabled"] = bool(value)
        save_vpn_users(data)


def set_user_note_key(user_key: str, note: str):
    data = load_vpn_users()
    key = str(user_key)
    if key in data:
        data[key]["note"] = note[:NOTE_MAX_LEN]
        save_vpn_users(data)


def rekey_user(old_key: str, new_key: str) -> bool:
    data = load_vpn_users()
    old_key = str(old_key)
    new_key = str(new_key)
    if old_key not in data:
        return False
    if old_key.startswith("anon_") and new_key.isdigit():
        suffix = old_key[len("anon_"):].strip("_")
        if suffix:
            new_key = f"{new_key}_{suffix}"
    payload = data.pop(old_key)
    def _rename_device_email(email: str) -> str:
        email = str(email or "")
        if email == old_key:
            return new_key
        if email.startswith(f"{old_key}_"):
            return new_key + email[len(old_key):]
        if old_key.startswith("anon_") and email.startswith("anon_") and new_key.isdigit():
            suffix = email[len("anon_"):].lstrip("_")
            return f"{new_key}_{suffix}" if suffix else new_key
        return email
    payload["devices"] = [
        {**device, "email": _rename_device_email(device.get("email", ""))}
        for device in payload.get("devices", [])
    ]
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
    user = data.pop(user_key, None)
    save_vpn_users(data)
    return user


def set_admin_disabled(tg_id: int, value: bool):
    data = load_vpn_users()
    if str(tg_id) in data:
        data[str(tg_id)]["admin_disabled"] = value
        save_vpn_users(data)


def set_user_note(tg_id: int, note: str):
    data = load_vpn_users()
    if str(tg_id) in data:
        data[str(tg_id)]["note"] = note[:NOTE_MAX_LEN]
        save_vpn_users(data)


def get_user_note(user_key: str) -> str:
    data = load_vpn_users()
    return str(data.get(str(user_key), {}).get("note", ""))


def set_user_username(tg_id: int, username: str):
    data = load_vpn_users()
    if str(tg_id) in data:
        data[str(tg_id)]["username"] = username or ""
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
    return _read_json(CLIENT_NOTES_FILE, {}) if CLIENT_NOTES_FILE.exists() else {}


def save_client_notes(data: dict):
    _write_json(CLIENT_NOTES_FILE, data)


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
