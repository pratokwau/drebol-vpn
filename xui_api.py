import asyncio
import time
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


async def count_panel_clients() -> dict:
    """Считает уникальных клиентов в панели.

    Клиент может лежать сразу в нескольких инбаундах (переносы при продлении
    и истечении), поэтому считаем по уникальному email, иначе цифра задваивается.
    """
    result = await get_inbounds()
    if not result.get("success"):
        return {"success": False, "error": result.get("error", "?")}

    import json
    seen: set[str] = set()
    paid = 0
    for inb in result["inbounds"]:
        try:
            settings = json.loads(inb.get("settings") or "{}")
            clients = settings.get("clients") or []
        except Exception:
            clients = []
        for c in clients:
            email = (c.get("email") or "").strip()
            if not email or email in seen:
                continue
            seen.add(email)
            if email.startswith("paid_"):
                paid += 1
    total = len(seen)
    return {"success": True, "total": total, "paid": paid, "other": total - paid}


async def check_tcp(host: str, port, timeout: float = 4.0) -> dict:
    """Реально ли порт принимает соединения (а не что о нём написано в конфиге)."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"ok": False, "error": "некорректный порт"}
    if not host or not (0 < port < 65536):
        return {"ok": False, "error": "нет адреса"}

    start = time.monotonic()
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        return {"ok": True, "ms": int((time.monotonic() - start) * 1000)}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "таймаут"}
    except ConnectionRefusedError:
        return {"ok": False, "error": "порт закрыт"}
    except OSError as e:
        return {"ok": False, "error": (e.strerror or str(e))[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:50]}
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass


async def check_sub_service(timeout: float = 6.0) -> dict:
    """Проверяет сервис подписок — тот самый адрес, по которому ходят клиенты.

    Панель и подписки в 3x-UI слушают разные порты и падают независимо:
    панель может отвечать, пока выдача подписок лежит. Именно этот случай
    прежняя проверка не видела.
    """
    cfg = load_config()
    url = (cfg.get("xui_url") or "").rstrip("/")
    if not url:
        return {"ok": False, "error": "URL панели не задан", "url": ""}

    parsed = urlparse(url)
    host = parsed.hostname
    scheme = parsed.scheme or "https"
    sub_port = cfg.get("xui_sub_port") or (443 if scheme == "https" else 80)
    sub_path = cfg.get("xui_sub_path", "/sub/")

    try:
        port_int = int(sub_port)
    except (TypeError, ValueError):
        port_int = 443 if scheme == "https" else 80

    skip_port = (scheme == "https" and port_int == 443) or (scheme == "http" and port_int == 80)
    base = f"{scheme}://{host}{'' if skip_port else f':{port_int}'}{sub_path}"

    tcp = await check_tcp(host, port_int, timeout=4.0)
    if not tcp["ok"]:
        return {"ok": False, "error": tcp["error"], "url": base, "port": port_int}

    start = time.monotonic()
    conn = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(
            connector=conn, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as s:
            async with s.get(base, allow_redirects=False) as r:
                # даже 404 означает, что сервис жив и отвечает —
                # важно отличать «нет ответа» от «ответил кодом»
                return {
                    "ok": True,
                    "status": r.status,
                    "ms": int((time.monotonic() - start) * 1000),
                    "url": base,
                    "port": port_int,
                }
    except asyncio.TimeoutError:
        return {"ok": False, "error": "таймаут HTTP", "url": base, "port": port_int}
    except Exception as e:
        return {"ok": False, "error": str(e)[:60], "url": base, "port": port_int}


def node_prefix(tag: str) -> str:
    """Префикс из имени инбаунда: у «n3-in-14034-tcp» это «n3».

    Инбаунды одного узла принято называть с общим префиксом, поэтому
    привязка идёт по нему — новый инбаунд на том же узле подхватится сам.
    """
    tag = (tag or "").strip()
    return tag.split("-")[0] if "-" in tag else tag


def resolve_inbound_host(inb: dict, panel_host: str | None) -> tuple[str | None, bool]:
    """Куда стучаться, чтобы проверить инбаунд.

    Возвращает (хост, привязан_явно). Порядок: поле listen самого инбаунда →
    адрес узла по префиксу имени → адрес панели.
    """
    listen = (inb.get("listen") or "").strip()
    if listen and listen not in ("0.0.0.0", "::"):
        return listen, True

    nodes = load_config().get("node_hosts") or {}
    prefix = node_prefix(inb.get("tag") or inb.get("remark") or "")
    if prefix and nodes.get(prefix):
        return nodes[prefix], True

    return panel_host, False


def _inbound_clients(inb: dict) -> int:
    cs = inb.get("clientStats")
    if isinstance(cs, list):
        return len(cs)
    try:
        return len(json.loads(inb.get("settings") or "{}").get("clients") or [])
    except Exception:
        return 0


async def probe_servers() -> dict:
    """Полная проверка: панель, сервис подписок и реальная доступность портов."""
    cfg = load_config()
    url = (cfg.get("xui_url") or "").rstrip("/")
    host = urlparse(url).hostname if url else None

    start = time.monotonic()
    inb_result = await get_inbounds()
    panel = {
        "ok": bool(inb_result.get("success")),
        "ms": int((time.monotonic() - start) * 1000),
        "error": inb_result.get("error"),
        "host": host,
    }

    sub = await check_sub_service()

    inbounds = []
    if panel["ok"]:
        raw = inb_result.get("inbounds") or []
        hosts = [resolve_inbound_host(inb, host) for inb in raw]
        # порты проверяем параллельно, иначе на десятке инбаундов экран висит
        checks = await asyncio.gather(*[
            check_tcp(h, inb.get("port")) for inb, (h, _m) in zip(raw, hosts)
        ], return_exceptions=True)

        for inb, (inb_host, mapped), chk in zip(raw, hosts, checks):
            if isinstance(chk, Exception):
                chk = {"ok": False, "error": str(chk)[:50]}
            tag = inb.get("tag") or inb.get("remark") or f"#{inb.get('id')}"
            inbounds.append({
                "tag": tag,
                "prefix": node_prefix(tag),
                "host": inb_host,
                "mapped": mapped,
                "protocol": inb.get("protocol", "?"),
                "port": inb.get("port"),
                "enabled": inb.get("enable", True),
                "clients": _inbound_clients(inb),
                "reachable": chk.get("ok", False),
                "ms": chk.get("ms"),
                "error": chk.get("error"),
            })

    return {"panel": panel, "sub": sub, "inbounds": inbounds}


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


async def reissue_client_uuid(email: str) -> dict:
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
        old_uuid = None
        for inb in (data.get("obj") or []):
            settings_str = inb.get("settings") or "{}"
            try:
                settings = json.loads(settings_str) if isinstance(settings_str, str) else settings_str
            except Exception:
                continue
            for c in settings.get("clients", []):
                if c.get("email") == email:
                    client_obj = dict(c)
                    old_uuid = c.get("id", "")
                    break
            if client_obj:
                break
        if not client_obj:
            return {"success": False, "error": "Клиент не найден в панели"}
        new_uuid = str(uuid.uuid4())
        client_obj["id"] = new_uuid
        client_obj["flow"] = "xtls-rprx-vision"
        safe_old = quote(old_uuid, safe="")
        safe_email = quote(email, safe="")
        for path in (
            f"/panel/api/clients/update/{safe_old}",
            f"/panel/api/clients/update/{safe_email}",
            f"/panel/api/inbounds/updateClient/{safe_old}",
        ):
            result, err2 = await _post(s, f"{url}{path}", client_obj)
            if result and result.get("success"):
                return {"success": True, "new_uuid": new_uuid}
        return {"success": False, "error": f"API не принял обновление: {err2}"}
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

        # Клиент может лежать сразу в нескольких инбаундах — собираем все,
        # иначе чистка затронет только первый найденный и останутся хвосты
        client_obj = None
        current_ids = set()
        for inb in (data.get("obj") or []):
            settings_str = inb.get("settings") or "{}"
            try:
                settings = json.loads(settings_str) if isinstance(settings_str, str) else settings_str
            except Exception:
                continue
            for c in settings.get("clients", []):
                if c.get("email") == email:
                    if client_obj is None:
                        client_obj = dict(c)
                    current_ids.add(inb.get("id"))
                    break

        if not client_obj:
            return {"success": False, "error": "Клиент не найден в панели"}

        client_obj["flow"] = "xtls-rprx-vision"
        real_ids = {inb.get("id") for inb in (data.get("obj") or [])}
        valid_targets = {int(i) for i in target_inbound_ids if int(i) in real_ids}
        if not valid_targets:
            return {"success": False, "error": "Целевые инбаунды не найдены"}

        to_add = valid_targets - current_ids
        to_remove = current_ids - valid_targets

        # уже ровно там, где нужно — не трогаем, чтобы зря не сбрасывать трафик
        if not to_add and not to_remove:
            return {"success": True, "moved": False}

        safe_email = quote(email, safe="")
        safe_uuid = quote(client_obj.get("id", ""), safe="")

        async def _add_to(targets: set) -> set:
            """Кладёт клиента в указанные инбаунды, возвращает удавшиеся."""
            if not targets:
                return set()
            ok = set()
            bulk, _ = await _post(
                s, f"{url}/panel/api/clients/add",
                {"inboundIds": sorted(targets), "client": client_obj},
            )
            if bulk and bulk.get("success"):
                return set(targets)
            # массовый эндпоинт есть не везде — тогда по одному
            for tid in sorted(targets):
                for path in (
                    f"/panel/api/inbounds/{tid}/addClient",
                    "/panel/api/inbounds/addClient",
                ):
                    res, _e = await _post(
                        s, f"{url}{path}",
                        {"id": tid, "settings": json.dumps({"clients": [client_obj]})},
                    )
                    if res and res.get("success"):
                        ok.add(tid)
                        break
            return ok

        del_errors = []
        added = set()

        # Точечное удаление из одного инбаунда поддерживают не все сборки 3x-UI:
        # часть отвечает 404. Тогда единственный доступный путь — снести клиента
        # целиком по email и создать заново уже в нужных инбаундах.
        selective_failed = False
        for old_id in sorted(to_remove):
            done = False
            attempts = []
            for ident in (safe_uuid, safe_email):
                if not ident or done:
                    continue
                for path in (
                    f"/panel/api/inbounds/{old_id}/delClient/{ident}",
                    f"/panel/api/inbounds/delClient/{old_id}/{ident}",
                ):
                    res, res_err = await _post(s, f"{url}{path}", {})
                    if res and res.get("success"):
                        done = True
                        break
                    reason = res_err or (res or {}).get("msg") or str(res)
                    attempts.append(f"{path.rsplit('/api', 1)[-1]} → {reason}")
            if not done:
                selective_failed = True
                del_errors.append(f"инбаунд {old_id}: " + " | ".join(attempts[:2]))

        if to_remove and selective_failed:
            # Полное пересоздание. UUID, subId и email берутся из существующей
            # записи, поэтому ссылка подписки у клиента не меняется.
            del_errors = []
            wiped = False
            res, res_err = await _post(s, f"{url}/panel/api/clients/del/{safe_email}", {})
            if res and res.get("success"):
                wiped = True
            else:
                del_errors.append(
                    f"clients/del: {res_err or (res or {}).get('msg') or str(res)}"
                )
                for ib_id in sorted(current_ids):
                    r2, e2 = await _post(
                        s, f"{url}/panel/api/inbounds/delClient/{ib_id}/{safe_email}", {}
                    )
                    if r2 and r2.get("success"):
                        wiped = True
            if wiped:
                del_errors = []
                added = await _add_to(valid_targets)
            else:
                added = await _add_to(to_add)
        else:
            added = await _add_to(to_add)

        if to_add and not added:
            return {"success": False,
                    "error": "не удалось добавить ни в один целевой инбаунд"}

        # Сверяемся с панелью, а не верим ответам: бывает, что запрос
        # отвечает успехом, а клиент остаётся на месте.
        # Инбаунды на узлах обновляются не мгновенно, поэтому при расхождении
        # даём панели время и перечитываем — иначе задержка выглядит как сбой.
        async def _placement() -> set:
            vdata, _ = await _get(s, f"{url}/panel/api/inbounds/list")
            found = set()
            if vdata and vdata.get("success"):
                for inb in (vdata.get("obj") or []):
                    try:
                        st = inb.get("settings") or "{}"
                        st = json.loads(st) if isinstance(st, str) else st
                    except Exception:
                        continue
                    if any(c.get("email") == email for c in st.get("clients", [])):
                        found.add(inb.get("id"))
            return found

        actual = await _placement()
        for _attempt in range(3):
            if not (valid_targets - actual) and not (actual & to_remove):
                break
            await asyncio.sleep(5)
            actual = await _placement()

        problems = []
        still_missing = valid_targets - actual
        still_extra = actual & to_remove
        if still_missing:
            problems.append(f"не добавлен в {sorted(still_missing)}")
        if still_extra:
            problems.append(f"не удалён из {sorted(still_extra)}")
            if del_errors:
                problems.append("\n".join(del_errors[:3]))

        return {
            "success": not problems,
            "moved": True,
            "added": sorted(added),
            "removed": sorted(to_remove - still_extra),
            "actual": sorted(actual),
            "error": " · ".join(problems),
        }
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

        # Пробуем массовый эндпоинт — он кладёт сразу во все инбаунды
        payload = {"inboundIds": inbound_ids, "client": client}
        data, err = await _post(s, f"{url}/panel/api/clients/add", payload)

        added = set()
        if data and data.get("success"):
            added = set(inbound_ids)
        else:
            # Запасной путь: по одному инбаунду. Раньше здесь добавлялся
            # только первый — клиент оставался в одном инбаунде из нескольких.
            err1 = err or str(data)
            errors = [f"clients/add: {err1}"]
            for ib in inbound_ids:
                one_payload = {
                    "id": int(ib),
                    "settings": json.dumps({"clients": [client]}),
                }
                ok = False
                for path in (
                    f"/panel/api/inbounds/{ib}/addClient",
                    "/panel/api/inbounds/addClient",
                ):
                    res, res_err = await _post(s, f"{url}{path}", one_payload)
                    if res and res.get("success"):
                        ok = True
                        break
                    errors.append(f"inbound {ib} via {path}: {res_err or str(res)}")
                if ok:
                    added.add(ib)

            if not added:
                return {"success": False, "error": "\n".join(errors[:4])}

        missed = sorted(set(inbound_ids) - added)

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
            "inbound_ids": sorted(added),
            "missed_inbounds": missed,
        }

    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        await s.close()
