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


def build_email(tg_id: int, username: str | None) -> str:
    suffix = username.lower() if username else "nousername"
    raw = f"{tg_id}_{suffix}"
    # оставляем только допустимые символы для email-поля 3x-UI
    return "".join(c for c in raw if c.isalnum() or c in ("_", "-", "."))[:50]


def date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    return int(dt.timestamp() * 1000)


def gb_to_bytes(gb: float) -> int:
    return int(gb * 1024 ** 3)


def _build_sub_url(scheme: str, hostname: str, port, sub_path: str, sub_id: str) -> str:
    try:
        p = int(port)
    except (ValueError, TypeError):
        p = 0
    skip_port = (scheme == "https" and p == 443) or (scheme == "http" and p == 80)
    if skip_port or p == 0:
        return f"{scheme}://{hostname}{sub_path}{sub_id}"
    return f"{scheme}://{hostname}:{p}{sub_path}{sub_id}"


def strip_default_port(sub_url: str) -> str:
    """Убирает :443 / :80 из готовой ссылки если они дефолтные для схемы."""
    import re
    sub_url = re.sub(r'^(https://[^/:]+):443(/)', r'\1\2', sub_url)
    sub_url = re.sub(r'^(http://[^/:]+):80(/)', r'\1\2', sub_url)
    return sub_url


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


async def get_inbounds() -> dict:
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        data, err = await _get(s, f"{url}/panel/api/inbounds/list")
        if data is None:
            return {"success": False, "error": err}
        if not data.get("success"):
            return {"success": False, "error": str(data)}
        return {"success": True, "inbounds": data.get("obj") or []}
    finally:
        await s.close()


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


async def get_client_traffic(email: str) -> dict:
    """Получает трафик клиента из панели. Возвращает {up, down} в байтах."""
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        safe_email = quote(email, safe="")
        data, err = await _get(s, f"{url}/panel/api/clients/get/{safe_email}")
        if data and data.get("success"):
            obj = data.get("obj") or {}
            if isinstance(obj, dict):
                client = obj.get("client") or obj
            else:
                client = obj
            if isinstance(client, dict):
                return {"success": True, "up": client.get("up", 0), "down": client.get("down", 0)}
        # фолбэк: ищем в инбаундах
        data2, err2 = await _get(s, f"{url}/panel/api/inbounds/list")
        if data2 and data2.get("success"):
            for inb in (data2.get("obj") or []):
                clients_str = (inb.get("settings") or "")
                try:
                    settings = json.loads(clients_str) if isinstance(clients_str, str) else clients_str
                    for c in settings.get("clients", []):
                        if c.get("email") == email:
                            stats = inb.get("clientStats") or []
                            for st in stats:
                                if st.get("email") == email:
                                    return {"success": True, "up": st.get("up", 0), "down": st.get("down", 0)}
                except Exception:
                    pass
        return {"success": False, "error": "Клиент не найден"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()


async def update_client_email(old_email: str, new_email: str, client_uuid: str,
                               sub_id: str, expire_date: str,
                               limit_ip: int, limit_hwid: int, total_gb: int) -> dict:
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        expire_ms = date_to_ms(expire_date)
        payload = {
            "id": client_uuid,
            "email": new_email,
            "subId": sub_id,
            "flow": "xtls-rprx-vision",
            "limitIp": limit_ip,
            "limitHwId": limit_hwid,
            "totalGB": gb_to_bytes(total_gb) if total_gb > 0 else 0,
            "expiryTime": expire_ms,
            "enable": True,
            "tgId": 0,
            "reset": 0,
        }
        # Пробуем разные эндпоинты (зависит от версии 3x-UI)
        safe_old = quote(old_email, safe="")
        safe_uuid = quote(client_uuid, safe="")
        paths = [
            f"/panel/api/clients/update/{safe_uuid}",
            f"/panel/api/clients/update/{safe_old}",
            f"/panel/api/inbounds/updateClient/{safe_uuid}",
        ]
        last_err = ""
        for path in paths:
            data, err = await _post(s, f"{url}{path}", payload)
            if data and data.get("success"):
                return {"success": True}
            last_err = err or str(data)
        return {"success": False, "error": f"Все варианты API не сработали: {last_err}"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()


async def delete_client(email: str) -> dict:
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        safe_email = quote(email, safe="")
        data, err = await _post(s, f"{url}/panel/api/clients/del/{safe_email}", {})
        if data and data.get("success"):
            return {"success": True}
        # фолбэк: удалить из каждого инбаунда
        inbounds_result = await get_inbounds()
        if inbounds_result["success"]:
            for inb in inbounds_result["inbounds"]:
                ib_id = inb.get("id")
                await _post(s, f"{url}/panel/api/inbounds/delClient/{ib_id}/{safe_email}", {})
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()


async def create_client(
    expire_date: str,
    limit_ip: int,
    limit_hwid: int,
    total_gb: int,
    email: str | None = None,
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
        preset_inbound_ids = cfg.get("preset_inbound_ids") or []
        if preset_inbound_ids:
            inbound_ids = [int(i) for i in preset_inbound_ids]
            inbound_id = inbound_ids[0]
        else:
            inbound_id, ierr = await _fetch_inbound_id(s, url)
            if not inbound_id:
                return {"success": False, "error": f"Не найден инбаунд: {ierr}"}
            inbound_ids = [int(inbound_id)]

        expire_ms = date_to_ms(expire_date)
        client_uuid = str(uuid.uuid4())
        sub_id = generate_sub_id()
        email = email or generate_email()

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

        payload = {"inboundIds": inbound_ids, "client": client}
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
        sub_url = _build_sub_url(parsed.scheme, parsed.hostname, sub_port, sub_path, sub_id)
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
