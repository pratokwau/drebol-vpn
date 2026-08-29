import uuid
import json
import random
import string
from datetime import datetime
from urllib.parse import urlparse, quote

import aiohttp

from config import load_config


def generate_sub_id(length: int = 16) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def generate_email(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    return int(dt.timestamp() * 1000)


def gb_to_bytes(gb: float) -> int:
    return int(gb * 1024 ** 3)


def _session(token: str) -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(ssl=False)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return aiohttp.ClientSession(connector=connector, headers=headers)


async def _get(session: aiohttp.ClientSession, url: str) -> tuple[dict | None, str]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            text = await resp.text()
            if not text.strip() or text.strip() == "null":
                return None, f"HTTP {resp.status}: пустой ответ"
            try:
                data = json.loads(text)
            except Exception:
                return None, f"HTTP {resp.status}: не JSON: {text[:200]}"
            return data, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def _post(session: aiohttp.ClientSession, url: str, body: dict) -> tuple[dict | None, str]:
    try:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            text = await resp.text()
            if not text.strip() or text.strip() == "null":
                return None, f"HTTP {resp.status}: пустой ответ"
            try:
                data = json.loads(text)
            except Exception:
                return None, f"HTTP {resp.status}: не JSON: {text[:200]}"
            return data, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def test_connection() -> dict:
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы. Открой «Параметры 3x-UI»."}

    s = _session(token)
    try:
        data, err = await _get(s, f"{url}/panel/api/inbounds/list")
        if data is None:
            return {"success": False, "error": err, "url": url}
        if not data.get("success"):
            return {"success": False, "error": f"Панель ответила: {data}", "url": url}
        inbounds = data.get("obj") or []
        return {"success": True, "inbounds": len(inbounds)}
    finally:
        await s.close()


async def _fetch_inbound_id(session: aiohttp.ClientSession, url: str) -> tuple[int | None, str]:
    data, err = await _get(session, f"{url}/panel/api/inbounds/list")
    if data is None:
        return None, err
    if not data.get("success"):
        return None, f"inbounds/list: {data}"
    inbounds = data.get("obj") or []
    if not inbounds:
        return None, "На панели нет ни одного инбаунда"
    for inb in inbounds:
        if inb.get("protocol") == "vless":
            return inb.get("id"), ""
    return inbounds[0].get("id"), ""


async def create_client(
    expire_date: str,
    limit_ip: int,
    limit_hwid: int,
    total_gb: int,
) -> dict:
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    sub_port = cfg.get("xui_sub_port", "")
    sub_path = cfg.get("xui_sub_path", "/sub/")

    missing = [k for k, v in [("URL", url), ("токен", token), ("порт подписки", sub_port)] if not v]
    if missing:
        return {"success": False, "error": f"Не заданы: {', '.join(missing)}. Открой «Параметры 3x-UI»."}

    s = _session(token)
    try:
        inbound_id, ierr = await _fetch_inbound_id(s, url)
        if not inbound_id:
            return {"success": False, "error": f"Не найден инбаунд: {ierr}"}

        expire_ms = date_to_ms(expire_date)
        client_uuid = str(uuid.uuid4())
        sub_id = generate_sub_id()
        email = generate_email()

        client = {
            "id": client_uuid,
            "email": email,
            "flow": "xtls-rprx-vision",
            "limitIp": limit_ip,
            "limitHwId": limit_hwid,
            "totalGB": gb_to_bytes(total_gb) if total_gb > 0 else 0,
            "expiryTime": expire_ms,
            "enable": True,
            "tgId": 0,
            "subId": sub_id,
            "reset": 0,
        }

        payload = {"inboundIds": [int(inbound_id)], "client": client}
        data, err = await _post(s, f"{url}/panel/api/clients/add", payload)

        if data is None or not data.get("success"):
            # Фолбэк на старое API
            old_payload = {
                "id": int(inbound_id),
                "settings": json.dumps({"clients": [client]}),
            }
            data2, err2 = await _post(s, f"{url}/panel/api/inbounds/addClient", old_payload)
            if data2 is None:
                return {"success": False, "error": f"clients/add: {err}\naddClient: {err2}"}
            if not data2.get("success"):
                return {"success": False, "error": f"clients/add: {data}\naddClient: {data2}"}
            data = data2

        parsed = urlparse(url)
        sub_url = f"{parsed.scheme}://{parsed.hostname}:{sub_port}{sub_path}{sub_id}"
        return {
            "success": True,
            "sub_url": sub_url,
            "uuid": client_uuid,
            "email": email,
            "sub_id": sub_id,
            "expire": expire_date,
            "inbound_id": inbound_id,
        }

    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()
