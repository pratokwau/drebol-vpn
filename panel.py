"""Одна дверь к панели: бот зовёт отсюда, а мы решаем, куда идти.

Раньше весь бот звал 3x-UI напрямую. Теперь панелей две, и переключение —
это одна настройка, а не правка двух десятков мест. Имена функций и формат
ответов остались прежними, поэтому вызывающий код не знает, с какой панелью
работает.

3x-UI пока никуда не делся: пока переключатель стоит на нём, всё идёт
по-старому. Переводим на Remnawave — те же вызовы уходят в её API.
"""

from datetime import datetime

from config import load_config

# Чисто 3x-UI-шные вещи: инбаунды, проверка портов, разбор ссылок.
# У Remnawave аналогов нет, поэтому берём как есть из старого модуля.
from xui_api import (  # noqa: F401
    build_email, strip_default_port, node_prefix, check_tcp,
    get_inbounds, test_connection,
)

XUI = "xui"
REMNAWAVE = "remnawave"


def provider() -> str:
    """Какая панель обслуживает подписки прямо сейчас."""
    p = (load_config().get("panel_provider") or XUI).lower()
    return REMNAWAVE if p == REMNAWAVE else XUI


def provider_label() -> str:
    return "Remnawave" if provider() == REMNAWAVE else "3x-UI"


def on_remnawave() -> bool:
    return provider() == REMNAWAVE


def _fail(error: str) -> dict:
    return {"success": False, "error": error}


def _iso(expire_date: str) -> str:
    from remnawave import to_iso
    return to_iso(expire_date)


def _name(email: str) -> str:
    """Имя клиента в Remnawave. У панели свои правила для имён, и у части
    подписок в базе email им не отвечает (длинные ники обрезаются). Правило
    одно и то же на выдаче и на переносе, поэтому имя всегда получается тем же.
    """
    from remnawave import make_username
    return make_username(email or "", 0)


# ── Подписки ──────────────────────────────────────────────────────────────────

async def create_client(expire_date: str, limit_ip: int, limit_hwid: int,
                        total_gb: int, email=None, preset_inbound_ids_override=None) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.create_client(expire_date, limit_ip, limit_hwid, total_gb,
                                           email, preset_inbound_ids_override)

    import remnawave as rw
    username = _name(email)
    payload = {
        "username": username,
        "status": "ACTIVE",
        "expireAt": _iso(expire_date),
        "trafficLimitBytes": int(total_gb or 0) * 1024 ** 3,
        "hwidDeviceLimit": int(limit_hwid or 0),
        "description": "Создано ботом Drebol VPN",
    }
    squads = rw.settings()["squads"]
    if squads:
        payload["activeInternalSquads"] = list(squads)

    r = await rw.create_user(payload)
    if not r["ok"]:
        # имя занято — значит клиент уже есть, забираем его и приводим к нашим данным
        found = await rw.user_by_name(username)
        if not found["ok"]:
            return _fail(str(r.get("error")))
        r = await rw.patch(username, expireAt=payload["expireAt"],
                           trafficLimitBytes=payload["trafficLimitBytes"],
                           hwidDeviceLimit=payload["hwidDeviceLimit"],
                           activeInternalSquads=payload.get("activeInternalSquads"))
        if not r["ok"]:
            return _fail(str(r.get("error")))

    data = r["data"] or {}
    if data.get("id") is not None:
        rw._IDS[username] = data["id"]
    return {
        "success": True,
        "sub_url": data.get("subscriptionUrl", ""),
        "uuid": data.get("vlessUuid", ""),
        "email": username,
        "sub_id": data.get("shortUuid", ""),
        "expire": expire_date,
        "inbound_id": None,
        "inbound_ids": [],
        "missed_inbounds": [],
    }


async def update_client_expire(email: str, new_expire_str: str,
                               limit_hwid: int = None) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.update_client_expire(email, new_expire_str, limit_hwid)

    import remnawave as rw
    r = await rw.patch(_name(email), expireAt=_iso(new_expire_str),
                       hwidDeviceLimit=None if limit_hwid is None else int(limit_hwid))
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def update_client_limits(email: str, limit_ip: int = None,
                               limit_hwid: int = None) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.update_client_limits(email, limit_ip, limit_hwid)
    if limit_hwid is None:
        # лимита по IP в Remnawave нет, ограничение только по устройствам
        return {"success": True}

    import remnawave as rw
    r = await rw.patch(_name(email), hwidDeviceLimit=int(limit_hwid))
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def toggle_client(email: str, enable: bool) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.toggle_client(email, enable)

    import remnawave as rw
    r = await rw.action(_name(email), "enable" if enable else "disable")
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def get_client_info(email: str) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.get_client_info(email)

    import remnawave as rw
    r = await rw.user_by_name(_name(email))
    if not r["ok"]:
        return {"success": False}
    data = r["data"] or {}
    return {"success": True, "enabled": (data.get("status") == "ACTIVE"),
            "uuid": data.get("vlessUuid", ""), "inbound_id": None}


async def get_client_traffic(email: str) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.get_client_traffic(email)

    import remnawave as rw
    r = await rw.user_by_name(_name(email))
    if not r["ok"]:
        return {"success": False, "error": str(r.get("error"))}
    traffic = (r["data"] or {}).get("userTraffic") or {}
    # панель отдаёт один общий счётчик, поэтому весь расход кладём в «получено»
    return {"success": True, "up": 0, "down": int(traffic.get("usedTrafficBytes") or 0)}


async def delete_client(email: str) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.delete_client(email)

    import remnawave as rw
    r = await rw.delete_by_name(_name(email))
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def update_client_email(old_email: str, new_email: str, client_uuid: str,
                              sub_id: str, expire_date: str, limit_ip: int,
                              limit_hwid: int, total_gb: int) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.update_client_email(old_email, new_email, client_uuid,
                                                 sub_id, expire_date, limit_ip,
                                                 limit_hwid, total_gb)
    # Переименование в Remnawave сломало бы ссылку подписки, поэтому имя
    # в панели остаётся тем, с которым клиента завели.
    return {"success": True, "skipped": "переименование не нужно"}


async def move_client_inbound(email: str, target_inbound_ids: list,
                              limit_hwid: int = None) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.move_client_inbound(email, target_inbound_ids, limit_hwid)
    # В Remnawave доступ определяется сквадами, а окончание срока панель
    # обрабатывает сама — переносить клиента никуда не нужно.
    return {"success": True, "moved": False}


async def reissue_subscription(email: str, limit_hwid: int = None) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.reissue_subscription(email, limit_hwid)

    import remnawave as rw
    r = await rw.action(_name(email), "revoke")
    if not r["ok"]:
        return _fail(str(r.get("error")))
    data = r["data"] or {}
    return {"success": True, "new_uuid": data.get("vlessUuid", ""),
            "sub_id": data.get("shortUuid", ""),
            "sub_url": data.get("subscriptionUrl", ""), "failed_inbounds": []}


# ── Устройства и адреса ───────────────────────────────────────────────────────

async def get_client_hwids(email: str) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.get_client_hwids(email)

    import remnawave as rw
    r = await rw.devices(_name(email))
    if not r["ok"]:
        return {"ok": False, "error": str(r.get("error")), "items": []}
    items = (r["data"] or {}).get("devices") or []
    # приводим к виду, который уже умеет показывать бот
    out = []
    for d in items:
        out.append({
            "id": d.get("hwid"),
            "hwid": d.get("hwid"),
            "deviceModel": d.get("deviceModel"),
            "deviceOs": d.get("platform"),
            "osVersion": d.get("osVersion"),
            "platform": d.get("platform"),
            "userAgent": d.get("userAgent"),
            "requestIp": d.get("requestIp"),
            "lastSeen": d.get("updatedAt") or d.get("createdAt"),
            "firstSeen": d.get("createdAt"),
        })
    return {"ok": True, "items": out}


async def resolve_hwid(email: str, ref: str):
    """Находит устройство по метке из кнопки.

    У 3x-UI устройство помечено числом, у Remnawave — длинной строкой hwid,
    которая в кнопку целиком не влезает: там лежит её начало. Кнопка в чате
    живёт дольше самого устройства, поэтому если по метке никто не нашёлся —
    возвращаем «нет», а не соседнее устройство.
    """
    mark = str(ref).split(":")[-1]
    got = await get_client_hwids(email)
    items = got.get("items") or []
    for d in items:
        if str(d.get("id", "")) == mark:
            return d.get("id")
    same = [d.get("id") for d in items if str(d.get("id", "")).startswith(mark)]
    return same[0] if len(same) == 1 else None


async def delete_client_hwid(email: str, hwid_id) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.delete_client_hwid(email, hwid_id)

    import remnawave as rw
    r = await rw.delete_device(_name(email), hwid_id)
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def clear_client_hwids(email: str) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.clear_client_hwids(email)

    import remnawave as rw
    r = await rw.delete_all_devices(_name(email))
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def get_client_ips(email: str) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.get_client_ips(email)

    # Отдельного журнала адресов в Remnawave нет, но у каждого устройства
    # записан адрес последнего обращения — этого хватает, чтобы понять,
    # откуда человек подключается.
    devices = await get_client_hwids(email)
    if not devices.get("ok"):
        return {"ok": False, "error": devices.get("error", ""), "items": []}
    items = [{"ip": d["requestIp"], "ts": d.get("lastSeen"), "node": d.get("deviceModel")}
             for d in devices["items"] if d.get("requestIp")]
    return {"ok": True, "items": items}


async def clear_client_ips(email: str) -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.clear_client_ips(email)
    return _fail("в Remnawave адреса живут вместе с устройствами — "
                 "очисти список устройств")


# ── Сводки по панели ──────────────────────────────────────────────────────────

def _online_since(user: dict):
    traffic = user.get("userTraffic") or {}
    raw = traffic.get("onlineAt") or user.get("onlineAt")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _used_bytes(user: dict) -> int:
    traffic = user.get("userTraffic") or {}
    raw = traffic.get("usedTrafficBytes", user.get("usedTrafficBytes"))
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


async def count_panel_clients() -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.count_panel_clients()

    import remnawave as rw
    users = await rw.all_users()
    names = {u.get("username") for u in users if u.get("username")}
    paid = sum(1 for n in names if n.startswith("paid_"))
    total = len(names)
    return {"success": True, "total": total, "paid": paid, "other": total - paid}


async def get_online_emails(window_seconds: int = 180) -> dict:
    """Кто сейчас на VPN. У Remnawave есть только отметка последнего
    обращения, поэтому «сейчас» — это последние минуты."""
    if not on_remnawave():
        import xui_api
        return await xui_api.get_online_emails()

    import remnawave as rw
    from datetime import timezone, timedelta
    users = await rw.all_users()
    if not users:
        return {"ok": True, "emails": []}
    edge = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    online = [u.get("username") for u in users
              if (_online_since(u) or datetime.min.replace(tzinfo=timezone.utc)) >= edge]
    return {"ok": True, "emails": sorted(e for e in online if e)}


async def get_last_online(timeout: float = 15) -> dict:
    """Когда клиент последний раз был в сети, в миллисекундах. 0 — ни разу."""
    if not on_remnawave():
        import xui_api
        return await xui_api.get_last_online(timeout)

    import remnawave as rw
    users = await rw.all_users()
    last = {}
    for u in users:
        name = u.get("username")
        if not name:
            continue
        seen = _online_since(u)
        last[name] = int(seen.timestamp() * 1000) if seen else 0
    return {"ok": True, "last": last}


async def get_traffic_snapshot() -> dict:
    if not on_remnawave():
        import xui_api
        return await xui_api.get_traffic_snapshot()

    import remnawave as rw
    users = await rw.all_users()
    clients = {}
    for u in users:
        name = u.get("username")
        if name:
            # панель считает один общий расход, поэтому всё кладём в «получено»
            clients[name] = (0, _used_bytes(u))
    return {"ok": True, "clients": clients}


# ── Проверка живости ──────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Заданы ли параметры той панели, что сейчас обслуживает подписки."""
    if on_remnawave():
        import remnawave as rw
        return rw.is_configured()
    cfg = load_config()
    return bool(cfg.get("xui_url") and cfg.get("xui_token"))


def node_word(plural: bool = True) -> str:
    """Как называть точки входа в текстах: у 3x-UI это инбаунды, у Remnawave — узлы."""
    if on_remnawave():
        return "Узлы" if plural else "Узел"
    return "Инбаунды" if plural else "Инбаунд"


async def probe_servers() -> dict:
    """Панель, страница подписок и точки входа — живы или нет.

    Формат ответа один на обе панели, чтобы экран «Здоровье серверов» и
    ночная проверка не знали, с какой панелью работают. У Remnawave точки
    входа — это узлы, и об их состоянии рассказывает сама панель.
    """
    if not on_remnawave():
        import xui_api
        return await xui_api.probe_servers()

    import time
    from urllib.parse import urlparse
    import remnawave as rw

    s = rw.settings()
    host = urlparse(s["url"]).hostname if s["url"] else None
    scheme = urlparse(s["url"]).scheme or "https"

    start = time.monotonic()
    check = await rw.test_connection()
    panel = {"ok": bool(check.get("ok")), "ms": int((time.monotonic() - start) * 1000),
             "error": check.get("error"), "host": host}

    # Ссылки подписок Remnawave отдаёт со своего же адреса.
    port = 443 if scheme == "https" else 80
    tcp = await check_tcp(host, port, timeout=4.0)
    sub = {"ok": bool(tcp.get("ok")), "ms": tcp.get("ms"), "status": 200,
           "port": port, "error": tcp.get("error"),
           "url": f"{scheme}://{host}" if host else ""}

    nodes = []
    if panel["ok"]:
        r = await rw.nodes()
        raw = r["data"] if r.get("ok") else []
        if isinstance(raw, dict):
            raw = raw.get("nodes") or raw.get("response") or []
        for n in raw or []:
            name = n.get("name") or n.get("address") or "узел"
            alive = bool(n.get("isConnected")) and n.get("isXrayRunning") is not False
            trouble = n.get("lastStatusMessage") or ""
            if not alive and not trouble:
                trouble = "панель не видит узел"
            nodes.append({
                "tag": name,
                "prefix": name,
                "host": n.get("address"),
                "mapped": True,
                "protocol": n.get("xrayVersion") or "xray",
                "udp": False,
                "port": n.get("port") or "",
                "enabled": not n.get("isDisabled"),
                "clients": int(n.get("usersOnline") or 0),
                "reachable": alive,
                "ms": None,
                "error": trouble,
            })
    return {"panel": panel, "sub": sub, "inbounds": nodes}
