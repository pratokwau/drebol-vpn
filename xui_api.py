import uuid
import random
import string
from datetime import datetime
from urllib.parse import urlparse

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


def _connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(ssl=False)


async def _login(url: str, login: str, password: str) -> tuple[aiohttp.ClientSession | None, str]:
    """Возвращает (session, error). Если session None — error содержит подробности."""
    headers = {
        "Referer": url + "/",
        "Origin": url,
        "X-Requested-With": "XMLHttpRequest",
    }
    session = aiohttp.ClientSession(connector=_connector(), headers=headers)
    try:
        async with session.post(
            f"{url}/login",
            data={"username": login, "password": password},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            status = resp.status
            try:
                data = await resp.json(content_type=None)
            except Exception:
                body = await resp.text()
                await session.close()
                return None, f"HTTP {status}, ответ не JSON: {body[:300]}"
            if (data or {}).get("success"):
                return session, ""
            await session.close()
            return None, f"HTTP {status}, ответ: {data}"
    except aiohttp.ClientConnectorError as e:
        await session.close()
        return None, f"Не удалось подключиться: {e}"
    except aiohttp.ClientResponseError as e:
        await session.close()
        return None, f"Ошибка ответа: {e}"
    except Exception as e:
        await session.close()
        return None, f"{type(e).__name__}: {e}"


async def test_connection() -> dict:
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    login = cfg.get("xui_login", "")
    password = cfg.get("xui_password", "")
    if not all([url, login, password]):
        return {"success": False, "error": "URL / логин / пароль не заданы"}
    session, err = await _login(url, login, password)
    if not session:
        return {"success": False, "error": err, "url": url, "login": login}
    await session.close()
    return {"success": True}


async def _fetch_inbound_id(session: aiohttp.ClientSession, url: str) -> tuple[int | None, str]:
    """Найти первый подходящий VLESS-инбаунд. Возвращает (id, error)."""
    try:
        async with session.get(
            f"{url}/panel/api/inbounds/list",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            status = resp.status
            try:
                data = await resp.json(content_type=None)
            except Exception:
                body = await resp.text()
                return None, f"list HTTP {status}, ответ не JSON: {body[:300]}"

            if not (data or {}).get("success"):
                return None, f"list HTTP {status}: {data}"

            inbounds = data.get("obj", []) or []
            if not inbounds:
                return None, "На панели нет ни одного инбаунда"

            # ищем VLESS с XTLS
            for inb in inbounds:
                if inb.get("protocol") == "vless":
                    return inb.get("id"), ""
            return inbounds[0].get("id"), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def create_client(
    expire_date: str,
    limit_ip: int,
    limit_hwid: int,
    total_gb: int,
) -> dict:
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    login = cfg.get("xui_login", "")
    password = cfg.get("xui_password", "")
    sub_port = cfg.get("xui_sub_port", "")
    sub_path = cfg.get("xui_sub_path", "/sub/")

    missing = [k for k, v in [("URL", url), ("логин", login), ("пароль", password), ("порт подписки", sub_port)] if not v]
    if missing:
        return {"success": False, "error": f"Не заданы: {', '.join(missing)}. Открой «Параметры 3x-UI»."}

    session, err = await _login(url, login, password)
    if not session:
        return {"success": False, "error": f"Авторизация: {err}"}

    try:
        inbound_id = cfg.get("xui_inbound_id")
        if not inbound_id:
            inbound_id, ierr = await _fetch_inbound_id(session, url)
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
            "tgId": "",
            "subId": sub_id,
            "comment": "",
        }

        payload = {"inboundIds": [int(inbound_id)], "client": client}

        async with session.post(
            f"{url}/panel/api/clients/add",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            status = resp.status
            try:
                data = await resp.json(content_type=None)
            except Exception:
                body = await resp.text()
                return {"success": False, "error": f"clients/add HTTP {status}, ответ не JSON: {body[:400]}"}

        if not (data or {}).get("success"):
            # Фолбэк на старое API
            import json as _json
            old_body = {
                "id": int(inbound_id),
                "settings": _json.dumps({"clients": [client]}),
            }
            async with session.post(
                f"{url}/panel/api/inbounds/addClient",
                json=old_body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp2:
                status2 = resp2.status
                try:
                    data = await resp2.json(content_type=None)
                except Exception:
                    body = await resp2.text()
                    return {"success": False, "error": f"addClient HTTP {status2}: {body[:400]}"}

        if (data or {}).get("success"):
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
        return {"success": False, "error": f"API вернул: {data}"}

    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await session.close()
