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
    """'дд.мм.гггг' → Unix timestamp в миллисекундах."""
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    return int(dt.timestamp() * 1000)


def gb_to_bytes(gb: float) -> int:
    return int(gb * 1024 ** 3)


def _connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(ssl=False)


async def _login(url: str, login: str, password: str) -> aiohttp.ClientSession | None:
    session = aiohttp.ClientSession(connector=_connector())
    try:
        async with session.post(
            f"{url}/login",
            json={"username": login, "password": password},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json(content_type=None)
            if data.get("success"):
                return session
    except Exception:
        pass
    await session.close()
    return None


async def test_connection() -> dict:
    """Проверить соединение с панелью."""
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    login = cfg.get("xui_login", "")
    password = cfg.get("xui_password", "")
    if not all([url, login, password]):
        return {"success": False, "error": "Параметры панели не заданы"}
    session = await _login(url, login, password)
    if not session:
        return {"success": False, "error": "Неверный логин/пароль или панель недоступна"}
    await session.close()
    return {"success": True}


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
    inbound_id = int(cfg.get("xui_inbound_id", 1))
    sub_port = cfg.get("xui_sub_port", "")
    sub_path = cfg.get("xui_sub_path", "/sub/")

    if not all([url, login, password, sub_port]):
        return {"success": False, "error": "Настройте параметры 3x-UI в админке"}

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

    session = await _login(url, login, password)
    if not session:
        return {"success": False, "error": "Ошибка авторизации на панели"}

    try:
        # Новый API: /panel/api/clients/add
        async with session.post(
            f"{url}/panel/api/clients/add",
            json={"inboundIds": [inbound_id], "client": client},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json(content_type=None)

        if not data.get("success"):
            # Фолбэк на старый API: /panel/api/inbounds/addClient
            import json as _json
            old_body = {
                "id": inbound_id,
                "settings": _json.dumps({"clients": [client]}),
            }
            async with session.post(
                f"{url}/panel/api/inbounds/addClient",
                json=old_body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp2:
                data = await resp2.json(content_type=None)

        if data.get("success"):
            parsed = urlparse(url)
            sub_url = f"{parsed.scheme}://{parsed.hostname}:{sub_port}{sub_path}{sub_id}"
            return {
                "success": True,
                "sub_url": sub_url,
                "uuid": client_uuid,
                "email": email,
                "sub_id": sub_id,
                "expire": expire_date,
            }
        return {"success": False, "error": data.get("msg", "Ошибка API панели")}

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await session.close()
