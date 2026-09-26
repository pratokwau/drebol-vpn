"""Одна дверь к панели: бот зовёт отсюда, а внутри — API Remnawave.

Раньше здесь жили две панели и переключатель между ними. 3x-UI из бота убран,
остался один дом для подписок, поэтому лишний слой ни к чему: функции те же,
что бот звал всегда, а внутри — запросы к Remnawave.

Формат ответов сохранён (`success`, `ok`, `items`), чтобы экраны не переписывать.
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlparse


# последняя неприменённая дата — её показывает «Здоровье серверов»
LAST_EXPIRE_FAIL = None


def build_email(tg_id: int, username=None, prefix: str = "") -> str:
    """Имя подписки: по нему бот и панель говорят об одном и том же клиенте."""
    suffix = username.strip().lower() if username else "nousername"
    raw = f"{prefix}{tg_id}_{suffix}"
    return "".join(c for c in raw if c.isalnum() or c in ("_", "-", "."))[:50]


def strip_default_port(sub_url: str) -> str:
    """Убирает :443 и :80 из ссылки — они там ничего не значат."""
    if not sub_url:
        return sub_url
    sub_url = re.sub(r'^(https://[^/:]+):443(/)', r'\1\2', sub_url)
    sub_url = re.sub(r'^(http://[^/:]+):80(/)', r'\1\2', sub_url)
    return sub_url


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


def is_configured() -> bool:
    """Заданы ли адрес панели и токен."""
    import remnawave as rw
    return rw.is_configured()


def _fail(error: str) -> dict:
    return {"success": False, "error": error}


def _iso(expire_date: str) -> str:
    from remnawave import to_iso
    return to_iso(expire_date)


def _name(email: str) -> str:
    """Имя клиента в панели. У неё свои правила для имён, и у части подписок
    в базе email им не отвечает (длинные ники обрезаются). Правило одно и то же
    на выдаче и на переносе, поэтому имя всегда получается тем же.
    """
    from remnawave import make_username
    return make_username(email or "", 0)


# ── Подписки ──────────────────────────────────────────────────────────────────

async def create_client(expire_date: str, limit_ip: int, limit_hwid: int,
                        total_gb: int, email=None, tg_id=None, note: str = "") -> dict:
    """Заводит клиента. TG ID и ник кладём в панель: по ним видно, кто это,
    без сверки с базой бота — раньше для этого переименовывали клиента."""
    import remnawave as rw
    username = _name(email)
    payload = {
        "username": username,
        "status": "ACTIVE",
        "expireAt": _iso(expire_date),
        "trafficLimitBytes": int(total_gb or 0) * 1024 ** 3,
        "hwidDeviceLimit": int(limit_hwid or 0),
        "description": f"Drebol VPN · {note}" if note else "Создано ботом Drebol VPN",
    }
    if tg_id:
        payload["telegramId"] = int(tg_id)
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
    }


async def update_client_expire(email: str, new_expire_str: str,
                               limit_hwid: int = None) -> dict:
    """Меняет срок окончания и сразу сверяет, что панель его приняла.

    Сверка нужна, потому что по этой дате панель сама закрывает доступ: если
    запрос тихо не применился, бот считал бы подписку закрытой, а человек
    продолжал бы пользоваться VPN. Смена срока — редкое событие, лишний
    запрос на проверку тут дешевле такой ошибки.
    """
    import remnawave as rw
    want = _iso(new_expire_str)
    name = _name(email)
    r = await rw.patch(name, expireAt=want,
                       hwidDeviceLimit=None if limit_hwid is None else int(limit_hwid))
    if not r["ok"]:
        return _note_fail(email, new_expire_str, str(r.get("error")))

    got = ((r["data"] or {}).get("expireAt")) if isinstance(r.get("data"), dict) else None
    if got is None:
        back = await rw.user_by_name(name)
        got = (back["data"] or {}).get("expireAt") if back["ok"] else None
    if got is not None and not _same_moment(got, want):
        return _note_fail(email, new_expire_str,
                          f"панель оставила свой срок: {got} вместо {want}")
    return {"success": True}


def _same_moment(a, b) -> bool:
    """Одна ли это дата с точностью до минуты (панель может вернуть свой формат)."""
    def moment(raw):
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    ma, mb = moment(a), moment(b)
    if ma is None or mb is None:
        return str(a)[:16] == str(b)[:16]
    return abs(ma - mb) < 90


def _note_fail(email: str, wanted: str, error: str) -> dict:
    """Запоминает и пишет в журнал сервиса неприменённый срок.

    Часть вызывающих мест ответ не смотрит, а расхождение по сроку — это
    открытый доступ у того, кто уже не платит. Пусть остаётся хотя бы след
    в journalctl и в «Здоровье серверов».
    """
    global LAST_EXPIRE_FAIL
    LAST_EXPIRE_FAIL = {"email": email, "wanted": wanted, "error": error,
                        "at": datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
    logging.error("panel: срок %s для %s не применён: %s", wanted, email, error)
    return {"success": False, "error": error}


async def update_client_limits(email: str, limit_ip: int = None,
                               limit_hwid: int = None) -> dict:
    if limit_hwid is None:
        # лимита по IP в Remnawave нет, ограничение только по устройствам
        return {"success": True}

    import remnawave as rw
    r = await rw.patch(_name(email), hwidDeviceLimit=int(limit_hwid))
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def update_client_traffic(email: str, total_gb: int) -> dict:
    """Лимит трафика. 0 — безлимит."""
    import remnawave as rw
    r = await rw.patch(_name(email), trafficLimitBytes=int(total_gb or 0) * 1024 ** 3)
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def sync_client_note(email: str, note: str = "", tg_id=None) -> dict:
    """Обновляет подпись клиента в панели: ник и TG ID.

    Имя клиента менять нельзя — оно вшито в ссылку подписки, — поэтому ник
    живёт в описании. Если в панели уже то же самое, запрос не отправляем.
    """
    import remnawave as rw
    name = _name(email)
    want = f"Drebol VPN · {note}" if note else "Создано ботом Drebol VPN"
    r = await rw.user_by_name(name)
    if not r["ok"]:
        return _fail(str(r.get("error")))
    data = r["data"] or {}
    same_note = (data.get("description") or "") == want
    same_tg = (not tg_id) or str(data.get("telegramId") or "") == str(tg_id)
    if same_note and same_tg:
        return {"success": True, "changed": False}

    fields = {"description": want}
    if tg_id:
        fields["telegramId"] = int(tg_id)
    upd = await rw.patch(name, **fields)
    if not upd["ok"]:
        return _fail(str(upd.get("error")))
    return {"success": True, "changed": True}


async def toggle_client(email: str, enable: bool) -> dict:
    import remnawave as rw
    r = await rw.action(_name(email), "enable" if enable else "disable")
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def get_client_info(email: str) -> dict:
    import remnawave as rw
    r = await rw.user_by_name(_name(email))
    if not r["ok"]:
        return {"success": False}
    data = r["data"] or {}
    return {"success": True, "enabled": (data.get("status") == "ACTIVE"),
            "uuid": data.get("vlessUuid", "")}


async def get_client_traffic(email: str) -> dict:
    import remnawave as rw
    r = await rw.user_by_name(_name(email))
    if not r["ok"]:
        return {"success": False, "error": str(r.get("error"))}
    traffic = (r["data"] or {}).get("userTraffic") or {}
    # панель отдаёт один общий счётчик, поэтому весь расход кладём в «получено»
    return {"success": True, "up": 0, "down": int(traffic.get("usedTrafficBytes") or 0)}


async def delete_client(email: str) -> dict:
    import remnawave as rw
    r = await rw.delete_by_name(_name(email))
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def reissue_subscription(email: str, limit_hwid: int = None) -> dict:
    import remnawave as rw
    r = await rw.action(_name(email), "revoke")
    if not r["ok"]:
        return _fail(str(r.get("error")))
    data = r["data"] or {}
    return {"success": True, "new_uuid": data.get("vlessUuid", ""),
            "sub_id": data.get("shortUuid", ""),
            "sub_url": data.get("subscriptionUrl", "")}


# ── Устройства и адреса ───────────────────────────────────────────────────────

async def get_client_hwids(email: str) -> dict:
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

    Устройство помечено строкой hwid, которая в кнопку целиком не влезает:
    там лежит её начало. Кнопка в чате живёт дольше самого устройства, поэтому
    если по метке никто не нашёлся — возвращаем «нет», а не соседнее устройство.
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
    import remnawave as rw
    r = await rw.delete_device(_name(email), hwid_id)
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def clear_client_hwids(email: str) -> dict:
    import remnawave as rw
    r = await rw.delete_all_devices(_name(email))
    return {"success": True} if r["ok"] else _fail(str(r.get("error")))


async def get_client_ips(email: str) -> dict:
    """Откуда человек подключается. Отдельного журнала адресов в панели нет,
    но у каждого устройства записан адрес последнего обращения."""
    devices = await get_client_hwids(email)
    if not devices.get("ok"):
        return {"ok": False, "error": devices.get("error", ""), "items": []}
    items = [{"ip": d["requestIp"], "ts": d.get("lastSeen"), "node": d.get("deviceModel")}
             for d in devices["items"] if d.get("requestIp")]
    return {"ok": True, "items": items}


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
    import remnawave as rw
    users = await rw.all_users()
    names = {u.get("username") for u in users if u.get("username")}
    paid = sum(1 for n in names if n.startswith("paid_"))
    total = len(names)
    return {"success": True, "total": total, "paid": paid, "other": total - paid}


async def get_online_emails(window_seconds: int = 180) -> dict:
    """Кто сейчас на VPN. У панели есть только отметка последнего обращения,
    поэтому «сейчас» — это последние минуты."""
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

async def probe_servers() -> dict:
    """Панель, выдача подписок и узлы — живы или нет.

    Состояние узлов рассказывает сама панель, простукивать их порты не нужно.
    """
    import remnawave as rw

    s = rw.settings()
    parsed = urlparse(s["url"])
    host, scheme = parsed.hostname, (parsed.scheme or "https")

    start = time.monotonic()
    check = await rw.test_connection()
    panel = {"ok": bool(check.get("ok")), "ms": int((time.monotonic() - start) * 1000),
             "error": check.get("error"), "host": host}

    # Ссылки подписок панель отдаёт со своего же адреса.
    port = parsed.port or (443 if scheme == "https" else 80)
    tcp = await check_tcp(host, port, timeout=4.0)
    sub = {"ok": bool(tcp.get("ok")), "ms": tcp.get("ms"), "port": port,
           "error": tcp.get("error"), "url": f"{scheme}://{host}" if host else ""}

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
                "host": n.get("address"),
                "xray": n.get("xrayVersion") or "",
                "port": n.get("port") or "",
                "enabled": not n.get("isDisabled"),
                "clients": int(n.get("usersOnline") or 0),
                "reachable": alive,
                "error": trouble,
            })
    return {"panel": panel, "sub": sub, "nodes": nodes}
