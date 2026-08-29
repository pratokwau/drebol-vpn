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


def build_email(tg_id: int, username=None, prefix: str = "") -> str:
    suffix = username.strip().lower() if username else "nousername"
    raw = f"{prefix}{tg_id}_{suffix}"
    return "".join(c for c in raw if c.isalnum() or c in ("_", "-", "."))[:50]


def date_to_ms(date_str: str) -> int:
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


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


async def get_client_info(email: str) -> dict:
    """Получает enable-статус клиента из панели."""
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False}
    s = _session(token)
    try:
        data, _ = await _get(s, f"{url}/panel/api/inbounds/list")
        if data and data.get("success"):
            for inb in (data.get("obj") or []):
                settings_str = inb.get("settings") or "{}"
                try:
                    settings = json.loads(settings_str) if isinstance(settings_str, str) else settings_str
                except Exception:
                    continue
                for c in settings.get("clients", []):
                    if c.get("email") == email:
                        return {"success": True, "enabled": c.get("enable", True), "uuid": c.get("id", ""), "inbound_id": inb.get("id")}
        return {"success": False}
    finally:
        await s.close()


async def toggle_client(email: str, enable: bool) -> dict:
    """Включает/выключает клиента в панели."""
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        info = await get_client_info.__wrapped__(s, url, email) if False else None
        # получаем данные клиента из инбаундов
        data, _ = await _get(s, f"{url}/panel/api/inbounds/list")
        if not data or not data.get("success"):
            return {"success": False, "error": "Не удалось загрузить инбаунды"}
        client_obj = None
        inbound_id = None
        for inb in (data.get("obj") or []):
            settings_str = inb.get("settings") or "{}"
            try:
                settings = json.loads(settings_str) if isinstance(settings_str, str) else settings_str
            except Exception:
                continue
            for c in settings.get("clients", []):
                if c.get("email") == email:
                    client_obj = c
                    inbound_id = inb.get("id")
                    break
            if client_obj:
                break
        if not client_obj:
            return {"success": False, "error": "Клиент не найден в панели"}

        client_obj["enable"] = enable
        client_obj["flow"] = "xtls-rprx-vision"
        safe_uuid = quote(client_obj.get("id", ""), safe="")
        safe_email = quote(email, safe="")

        for path in (
            f"/panel/api/clients/update/{safe_uuid}",
            f"/panel/api/clients/update/{safe_email}",
            f"/panel/api/inbounds/updateClient/{safe_uuid}",
        ):
            result, err = await _post(s, f"{url}{path}", client_obj)
            if result and result.get("success"):
                return {"success": True}
        return {"success": False, "error": f"API не принял обновление: {err}"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()


async def get_client_traffic(email: str) -> dict:
    """Получает трафик клиента из панели. Возвращает {up, down} в байтах."""
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        # clientStats лежат внутри инбаундов
        data, err = await _get(s, f"{url}/panel/api/inbounds/list")
        if data and data.get("success"):
            for inb in (data.get("obj") or []):
                stats = inb.get("clientStats") or []
                for st in stats:
                    if st.get("email") == email:
                        return {"success": True, "up": st.get("up", 0), "down": st.get("down", 0)}

        # отдельный эндпоинт (некоторые версии)
        safe_email = quote(email, safe="")
        for path in (
            f"/panel/api/clients/get/{safe_email}",
            f"/panel/api/inbounds/getClientTraffics/{safe_email}",
        ):
            data2, _ = await _get(s, f"{url}{path}")
            if data2 and data2.get("success"):
                obj = data2.get("obj")
                if isinstance(obj, dict):
                    up = obj.get("up", 0)
                    down = obj.get("down", 0)
                    if up or down:
                        return {"success": True, "up": up, "down": down}
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict) and item.get("email") == email:
                            return {"success": True, "up": item.get("up", 0), "down": item.get("down", 0)}

        return {"success": True, "up": 0, "down": 0}
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


async def update_client_expire(email: str, new_expire_str: str) -> dict:
    """Обновляет expiryTime клиента в панели 3x-UI."""
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        data, err = await _get(s, f"{url}/panel/api/inbounds/list")
        if not data or not data.get("success"):
            return {"success": False, "error": f"Не удалось загрузить инбаунды: {err}"}

        client_obj = None
        for inb in (data.get("obj") or []):
            settings_str = inb.get("settings") or "{}"
            try:
                settings = json.loads(settings_str) if isinstance(settings_str, str) else settings_str
            except Exception:
                continue
            for c in settings.get("clients", []):
                if c.get("email") == email:
                    client_obj = dict(c)
                    break
            if client_obj:
                break

        if not client_obj:
            return {"success": False, "error": "Клиент не найден в панели"}

        new_expire_ms = date_to_ms(new_expire_str)
        client_obj["expiryTime"] = new_expire_ms
        client_obj["flow"] = "xtls-rprx-vision"

        safe_uuid = quote(client_obj.get("id", ""), safe="")
        safe_email = quote(email, safe="")
        for path in (
            f"/panel/api/clients/update/{safe_uuid}",
            f"/panel/api/clients/update/{safe_email}",
            f"/panel/api/inbounds/updateClient/{safe_uuid}",
        ):
            result, err2 = await _post(s, f"{url}{path}", client_obj)
            if result and result.get("success"):
                return {"success": True}
        return {"success": False, "error": f"API не принял обновление: {err2}"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()


async def move_client_inbound(email: str, target_inbound_ids: list) -> dict:
    """Перемещает клиента из текущего инбаунда в целевые инбаунды."""
    cfg = load_config()
    url = cfg.get("xui_url", "").rstrip("/")
    token = cfg.get("xui_token", "")
    if not url or not token:
        return {"success": False, "error": "URL или токен не заданы"}
    s = _session(token)
    try:
        data, err = await _get(s, f"{url}/panel/api/inbounds/list")
        if not data or not data.get("success"):
            return {"success": False, "error": f"Не удалось загрузить инбаунды: {err}"}

        client_obj = None
        old_inbound_id = None
        for inb in (data.get("obj") or []):
            settings_str = inb.get("settings") or "{}"
            try:
                settings = json.loads(settings_str) if isinstance(settings_str, str) else settings_str
            except Exception:
                continue
            for c in settings.get("clients", []):
                if c.get("email") == email:
                    client_obj = dict(c)
                    old_inbound_id = inb.get("id")
                    break
            if client_obj:
                break

        if not client_obj:
            return {"success": False, "error": "Клиент не найден в панели"}

        client_obj["flow"] = "xtls-rprx-vision"
        real_ids = {inb.get("id") for inb in (data.get("obj") or [])}
        valid_targets = [int(i) for i in target_inbound_ids if int(i) in real_ids]
        if not valid_targets:
            return {"success": False, "error": "Целевые инбаунды не найдены"}

        if old_inbound_id in valid_targets:
            return {"success": True, "moved": False}

        safe_email = quote(email, safe="")
        safe_uuid = quote(client_obj.get("id", ""), safe="")

        # Удаляем из старого инбаунда
        for path in (
            f"/panel/api/clients/del/{safe_email}",
            f"/panel/api/inbounds/{old_inbound_id}/delClient/{safe_email}",
        ):
            await _post(s, f"{url}{path}", {})

        # Добавляем в новые инбаунды
        payload_new = {"inboundIds": valid_targets, "client": client_obj}
        result, err2 = await _post(s, f"{url}/panel/api/clients/add", payload_new)
        if result and result.get("success"):
            return {"success": True, "moved": True}

        # Фолбэк: добавляем в первый целевой
        target_id = valid_targets[0]
        old_payload = {
            "id": target_id,
            "settings": json.dumps({"clients": [client_obj]}),
        }
        result2, err3 = await _post(s, f"{url}/panel/api/inbounds/{target_id}/addClient", old_payload)
        if result2 and result2.get("success"):
            return {"success": True, "moved": True}

        return {"success": False, "error": f"Не удалось добавить в новый инбаунд: {err3}"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()


async def create_client(
    expire_date: str,
    limit_ip: int,
    limit_hwid: int,
    total_gb: int,
    email=None,
    preset_inbound_ids_override=None,
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
        # Всегда загружаем актуальные инбаунды из панели
        real_data, real_err = await _get(s, f"{url}/panel/api/inbounds/list")
        if not real_data or not real_data.get("success"):
            return {"success": False, "error": f"Не удалось загрузить инбаунды: {real_err}"}
        real_inbounds = real_data.get("obj") or []
        real_ids = {inb.get("id") for inb in real_inbounds}

        if not real_ids:
            return {"success": False, "error": "На панели нет ни одного инбаунда"}

        preset_inbound_ids = preset_inbound_ids_override or cfg.get("preset_inbound_ids") or []
        if preset_inbound_ids:
            # Фильтруем — оставляем только реально существующие
            valid_ids = [int(i) for i in preset_inbound_ids if int(i) in real_ids]
            if not valid_ids:
                names = [f"{inb.get('tag') or inb.get('remark') or '?'} (id:{inb.get('id')})" for inb in real_inbounds]
                return {"success": False, "error": f"Выбранные инбаунды ({preset_inbound_ids}) не найдены в панели.\nДоступные: {', '.join(names)}\n\nПерейди в Настройки → Инбаунды и выбери заново."}
            inbound_ids = valid_ids
            inbound_id = inbound_ids[0]
        else:
            # Автодетект: первый VLESS, иначе первый любой
            inbound_id = None
            for inb in real_inbounds:
                if inb.get("protocol") == "vless":
                    inbound_id = inb.get("id")
                    break
            if not inbound_id:
                inbound_id = real_inbounds[0].get("id")
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
            "totalGB": gb_to_bytes(total_gb) if total_gb > 0 else 0,
            "expiryTime": expire_ms,
            "enable": True,
            "tgId": 0,
            "subId": sub_id,
            "reset": 0,
        }

        # Пробуем новый API
        payload = {"inboundIds": inbound_ids, "client": client}
        data, err = await _post(s, f"{url}/panel/api/clients/add", payload)

        if data and data.get("success"):
            pass  # OK
        else:
            err1 = err or str(data)
            # Фолбэк 1: /panel/api/inbounds/{id}/addClient
            old_payload = {
                "id": int(inbound_id),
                "settings": json.dumps({"clients": [client]}),
            }
            data2, err2 = await _post(s, f"{url}/panel/api/inbounds/{inbound_id}/addClient", old_payload)
            if data2 and data2.get("success"):
                data = data2
            else:
                err2 = err2 or str(data2)
                # Фолбэк 2: /panel/api/inbounds/addClient
                data3, err3 = await _post(s, f"{url}/panel/api/inbounds/addClient", old_payload)
                if data3 and data3.get("success"):
                    data = data3
                else:
                    err3 = err3 or str(data3)
                    return {"success": False, "error": f"1) clients/add: {err1}\n2) inbounds/{inbound_id}/addClient: {err2}\n3) inbounds/addClient: {err3}"}

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
