from __future__ import annotations

import json
import secrets
from pathlib import Path

VPN_USERS_FILE = Path("data/vpn_users.json")
CLIENT_NOTES_FILE = Path("data/client_notes.json")
NOTE_MAX_LEN = 50
DEFAULT_MAX_DEVICES = 1


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
    return _migrate_vpn_users(raw)


def _migrate_vpn_users(data: dict) -> dict:
    changed = False
    for tg_id, info in data.items():
        if not isinstance(info, dict):
            data[tg_id] = {
                "username": "",
                "note": "",
                "max_devices": DEFAULT_MAX_DEVICES,
                "admin_disabled": False,
                "devices": [],
            }
            changed = True
            continue
        info.setdefault("username", "")
        info.setdefault("note", "")
        info.setdefault("max_devices", DEFAULT_MAX_DEVICES)
        info.setdefault("admin_disabled", False)
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


def add_device_to_user(tg_id: int, ib_id: int, uuid: str, email: str):
    data = load_vpn_users()
    key = str(tg_id)
    if key not in data:
        data[key] = {
            "username": "",
            "note": "",
            "max_devices": DEFAULT_MAX_DEVICES,
            "admin_disabled": False,
            "devices": [],
        }
    for d in data[key]["devices"]:
        if d.get("ib_id") == ib_id and d.get("email") == email:
            d["uuid"] = uuid
            save_vpn_users(data)
            return
    data[key]["devices"].append({"ib_id": ib_id, "uuid": uuid, "email": email})
    save_vpn_users(data)


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
            save_vpn_users(data)
            return key
    else:
        key = f"anon_{secrets.token_hex(4)}"
    data[key] = {
        "username": "",
        "note": note[:NOTE_MAX_LEN],
        "max_devices": max_devices,
        "admin_disabled": False,
        "devices": [],
    }
    save_vpn_users(data)
    return key


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
