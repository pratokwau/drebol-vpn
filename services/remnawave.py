"""Remnawave: связь с панелью и её настройки в боте.

Здесь живут адрес и токен панели, выбор сквадов, запросы к её API и рассылка
ссылок подписок людям.

Пути и поля взяты из контракта API панели: всё под /api, ответы завёрнуты
в {"response": ...}. Клиент опознаётся по username — его мы получаем из email
подписки одним и тем же правилом, поэтому бот всегда попадает в того же
человека, а не плодит дублей.
"""

import asyncio
import calendar
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from html import escape

import aiohttp

from config import load_config, save_config

API_ROOT = "/api"
USERS = f"{API_ROOT}/users"
SQUADS = f"{API_ROOT}/internal-squads"
CONFIG_PROFILES = f"{API_ROOT}/config-profiles"


def settings() -> dict:
    cfg = load_config()
    return {
        "url": (cfg.get("rw_url") or "").rstrip("/"),
        "token": cfg.get("rw_token") or "",
        "squads": list(cfg.get("rw_squads") or []),
    }


def save_settings(**kw):
    cfg = load_config()
    cfg.update(kw)
    save_config(cfg)


def is_configured() -> bool:
    s = settings()
    return bool(s["url"] and s["token"])


def _session() -> aiohttp.ClientSession:
    s = settings()
    return aiohttp.ClientSession(
        headers={
            "Authorization": f"Bearer {s['token']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=aiohttp.ClientTimeout(total=25),
    )


async def _request(method: str, path: str, payload=None) -> dict:
    """Один запрос к панели. Возвращает {ok, data|error, status}."""
    s = settings()
    if not s["url"] or not s["token"]:
        return {"ok": False, "error": "не задан адрес панели или токен"}
    url = f"{s['url']}{path}"
    try:
        async with _session() as http:
            async with http.request(method, url, json=payload) as resp:
                text = await resp.text()
                data = None
                if text.strip():
                    try:
                        import json
                        data = json.loads(text)
                    except ValueError:
                        data = None
                if resp.status == 404:
                    return {"ok": False, "status": 404, "error": "не найдено"}
                if resp.status >= 400:
                    detail = ""
                    if isinstance(data, dict):
                        detail = str(data.get("message") or data.get("error") or "")
                    return {"ok": False, "status": resp.status,
                            "error": detail or f"HTTP {resp.status}: {text[:200]}"}
                body = data.get("response") if isinstance(data, dict) else data
                return {"ok": True, "status": resp.status, "data": body}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── Действия панели ───────────────────────────────────────────────────────────

async def test_connection() -> dict:
    r = await _request("GET", SQUADS)
    if not r["ok"]:
        return r
    data = r["data"] or {}
    squads = data.get("internalSquads") or []
    return {"ok": True, "squads": len(squads)}


async def list_squads() -> dict:
    r = await _request("GET", SQUADS)
    if not r["ok"]:
        return r
    data = r["data"] or {}
    out = []
    for sq in data.get("internalSquads") or []:
        info = sq.get("info") or {}
        out.append({"uuid": sq.get("uuid"), "name": sq.get("name") or "без имени",
                    "members": info.get("membersCount", 0),
                    "inbounds": info.get("inboundsCount", 0)})
    return {"ok": True, "squads": out}


async def list_config_profiles() -> dict:
    """Профили конфигурации панели (инбаунды и хосты) — только чтение.

    Используется веб-админкой для страницы «Панель Remnawave».
    Редактирование — через get/update_config_profile() ниже (веб-админка
    правит только whitelisted-поля одного инбаунда и валидирует результат
    через get_computed_config); правки напрямую в панели — через браузер.
    """
    r = await _request("GET", CONFIG_PROFILES)
    if not r["ok"]:
        return r
    data = r["data"]
    profiles = data if isinstance(data, list) else (data or {}).get("configProfiles") or []
    out = []
    for p in profiles:
        if not isinstance(p, dict):
            continue
        inbounds = []
        for ib in p.get("inbounds") or []:
            if not isinstance(ib, dict):
                continue
            hosts = []
            for h in ib.get("hosts") or []:
                if not isinstance(h, dict):
                    continue
                hosts.append({
                    "remark": h.get("remark") or "",
                    "address": h.get("address") or "",
                    "port": h.get("port"),
                    "sni": h.get("sni") or "",
                    "is_disabled": bool(h.get("isDisabled")),
                })
            inbounds.append({
                "tag": ib.get("tag") or "",
                "type": ib.get("type") or "",
                "port": (ib.get("port") or (ib.get("config") or {}).get("port")),
                "hosts": hosts,
            })
        out.append({"uuid": p.get("uuid") or "", "name": p.get("name") or "",
                    "inbounds": inbounds})
    return {"ok": True, "profiles": out}


async def get_config_profile(uuid: str) -> dict:
    """Один профиль конфигурации целиком, включая config.inbounds.

    GET /api/config-profiles/{uuid}. Ответ панели — сам профиль
    (uuid, name, config: полный Xray-JSON, ...)."""
    return await _request("GET", f"{CONFIG_PROFILES}/{uuid}")


async def update_config_profile(uuid: str, config: dict) -> dict:
    """Заменить config профиля целиком.

    PATCH /api/config-profiles, тело — UpdateConfigProfileRequestDto
    {"uuid": uuid, "config": config} (полный Xray-JSON, не дельта).
    Вызывающий обязан сначала GET'нуть профиль и менять в копии только
    нужные поля — панель перезапишет config как есть."""
    return await _request("PATCH", CONFIG_PROFILES,
                          {"uuid": uuid, "config": config})


async def get_computed_config(uuid: str) -> dict:
    """Вычисленный Xray-конфиг профиля после правок — для валидации.

    GET /api/config-profiles/{uuid}/computed-config. Если панель приняла
    PATCH, но конфиг не собирается, ошибка видна здесь, а не у юзеров."""
    return await _request("GET", f"{CONFIG_PROFILES}/{uuid}/computed-config")


HOSTS = f"{API_ROOT}/hosts"


def _norm_host(h: dict) -> dict:
    return {
        "uuid": h.get("uuid") or "",
        "inboundUuid": h.get("inboundUuid") or "",
        "remark": h.get("remark") or "",
        "address": h.get("address") or "",
        "port": h.get("port"),
        "sni": h.get("sni") or "",
        "isDisabled": bool(h.get("isDisabled")),
    }


async def list_hosts() -> dict:
    """Все хосты панели. GET /api/hosts."""
    r = await _request("GET", HOSTS)
    if not r["ok"]:
        return r
    data = r["data"]
    raw = data if isinstance(data, list) else (data or {}).get("hosts") or []
    return {"ok": True,
            "hosts": [_norm_host(h) for h in raw if isinstance(h, dict)]}


async def patch_host(uuid: str, fields: dict) -> dict:
    """Точечная правка хоста. PATCH /api/hosts, тело {"uuid": uuid, ...fields}.

    Тот же collection-паттерн, что PATCH /api/users и PATCH
    /api/config-profiles: uuid + только меняемые поля. Валидация —
    read-back через list_hosts() у вызывающего."""
    body = {"uuid": uuid}
    body.update(fields)
    return await _request("PATCH", HOSTS, body)


async def create_host(fields: dict) -> dict:
    """Новый хост. POST /api/hosts. Валидация — read-back через list_hosts()."""
    return await _request("POST", HOSTS, fields)


async def delete_host(uuid: str) -> dict:
    """Удалить хост. DELETE /api/hosts/{uuid}."""
    return await _request("DELETE", f"{HOSTS}/{uuid}")


async def get_user(username: str) -> dict:
    return await _request("GET", f"{USERS}/by-username/{username}")


async def create_user(payload: dict) -> dict:
    return await _request("POST", USERS, payload)


async def update_user(payload: dict) -> dict:
    return await _request("PATCH", USERS, payload)


# ── Операции с подпиской ──────────────────────────────────────────────────────

# Панель адресует пользователя числовым id, а бот знает только email подписки.
# Держим соответствие в памяти: имена не меняются, а лишний запрос на каждое
# действие — это лишняя задержка для человека.
_IDS: dict = {}


def forget(username: str):
    _IDS.pop(username, None)


async def user_by_name(username: str) -> dict:
    """Пользователь панели по имени. Заодно запоминаем его числовой id."""
    r = await get_user(username)
    if r["ok"] and isinstance(r.get("data"), dict):
        uid = r["data"].get("id")
        if uid is not None:
            _IDS[username] = uid
    return r


async def user_id(username: str):
    if username in _IDS:
        return _IDS[username]
    r = await user_by_name(username)
    return _IDS.get(username) if r["ok"] else None


async def patch(username: str, **fields) -> dict:
    """Точечная правка пользователя: меняем только переданное."""
    body = {"username": username}
    body.update({k: v for k, v in fields.items() if v is not None})
    return await update_user(body)


async def action(username: str, name: str, payload=None) -> dict:
    """Действие панели над пользователем: enable, disable, revoke."""
    uid = await user_id(username)
    if uid is None:
        return {"ok": False, "error": "пользователь не найден в панели"}
    return await _request("POST", f"{USERS}/{uid}/actions/{name}", payload or {})


async def devices(username: str) -> dict:
    uid = await user_id(username)
    if uid is None:
        return {"ok": False, "error": "пользователь не найден в панели"}
    return await _request("GET", f"{API_ROOT}/hwid/devices/{uid}")


async def delete_device(username: str, hwid: str) -> dict:
    uid = await user_id(username)
    if uid is None:
        return {"ok": False, "error": "пользователь не найден в панели"}
    return await _request("POST", f"{API_ROOT}/hwid/devices/delete",
                          {"userId": uid, "hwid": str(hwid)})


async def delete_all_devices(username: str) -> dict:
    uid = await user_id(username)
    if uid is None:
        return {"ok": False, "error": "пользователь не найден в панели"}
    return await _request("POST", f"{API_ROOT}/hwid/devices/delete-all", {"userId": uid})


async def delete_by_name(username: str) -> dict:
    uid = await user_id(username)
    if uid is None:
        return {"ok": True}          # нет — значит и удалять нечего
    r = await _request("DELETE", f"{USERS}/{uid}")
    forget(username)
    return r


async def nodes() -> dict:
    """Узлы панели: их состояние она знает сама, проверять порты не нужно."""
    return await _request("GET", f"{API_ROOT}/nodes")


# ── Потребление трафика по узлам ──────────────────────────────────────────────

def current_month_range(now=None):
    """Текущий календарный месяц: с 1-го числа по его последний день.

    Панель отдаёт расход по датам, а не «за последние 30 дней», поэтому
    границы берём именно календарные: в феврале это 28 (29 в високосном),
    в октябре — 31. Возвращает (начало, конец, «01.10.2026 — 31.10.2026»).
    """
    now = now or datetime.now(timezone.utc)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = calendar.monthrange(now.year, now.month)[1]
    last = now.replace(day=last_day, hour=23, minute=59, second=59,
                       microsecond=0)
    period = f"{first.strftime('%d.%m.%Y')} — {last.strftime('%d.%m.%Y')}"
    return first, last, period


def current_month_dates(now=None):
    """Тот же месяц, но датами YYYY-MM-DD — так их ждёт панель 3.x."""
    first, last, period = current_month_range(now)
    return first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"), period


# Коды периодов: month — текущий месяц (по умолчанию), prev — прошлый
# месяц, 7d/30d/90d — последние N дней, custom — даты, введённые вручную
# (лежат в context.user_data["rw_usage_custom"]).
_USAGE_PERIOD_NAMES = {
    "month": "Текущий месяц",
    "prev": "Прошлый месяц",
    "7d": "Последние 7 дней",
    "30d": "Последние 30 дней",
    "90d": "Последние 90 дней",
    "custom": "Свой период",
}


def _period_label(start: str, end: str) -> str:
    """YYYY-MM-DD — YYYY-MM-DD -> «01.10.2026 — 31.10.2026»."""
    def _fmt(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
        except (TypeError, ValueError):
            return str(d)
    return f"{_fmt(start)} — {_fmt(end)}"


def resolve_usage_period(context=None, now=None):
    """Выбранный период: (start, end, подпись, код).

    По умолчанию — текущий календарный месяц, как было раньше. Выбор
    живёт в user_data админа, поэтому пагинация и «Обновить» его не
    теряют, а после перезапуска бота всё снова становится месяцем.
    """
    now = now or datetime.now(timezone.utc)
    code = None
    if context is not None:
        code = (context.user_data or {}).get("rw_usage_period")
    if code in ("7d", "30d", "90d"):
        days = int(code[:-1])
        end = now.date()
        start = end - timedelta(days=days - 1)
        return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                _period_label(start.strftime("%Y-%m-%d"),
                              end.strftime("%Y-%m-%d")), code)
    if code == "prev":
        first_this = now.replace(day=1, hour=0, minute=0, second=0,
                                 microsecond=0)
        last_prev = (first_this - timedelta(days=1)).date()
        first_prev = last_prev.replace(day=1)
        return (first_prev.strftime("%Y-%m-%d"),
                last_prev.strftime("%Y-%m-%d"),
                _period_label(first_prev.strftime("%Y-%m-%d"),
                              last_prev.strftime("%Y-%m-%d")), code)
    if code == "custom" and context is not None:
        custom = (context.user_data or {}).get("rw_usage_custom")
        if (isinstance(custom, (list, tuple)) and len(custom) == 2
                and custom[0] and custom[1]):
            return custom[0], custom[1], _period_label(*custom), code
    start, end, period = current_month_dates(now)
    return start, end, period, "month"


def parse_custom_period(text: str):
    """«01.09.2026 — 15.09.2026» (или YYYY-MM-DD) -> (start, end).

    Возвращает None, если формат не распознан, даты невалидны или
    начало позже конца. Разделителем может быть тире, дефис или
    просто пробел.
    """
    if not text:
        return None
    # Ищем именно две даты: так дефис внутри ISO-даты (2026-09-01)
    # не путается с разделителем диапазона.
    parts = re.findall(r"\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}",
                       text.strip())
    if len(parts) != 2:
        return None
    dates = []
    for part in parts:
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                dates.append(datetime.strptime(part, fmt).date())
                break
            except ValueError:
                continue
        else:
            return None
    if dates[0] > dates[1]:
        return None
    return dates[0].strftime("%Y-%m-%d"), dates[1].strftime("%Y-%m-%d")


# Лимит топа панели по умолчанию — 100, в её же интерфейсе можно
# выбрать до 2000. Берём 2000, чтобы в бот попадали все пользователи
# узла, а не только первая сотня.
_TOP_USERS_LIMIT = 2000


async def node_users_usage(node_uuid: str, start: str, end: str) -> dict:
    """Расход пользователей одного узла за период (панель 3.x).

    Тот же эндпоинт, что открывает сама панель в «Статистике
    использования» узла: GET /api/bandwidth-stats/nodes/{uuid}/users
    ?start=YYYY-MM-DD&end=YYYY-MM-DD&topUsersLimit=2000.
    Ответ — {categories, sparklineData,
    topUsers: [{color, username, total}]}, где total уже суммарный
    расход пользователя за период в байтах.
    """
    path = (f"{API_ROOT}/bandwidth-stats/nodes/{node_uuid}/users"
            f"?start={quote(start, safe='')}"
            f"&end={quote(end, safe='')}"
            f"&topUsersLimit={_TOP_USERS_LIMIT}")
    return await _request("GET", path)


async def nodes_users_usage(node_uuids: list, start: str, end: str) -> dict:
    """Расход пользователей сразу по нескольким узлам (панель 3.x).

    POST /api/bandwidth-stats/nodes/users с телом
    {"nodesUuids": [...]} и теми же query-параметрами. Ответ той же
    формы, что у node_users_usage, но topUsers уже суммирован по всем
    перечисленным узлам — второй запрос на каждый узел не нужен.
    """
    path = (f"{API_ROOT}/bandwidth-stats/nodes/users"
            f"?start={quote(start, safe='')}"
            f"&end={quote(end, safe='')}"
            f"&topUsersLimit={_TOP_USERS_LIMIT}")
    return await _request("POST", path, {"nodesUuids": list(node_uuids)})


# ── LTE-трафик пользователя ───────────────────────────────────────────────────
# В боте LTE-узлами называются узлы панели, чьё название кончается на [CDN].
# В самой панели они так и зовутся [CDN] — переименование только в интерфейсе
# бота, чтобы не путать людей: LTE — это «белый» трафик, который считается
# отдельно от общего лимита подписки.

# Месячный лимит на LTE-узлы по умолчанию: каждый месяц пользователю
# даётся 30 ГБ, счётчик — просто текущий календарный месяц, поэтому
# обнуление происходит само, без отдельной задачи. Блокировки при
# превышении здесь нет — только показ расхода, дальше решает владелец.
# Лимит можно переопределить: пресетом для новых подписок или
# отдельно для каждой подписки (колонка lte_gb, NULL = пресет).
LTE_MONTHLY_GB = 30


def lte_limit_gb(sub_lte=None, preset=None) -> int:
    """Действующий месячный лимит LTE-трафика: свой у подписки,
    иначе пресет, иначе 30 ГБ по умолчанию."""
    if sub_lte is not None:
        return int(sub_lte)
    if preset is not None:
        return int(preset)
    return LTE_MONTHLY_GB


def lte_limit_label(sub_lte=None, preset=None) -> str:
    """Как показать лимит в админке: число и откуда оно взялось."""
    if sub_lte is not None:
        return f"{int(sub_lte)} ГБ (свой)"
    if preset is not None:
        return f"{int(preset)} ГБ (по умолчанию)"
    return f"{LTE_MONTHLY_GB} ГБ (по умолчанию)"


def is_cdn_node(name) -> bool:
    """LTE-узел — тот, чьё название кончается ровно на «[CDN]»,
    со скобками. «Германия - 1 [CDN]» — да, «Германия - 1» — нет."""
    return (name or "").strip().endswith("[CDN]")


async def user_cdn_usage(panel_username: str, start=None, end=None) -> dict:
    """Трафик одного пользователя панели только по LTE-узлам ([CDN]).

    Период по умолчанию — текущий месяц. Для каждого LTE-узла берётся
    его топ пользователей и ищется нужное имя; имя панели может не
    попасть в топ-2000 узла только при тысячах клиентов, на практике
    такого нет. Возвращает {ok, cdn_nodes, used_bytes, per_node,
    failed, period} или {ok: False, error}.
    """
    if start is None or end is None:
        start, end, period = current_month_dates()
    else:
        period = _period_label(start, end)
    nodes_r = await nodes()
    if not nodes_r["ok"]:
        return {"ok": False, "error": nodes_r.get("error")}
    cdn = [n for n in _parse_nodes(nodes_r["data"])
           if is_cdn_node(n["name"])]
    if not cdn:
        return {"ok": True, "cdn_nodes": [], "used_bytes": 0,
                "per_node": [], "failed": 0, "period": period}
    results = await asyncio.gather(*[
        node_users_usage(n["uuid"], start, end) for n in cdn
    ])
    per_node, failed, total = [], 0, 0
    for node, res in zip(cdn, results):
        if not res["ok"]:
            failed += 1
            continue
        used = dict(_usage_items(res["data"])).get(panel_username, 0)
        per_node.append((node["name"], used))
        total += used
    if failed == len(cdn):
        return {"ok": False, "error": "LTE-узлы не ответили"}
    per_node.sort(key=lambda kv: (-kv[1], kv[0].lower()))
    return {"ok": True, "cdn_nodes": [n["name"] for n in cdn],
            "used_bytes": total, "per_node": per_node,
            "failed": failed, "period": period}


async def all_lte_usage() -> dict:
    """Расход всех пользователей панели по LTE-узлам за текущий месяц.

    Одним запросом (панель сама агрегирует по узлам), а не по одному
    на узел: фоновой проверке это нужно для всех подписок сразу.
    Возвращает {ok, usage: {panel_username: bytes}, cdn_nodes}
    или {ok: False, error}.
    """
    start, end, period = current_month_dates()
    nodes_r = await nodes()
    if not nodes_r["ok"]:
        return {"ok": False, "error": nodes_r.get("error")}
    cdn = [n for n in _parse_nodes(nodes_r["data"])
           if is_cdn_node(n["name"])]
    if not cdn:
        return {"ok": True, "usage": {}, "cdn_nodes": [], "period": period}
    r = await nodes_users_usage([n["uuid"] for n in cdn], start, end)
    if not r["ok"]:
        return {"ok": False, "error": r.get("error")}
    return {"ok": True, "usage": dict(_usage_items(r["data"])),
            "cdn_nodes": [n["name"] for n in cdn], "period": period}


def _parse_nodes(data) -> list:
    """Узлы панели в виде [{uuid, name, disabled}]."""
    if isinstance(data, dict):
        raw = data.get("nodes") or data.get("response") or []
    else:
        raw = data or []
    out = []
    for n in raw:
        if not isinstance(n, dict) or not n.get("uuid"):
            continue
        out.append({"uuid": n["uuid"],
                    "name": n.get("name") or n.get("address") or "узел",
                    "disabled": bool(n.get("isDisabled"))})
    return out


def _usage_items(data) -> list:
    """Записи панели -> [(username, байты за период)], по убыванию.

    _request уже снял внешнюю обёртку {"response": ...}, но на всякий
    случай поддерживаем и вложенный список, и ключ users. Нулевой
    расход в список не попадает — он только шумит.
    """
    if isinstance(data, dict):
        if isinstance(data.get("topUsers"), list):
            # Панель 3.x: {topUsers: [{username, total}]}.
            data = data["topUsers"]
        else:
            for key in ("response", "users", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                return []
    if not isinstance(data, list):
        return []
    totals = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        username = row.get("username") or row.get("userName") or ""
        total = row.get("total")
        if total is None:
            total = (row.get("totalTrafficBytes")
                     or row.get("usedTrafficBytes") or 0)
        if isinstance(total, dict):
            total = sum(v for v in total.values()
                        if isinstance(v, (int, float)))
        try:
            total = int(total or 0)
        except (TypeError, ValueError):
            total = 0
        if username and total > 0:
            totals[username] = totals.get(username, 0) + total
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def _fmt_gb(nbytes: int) -> str:
    return f"{nbytes / 1024 ** 3:.2f} ГБ"


def _panel_tg_id(panel_username: str):
    """TG ID, зашитый в имя панели: paid_<tg_id> (новый формат, без юза)
    или paid_<tg_id>_<username> / <tg_id>_<username> (старый формат).
    None, если имя не по этому шаблону (например, заведено в панели вручную).
    """
    m = re.match(r"^(?:paid_)?(\d+)(?:_|$)", panel_username or "")
    return int(m.group(1)) if m else None


def _strip_username(panel_username: str) -> str | None:
    """Новое имя клиента без юзернейма: paid_<tg_id> / <tg_id>.

    None — имя уже в новом формате или не по шаблону (не трогаем).
    """
    m = re.match(r"^(paid_)?(\d+)_(.+)$", panel_username or "")
    if not m:
        return None
    return f"{m.group(1) or ''}{m.group(2)}"


async def _resolve_usage_labels(panel_usernames: list) -> dict:
    """Имя панели -> строка для списка: имя, @username, TG ID, срок.

    Привязка к базе бота (bot.db) идёт тремя путями, по надёжности:
    1) email подписки в paid_subs/admin_subs равен имени панели —
       оттуда TG ID и данные из таблицы users;
    2) TG ID из самого имени панели + users по этому ID;
    3) имя панели как @username в таблице users.
    Не нашёлся нигде — строка помечается «нет в базе», чтобы такие
    клиенты были видны, а не молча терялись.
    """
    labels = {}
    if not panel_usernames:
        return labels
    try:
        import core.database as db
    except Exception:
        return {u: f"<code>{escape(u)}</code>" for u in panel_usernames}
    try:
        by_email = await db.users_by_emails(list(panel_usernames))
    except Exception:
        by_email = {}
    # {имя панели: (tg_id, first_name, username)}
    resolved = {}
    parsed_ids = {}
    for un in panel_usernames:
        if un in by_email:
            tg_id, fn, db_un = by_email[un]
            resolved[un] = (tg_id, fn, db_un)
        else:
            tg_id = _panel_tg_id(un)
            if tg_id:
                parsed_ids[un] = tg_id
            else:
                try:
                    row = await db.find_user_by_username(un)
                except Exception:
                    row = None
                if row:
                    resolved[un] = (row[0], row[1], row[2])
    tg_ids = [tg for tg, _, _ in resolved.values() if tg]
    tg_ids += list(parsed_ids.values())
    try:
        by_id = await db.users_by_ids(tg_ids) if tg_ids else {}
    except Exception:
        by_id = {}
    try:
        subs = await db.subs_by_tg_ids(tg_ids) if tg_ids else {}
    except Exception:
        subs = {}
    for un in panel_usernames:
        if un in resolved:
            tg_id, fn, db_un = resolved[un]
        elif un in parsed_ids:
            tg_id = parsed_ids[un]
            fn, db_un = by_id.get(tg_id, (None, None))
        else:
            labels[un] = (f"<code>{escape(un)}</code>"
                          " · <i>нет в базе</i>")
            continue
        if tg_id is None:
            labels[un] = f"<code>{escape(un)}</code>"
            continue
        head = " ".join(p for p in (fn, f"@{db_un}" if db_un else None)
                        if p)
        label = f"{escape(head)} · <code>{tg_id}</code>" if head else \
            f"TG <code>{tg_id}</code>"
        sub = subs.get(tg_id) or {}
        expire = sub.get("expire")
        if expire:
            label += f" · до {escape(_fmt_expire(expire))}"
        labels[un] = label
    return labels


def _fmt_expire(expire) -> str:
    """Дата окончания подписки -> DD.MM.YYYY (или как есть)."""
    s = str(expire).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return s[:10]


_PAGE_SIZE = 20


def _usage_page_keyboard(node_uuid, page, total_pages, back_to):
    """Пагинация: кнопки ◀️/▶️, обновление и возврат."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(
                "◀️", callback_data=f"{back_to}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}",
                                        callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(
                "▶️", callback_data=f"{back_to}:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(
        "📅 Период", callback_data="rw_usage_period")])
    rows.append([InlineKeyboardButton(
        "🔄 Обновить", callback_data=f"{back_to}:{page}")])
    rows.append([InlineKeyboardButton("◀️ К узлам", callback_data="rw_usage"),
                 InlineKeyboardButton("◀️ К логам",
                                      callback_data="ctl_menu")])
    return InlineKeyboardMarkup(rows)


def _usage_text(title, period, items, page, total_pages, labels=None) -> str:
    """Текст страницы: итог + строки «номер. имя (@username) · TG ID — X ГБ».

    labels — привязка к базе для пользователей этой страницы
    (см. _resolve_usage_labels); без неё строка — просто имя панели.
    """
    total_bytes = sum(total for _, total in items)
    lines = [f"📊 <b>{escape(title)}</b>",
             f"Период: <b>{period}</b>",
             f"Всего: <b>{_fmt_gb(total_bytes)}</b>"
             f" · пользователей: <b>{len(items)}</b>", ""]
    if not items:
        lines.append("<i>За этот период трафика пока нет.</i>")
    else:
        start = (page - 1) * _PAGE_SIZE
        for i, (username, total) in enumerate(
                items[start:start + _PAGE_SIZE], start + 1):
            shown = (labels or {}).get(username) or \
                f"<code>{escape(username)}</code>"
            lines.append(f"{i}. {shown} — <b>{_fmt_gb(total)}</b>")
        if total_pages > 1:
            lines.append("")
            lines.append(f"<i>Страница {page} из {total_pages}.</i>")
    return "\n".join(lines)


async def handle_rw_usage(query, context=None):
    """Единый экран «Трафик»: сводка за всё время (счётчики панели
    с последнего сброса + топ-10) и потребление по узлам за выбранный
    период (по умолчанию — текущий месяц)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if not is_configured():
        await query.edit_message_text(
            "❌ <b>Панель не настроена</b>\n\n"
            "Сначала задай адрес и токен в меню Remnawave.",
            parse_mode="HTML", reply_markup=_usage_back())
        return
    await query.edit_message_text("📊 Загружаю узлы…")
    r = await nodes()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить узлы</b>\n\n"
            f"<code>{escape(str(r.get('error'))[:300])}</code>",
            parse_mode="HTML", reply_markup=_usage_back())
        return
    parsed = _parse_nodes(r["data"])
    _, _, period, _code = resolve_usage_period(context)
    if not parsed:
        await query.edit_message_text(
            "📊 <b>Трафик</b>\n\n<i>В панели нет узлов.</i>",
            parse_mode="HTML", reply_markup=_usage_back())
        return
    # Сводка за всё время из старого отдельного экрана «Трафик»:
    # панель считает один общий расход, поэтому всё лежит в «получено».
    # Не получили — экран всё равно открывается, просто без этого блока.
    snap_lines = []
    try:
        from services.panel import get_traffic_snapshot
        snap = await get_traffic_snapshot()
    except Exception:
        snap = {}
    if snap.get("ok") and snap.get("clients"):
        clients = snap["clients"]
        total = sum(up + down for up, down in clients.values())
        top = sorted(clients.items(),
                     key=lambda kv: kv[1][0] + kv[1][1], reverse=True)[:10]
        labels = await _resolve_usage_labels([e for e, _ in top])
        snap_lines = [
            f"Всего по всем клиентам: <b>{_fmt_gb(total)}</b>"
            f" · клиентов: <b>{len(clients)}</b>",
            "<i>Счётчики панели с последнего сброса.</i>",
            "",
            "<b>Топ-10 за всё время:</b>",
        ]
        for i, (email, (up, down)) in enumerate(top, 1):
            shown = labels.get(email) or f"<code>{escape(email)}</code>"
            snap_lines.append(f"{i}. {shown} — <b>{_fmt_gb(up + down)}</b>")
    rows = []
    for n in parsed:
        mark = "⛔ " if n["disabled"] else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{n['name']}",
            callback_data=f"rw_usage_node:{n['uuid']}:1")])
    rows.append([InlineKeyboardButton("🖥 Все ноды",
                                      callback_data="rw_usage_all:1")])
    rows.append([InlineKeyboardButton(f"📅 Период: {period}",
                                      callback_data="rw_usage_period")])
    rows.append([InlineKeyboardButton("🔄 Обновить",
                                      callback_data="rw_usage")])
    rows.append([InlineKeyboardButton("◀️ К логам",
                                      callback_data="ctl_menu")])
    text = "\n".join(
        ["📊 <b>Трафик</b>", ""]
        + snap_lines + ([""] if snap_lines else [])
        + [f"Период: <b>{period}</b>", "",
           "Выбери узел — покажу каждого пользователя (имя, @username, "
           "TG ID и срок подписки из базы бота) и сколько он потратил "
           "на этом узле за период. «Все ноды» — суммарно по всем узлам."])
    await query.edit_message_text(
        text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


async def handle_rw_usage_period(query, context=None):
    """Выбор периода: пресеты и свой диапазон."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    _, _, period, code = resolve_usage_period(context)
    rows = []
    for preset in ("month", "prev", "7d", "30d", "90d"):
        mark = "✅ " if preset == code else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{_USAGE_PERIOD_NAMES[preset]}",
            callback_data=f"rw_usage_set:{preset}")])
    rows.append([InlineKeyboardButton(
        f"{'✅ ' if code == 'custom' else ''}✏️ Свой период…",
        callback_data="rw_usage_custom")])
    rows.append([InlineKeyboardButton("◀️ К узлам",
                                      callback_data="rw_usage")])
    await query.edit_message_text(
        "📅 <b>Период потребления</b>\n\n"
        f"Сейчас: <b>{period}</b>\n\n"
        "Выбери готовый период или пришли свой диапазон датами.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


async def handle_rw_usage_set(query, context, code: str):
    """Пресет периода -> обратно к выбору узла с новым периодом."""
    if context is not None:
        context.user_data["rw_usage_period"] = code
    await handle_rw_usage(query, context)


async def handle_rw_usage_custom(query, context):
    """Просьба прислать свой диапазон дат."""
    from core.states import AWAITING_RW_USAGE_PERIOD
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context is not None:
        context.user_data["state"] = AWAITING_RW_USAGE_PERIOD
    await query.edit_message_text(
        "✏️ <b>Свой период</b>\n\n"
        "Пришли диапазон, например:\n"
        "<code>01.09.2026 — 15.09.2026</code>\n\n"
        "<i>Подойдёт и формат 2026-09-01 — 2026-09-15.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К периодам",
                                  callback_data="rw_usage_period")]]))


async def handle_rw_usage_node(query, context, node_uuid: str, page: int = 1):
    """Пользователи одного узла за выбранный период, по убыванию ГБ."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    start, end, period, _code = resolve_usage_period(context)
    await query.edit_message_text("📊 Загружаю потребление…")
    nodes_r = await nodes()
    name = node_uuid
    if nodes_r["ok"]:
        for n in _parse_nodes(nodes_r["data"]):
            if n["uuid"] == node_uuid:
                name = n["name"]
                break
    r = await node_users_usage(node_uuid, start, end)
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить потребление</b>\n\n"
            f"<code>{escape(str(r.get('error'))[:300])}</code>\n\n"
            "<i>Если ошибка 403 — у API-токена в панели нет права "
            "node-users-usage на чтение: его включают в настройках "
            "токена в панели.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К узлам",
                                      callback_data="rw_usage")]]))
        return
    items = _usage_items(r["data"])
    total_pages = max(1, (len(items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(max(1, page), total_pages)
    page_items = items[(page - 1) * _PAGE_SIZE:page * _PAGE_SIZE]
    labels = await _resolve_usage_labels([u for u, _ in page_items])
    await query.edit_message_text(
        _usage_text(name, period, items, page, total_pages, labels),
        parse_mode="HTML",
        reply_markup=_usage_page_keyboard(
            node_uuid, page, total_pages,
            f"rw_usage_node:{node_uuid}"))


async def handle_rw_usage_all(query, context, page: int = 1):
    """Пользователи суммарно по всем узлам за выбранный период."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    start, end, period, _code = resolve_usage_period(context)
    await query.edit_message_text("📊 Загружаю потребление по всем узлам…")
    nodes_r = await nodes()
    if not nodes_r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить узлы</b>\n\n"
            f"<code>{escape(str(nodes_r.get('error'))[:300])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К узлам",
                                      callback_data="rw_usage")]]))
        return
    parsed = _parse_nodes(nodes_r["data"])
    if not parsed:
        await query.edit_message_text(
            "📊 <b>Потребление ГБ</b>\n\n<i>В панели нет узлов.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К узлам",
                                      callback_data="rw_usage")]]))
        return
    r = await nodes_users_usage([n["uuid"] for n in parsed], start, end)
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить потребление</b>\n\n"
            f"<code>{escape(str(r.get('error'))[:300])}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К узлам",
                                      callback_data="rw_usage")]]))
        return
    items = _usage_items(r["data"])
    total_pages = max(1, (len(items) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(max(1, page), total_pages)
    page_items = items[(page - 1) * _PAGE_SIZE:page * _PAGE_SIZE]
    labels = await _resolve_usage_labels([u for u, _ in page_items])
    text = _usage_text("Все ноды", period, items, page, total_pages, labels)
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=_usage_page_keyboard(
            None, page, total_pages, "rw_usage_all"))


async def users_page(start: int = 0, size: int = 500) -> dict:
    """Страница пользователей. Больше 1000 за раз панель не отдаёт."""
    return await _request("GET", f"{USERS}?start={int(start)}&size={min(int(size), 1000)}")


async def all_users(limit: int = 5000) -> list:
    """Все пользователи панели — для статистики и списка онлайна."""
    out, start = [], 0
    while start < limit:
        r = await users_page(start, 500)
        if not r["ok"]:
            break
        data = r["data"] or {}
        chunk = data.get("users") or []
        out += chunk
        total = int(data.get("total") or 0)
        start += len(chunk)
        if not chunk or start >= total:
            break
    return out


# ── Точечная синхронизация с панелью ─────────────────────────────────────────

def _panel_expire_to_bot(raw) -> str | None:
    """expireAt панели (ISO) → формат базы бота DD.MM.YYYY HH:MM:SS."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d.%m.%Y %H:%M:%S")
    except (ValueError, TypeError):
        return None


async def run_panel_sync() -> dict:
    """Сверяет базу бота с панелью: панель — источник правды для полей,
    которые она хранит. Обновляет у платных и админских подписок uuid,
    sub_id, sub_url, expire_date, limit_hwid, total_gb (у платных заодно
    period_end вслед за expire_date — как при обычном продлении).

    Сознательно НЕ делается, чтобы одна ошибка не унесла подписки:
    — не меняются статусы, продления, LTE-настройки и чёрный список;
    — не удаляются подписки, которых нет в панели;
    — не создаются подписки для пользователей панели без записи в боте;
    — сквады не трогаются (там живёт LTE-fallback).
    Обе «подозрительные» группы только попадают в отчёт.
    """
    if not is_configured():
        return {"ok": False, "error": "панель не настроена"}
    probe = await users_page(0, 1)
    if not probe["ok"]:
        return {"ok": False, "error": str(probe.get("error"))}
    panel_users = await all_users()
    if not panel_users and (probe.get("data") or {}).get("total"):
        return {"ok": False, "error": "не удалось забрать пользователей панели"}

    import aiosqlite
    from core.database import DB_PATH
    from paidsub.storage import update_paid_sub_field
    from adminsub.storage import update_sub_field

    tables = []
    async with aiosqlite.connect(DB_PATH) as db:
        for table in ("paid_subs", "admin_subs"):
            async with db.execute(
                    f"SELECT id, tg_id, email, uuid, sub_id, sub_url, expire_date,"
                    f" limit_hwid, total_gb FROM {table} ORDER BY id") as cur:
                tables.append((table, await cur.fetchall()))

    # Карта «имя в панели → строка базы»: имя в панели — это
    # make_username(email, 0), то же правило, что при выдаче.
    by_name, by_tg = {}, {}
    for table, rows in tables:
        for row in rows:
            by_name.setdefault(make_username(row[2] or "", 0), []).append((table, row))
            if row[1] is not None:
                by_tg.setdefault(int(row[1]), []).append((table, row))

    checked = updated_subs = updated_fields = disabled = 0
    orphans, missing, examples = [], [], []
    matched_keys = set()

    def _match(pu: dict):
        uname = pu.get("username") or ""
        cands = by_name.get(make_username(uname, 0), [])
        if len(cands) == 1:
            return cands[0]
        if not cands:
            # Запасной путь: у части подписок email в базе не совпадает с
            # именем в панели (длинные ники обрезаются) — тогда ищем по
            # telegramId, но только если такой подписчик ровно один.
            tid = pu.get("telegramId")
            if tid is not None:
                free = [c for c in by_tg.get(int(tid), [])
                        if (c[0], c[1][0]) not in matched_keys]
                if len(free) == 1:
                    return free[0]
        return None

    for pu in panel_users:
        m = _match(pu)
        if m is None:
            orphans.append(pu.get("username") or "без имени")
            continue
        table, row = m
        matched_keys.add((table, row[0]))
        checked += 1
        if (pu.get("status") or "") != "ACTIVE":
            disabled += 1
        want = {}
        if pu.get("vlessUuid") and pu["vlessUuid"] != row[3]:
            want["uuid"] = pu["vlessUuid"]
        if pu.get("shortUuid") and pu["shortUuid"] != row[4]:
            want["sub_id"] = pu["shortUuid"]
        if pu.get("subscriptionUrl") and pu["subscriptionUrl"] != row[5]:
            want["sub_url"] = pu["subscriptionUrl"]
        exp = _panel_expire_to_bot(pu.get("expireAt"))
        if exp and exp != row[6]:
            want["expire_date"] = exp
        if pu.get("hwidDeviceLimit") is not None and \
                int(pu["hwidDeviceLimit"]) != int(row[7] or 0):
            want["limit_hwid"] = int(pu["hwidDeviceLimit"])
        if pu.get("trafficLimitBytes") is not None:
            gb = int(round(int(pu["trafficLimitBytes"]) / 1024 ** 3))
            if gb != int(row[8] or 0):
                want["total_gb"] = gb
        if not want:
            continue
        upd = update_paid_sub_field if table == "paid_subs" else update_sub_field
        for field, value in want.items():
            await upd(row[0], field, value)
        if table == "paid_subs" and "expire_date" in want:
            await update_paid_sub_field(row[0], "period_end", want["expire_date"])
        updated_subs += 1
        updated_fields += len(want)
        if len(examples) < 5:
            fields = ", ".join(want)
            examples.append(f"{row[2]}: {fields}")

    for table, rows in tables:
        for row in rows:
            if (table, row[0]) not in matched_keys:
                missing.append(f"{'платная' if table == 'paid_subs' else 'админская'}: {row[2]}")

    return {"ok": True, "panel_total": len(panel_users), "checked": checked,
            "updated_subs": updated_subs, "updated_fields": updated_fields,
            "disabled": disabled, "orphans": orphans, "missing": missing,
            "examples": examples}


def panel_sync_report_text(res: dict, title: str = "🔄 Синхронизация с панелью") -> str:
    """Текст отчёта по результату run_panel_sync() — один для ручного
    запуска и для уведомления о плановой синхронизации."""
    if not res.get("ok"):
        return (f"❌ <b>{title}</b>\n\n"
                f"<blockquote>{escape(str(res.get('error'))[:300])}</blockquote>\n\n"
                "<i>База не менялась: при ошибке панели ничего не трогаем.</i>")
    lines = [f"✅ <b>{title}</b>", "",
             "<blockquote>"
             f"Пользователей в панели: <b>{res['panel_total']}</b>\n"
             f"Сверено подписок: <b>{res['checked']}</b>\n"
             f"Обновлено подписок: <b>{res['updated_subs']}</b> "
             f"(полей: {res['updated_fields']})</blockquote>"]
    if res["examples"]:
        shown = "\n".join(escape(e) for e in res["examples"])
        lines += ["", "✏️ <b>Что поменялось</b>", f"<blockquote>{shown}</blockquote>"]
    if res["disabled"]:
        lines += ["", f"⏸ В панели отключено подписок: <b>{res['disabled']}</b> "
                      "(статусы в базе не трогаем — заморозка и так читается из панели)."]
    if res["orphans"]:
        shown = "\n".join(escape(o) for o in res["orphans"][:5])
        lines += ["", f"👻 В панели есть, а в базе нет: <b>{len(res['orphans'])}</b>",
                  f"<blockquote>{shown}</blockquote>"]
        if len(res["orphans"]) > 5:
            lines.append(f"<i>…и ещё {len(res['orphans']) - 5}</i>")
    if res["missing"]:
        shown = "\n".join(escape(m) for m in res["missing"][:5])
        lines += ["", f"⚠️ В базе есть, а в панели нет: <b>{len(res['missing'])}</b>",
                  f"<blockquote>{shown}</blockquote>"]
        if len(res["missing"]) > 5:
            lines.append(f"<i>…и ещё {len(res['missing']) - 5}</i>")
    lines += ["", "<i>Синхронизируются только поля панели: uuid, ссылка, срок, "
              "лимит устройств и лимит трафика. Статусы, продления и LTE-настройки "
              "не меняются, ничего не удаляется и не создаётся само.</i>"]
    return "\n".join(lines)



async def run_full_sync(bot) -> dict:
    """Полная синхронизация одной кнопкой (решение владельца 2026-11-19):
    всё, что бот сверяет с внешним миром, одним проходом. Шаги независимы:
    падение одного не отменяет остальные, у каждого своя секция отчёта.
      1) панель → бот: подписки (поля панели в базу);
      2) бот → панель: ники и юзернеймы в описания клиентов;
      3) ресурсы: панель, выдача подписок и все узлы — живы ли;
      4) хосты панели: состав, отключённые, скрытые;
      5) сквады: выбранные в боте против живых в панели;
      6) сайт: пересборка и деплой, если что-то поменялось;
      7) общий чёрный список: скачать и применить (если включён);
      8) сверка Platega: только отчёт, исправления — отдельной кнопкой.
    """
    out: dict = {}
    try:
        out["panel"] = await run_panel_sync()
    except Exception as e:
        out["panel"] = {"ok": False, "error": str(e)[:200]}

    if bot is not None and (out.get("panel") or {}).get("ok"):
        try:
            from services.panel import refresh_panel_descriptions, tg_chat_resolver
            out["names"] = await refresh_panel_descriptions(
                resolve_chat=await tg_chat_resolver(bot))
        except Exception as e:
            out["names"] = {"ok": False, "error": str(e)[:200]}
    else:
        out["names"] = None

    try:
        from services.panel import probe_servers
        out["probe"] = await probe_servers()
    except Exception as e:
        out["probe"] = {"error": str(e)[:200]}

    try:
        out["hosts"] = await list_hosts()
    except Exception as e:
        out["hosts"] = {"ok": False, "error": str(e)[:200]}

    try:
        sq = await list_squads()
        chosen = set(settings()["squads"])
        live = {s["uuid"] for s in sq.get("squads") or []}
        out["squads"] = {**sq, "chosen": len(chosen),
                         "missing": sorted(chosen - live)}
    except Exception as e:
        out["squads"] = {"ok": False, "error": str(e)[:200]}

    try:
        from web.site_deploy import _build_and_maybe_deploy, configured as site_on
        if not site_on():
            out["site"] = {"status": "not_configured"}
        elif not load_config().get("site_deployed_at"):
            out["site"] = {"status": "not_deployed"}
        elif bot is None:
            out["site"] = {"status": "no_bot"}
        else:
            me = await bot.get_me()
            status, _res = await _build_and_maybe_deploy(me.username)
            out["site"] = {"status": status}
    except Exception as e:
        out["site"] = {"status": "failed", "error": str(e)[:200]}

    try:
        from features.blacklist import remote_on, sync_remote
        if not remote_on():
            out["blacklist"] = {"status": "off"}
        elif bot is None:
            out["blacklist"] = {"status": "no_bot"}
        else:
            out["blacklist"] = await sync_remote(bot)
    except Exception as e:
        out["blacklist"] = {"ok": False, "error": str(e)[:200]}

    try:
        from handlers.reconcile import run_reconciliation
        out["reconcile"] = await run_reconciliation()
    except Exception as e:
        out["reconcile"] = {"error": str(e)[:200]}

    # отметка о запуске — для «последнего отчёта» в обеих админках
    try:
        cfg = load_config()
        cfg["panel_sync_last_run"] = datetime.now().isoformat(timespec="seconds")
        p = out.get("panel") or {}
        cfg["panel_sync_last_report"] = {
            "at": cfg["panel_sync_last_run"],
            "checked": p.get("checked", 0),
            "updated": p.get("updated_subs", 0),
            "orphans": len(p.get("orphans") or []),
            "missing": len(p.get("missing") or []),
            "names_updated": (out.get("names") or {}).get("updated", 0),
            "names_errors": len((out.get("names") or {}).get("errors") or []),
        }
        save_config(cfg)
    except Exception:
        pass
    return out


def full_sync_report_text(res: dict) -> str:
    """Единый отчёт полной синхронизации по всем секциям."""
    parts = [panel_sync_report_text(res.get("panel") or {},
                                    "🔄 Полная синхронизация · подписки")]

    names = res.get("names")
    if names is None:
        parts.append("\n👤 <b>Ники и юзернеймы</b>\n\n"
                     "<blockquote>Пропущено: панель недоступна.</blockquote>")
    elif names.get("ok"):
        parts.append(
            "\n👤 <b>Ники и юзернеймы (бот → панель)</b>\n\n"
            "<blockquote>"
            f"Проверено подписок: <b>{names['checked']}</b>\n"
            f"Обновлено описаний: <b>{names['updated']}</b>\n"
            f"С ошибкой: <b>{len(names.get('errors') or [])}</b>"
            "</blockquote>")
        if names.get("errors"):
            shown = "\n".join(str(e)[:120] for e in names["errors"][:5])
            parts.append(f"<blockquote>{shown}</blockquote>")
    else:
        parts.append("\n👤 <b>Ники и юзернеймы</b>\n\n"
                     f"<blockquote>{escape(str(names.get('error') or 'ошибка'))}</blockquote>")

    probe = res.get("probe") or {}
    if probe.get("error"):
        parts.append("\n🖥 <b>Ресурсы и узлы</b>\n\n"
                     f"<blockquote>Проверка не удалась: {escape(str(probe['error']))}</blockquote>")
    else:
        panel = probe.get("panel") or {}
        sub = probe.get("sub") or {}
        nodes = probe.get("nodes") or []
        lines = ["\n🖥 <b>Ресурсы и узлы</b>", "", "<blockquote>",
                 f"Панель: {'✅ отвечает' if panel.get('ok') else '❌ недоступна'}"
                 f" · {panel.get('ms', '—')} мс\n"
                 f"Выдача подписок: {'✅ отвечает' if sub.get('ok') else '❌ недоступна'}"
                 f" · {sub.get('ms', '—')} мс"]
        if nodes:
            lines.append("")
            for n in nodes:
                if not n.get("enabled"):
                    state = "⏸ выключен"
                elif n.get("reachable"):
                    state = "✅ онлайн"
                else:
                    state = "❌ " + (n.get("error") or "недоступен")
                lines.append(
                    f"{n.get('tag')}: <b>{state}</b> · {n.get('host') or ''}"
                    f" · онлайн-клиентов: {n.get('clients', 0)}")
        else:
            lines.append("Узлов панель не отдала.")
        lines.append("</blockquote>")
        parts.append("\n".join(lines))

    hosts = res.get("hosts") or {}
    if hosts.get("ok"):
        hs = hosts.get("hosts") or []
        off = [h for h in hs if h.get("isDisabled")]
        hidden = [h for h in hs if h.get("isHidden")]
        block = (f"Всего: <b>{len(hs)}</b> · отключено: <b>{len(off)}</b>"
                 f" · скрыто: <b>{len(hidden)}</b>")
        if off:
            block += "\nОтключены: " + ", ".join(
                escape(str(h.get("remark") or h.get("address") or "?")) for h in off[:10])
        parts.append("\n🌐 <b>Хосты в панели</b>\n\n"
                     f"<blockquote>{block}</blockquote>")
    else:
        parts.append("\n🌐 <b>Хосты в панели</b>\n\n"
                     f"<blockquote>Не получить: {escape(str(hosts.get('error') or 'ошибка'))}</blockquote>")

    squads = res.get("squads") or {}
    if squads.get("ok"):
        block = (f"В панели: <b>{len(squads.get('squads') or [])}</b> · "
                 f"выбрано для выдачи: <b>{squads.get('chosen', 0)}</b>")
        if squads.get("missing"):
            block += ("\n⚠️ Выбранных в панели больше нет: "
                      f"<b>{len(squads['missing'])}</b> — проверь сквады в Remnawave.")
        parts.append("\n👥 <b>Сквады</b>\n\n"
                     f"<blockquote>{block}</blockquote>")
    else:
        parts.append("\n👥 <b>Сквады</b>\n\n"
                     f"<blockquote>Не получить: {escape(str(squads.get('error') or 'ошибка'))}</blockquote>")

    site = res.get("site") or {}
    site_text = {
        "unchanged": "✅ Актуален, изменений нет — деплой не понадобился.",
        "deployed": "✅ Обновлён: залита свежая версия.",
        "not_deployed": "Ещё ни разу не развёрнут — пропускаю (деплой делается вручную).",
        "not_configured": "Не настроен — пропускаю.",
        "no_bot": "Пропущено: нет доступа к боту.",
    }.get(site.get("status"),
          "❌ Не удалось: " + str(site.get("error") or site.get("status") or "ошибка"))
    parts.append("\n🌍 <b>Сайт и кабинет</b>\n\n"
                 f"<blockquote>{site_text}</blockquote>")

    bl = res.get("blacklist") or {}
    if bl.get("status") == "off":
        bl_text = "Общий список выключен — пропускаю."
    elif bl.get("status") == "no_bot":
        bl_text = "Пропущено: нет доступа к боту."
    elif bl.get("ok"):
        stopped = (len(bl.get("trials_stopped") or [])
                   + len(bl.get("paid_stopped") or [])
                   + len(bl.get("admin_stopped") or []))
        bl_text = (f"✅ Записей в списке: <b>{bl.get('total', 0)}</b> · "
                   f"добавлено: <b>{bl.get('added', 0)}</b> · "
                   f"снято: <b>{bl.get('removed', 0)}</b> · "
                   f"остановлено подписок: <b>{stopped}</b> · "
                   f"восстановлено: <b>{len(bl.get('restored') or [])}</b>")
    else:
        bl_text = "❌ Не удалось: " + str(bl.get("error") or "ошибка")
    parts.append("\n🚫 <b>Чёрный список</b>\n\n"
                 f"<blockquote>{bl_text}</blockquote>")

    rec = res.get("reconcile") or {}
    if rec.get("error"):
        rec_text = "❌ Не удалось: " + str(rec["error"])
    else:
        issues = rec.get("issues") or []
        rec_text = (f"Проверено счетов: <b>{rec.get('checked', 0)}</b> · "
                    f"расхождений: <b>{len(issues)}</b>")
        if issues:
            rec_text += ("\n<i>Исправления отсюда не применяются — они в "
                         "разделе сверки, по кнопке.</i>")
    parts.append("\n🔍 <b>Сверка с Platega</b>\n\n"
                 f"<blockquote>{rec_text}</blockquote>")
    return "\n".join(parts)


# ── Подготовка данных подписки ────────────────────────────────────────────────

def make_username(email: str, tg_id: int) -> str:
    """Имя для панели: 3–36 символов, только буквы, цифры, _ и -."""
    base = re.sub(r"[^a-zA-Z0-9_-]", "", str(email or ""))[:36]
    if len(base) < 3:
        base = f"user_{tg_id}"[:36]
    return base


def to_iso(raw: str) -> str:
    """Дату подписки отдаём с часовым поясом сервера, чтобы панель
    не сдвинула срок на несколько часов."""
    from paidsub.storage import parse_sub_date
    dt = parse_sub_date(raw) or datetime.now()
    return dt.astimezone().isoformat(timespec="seconds")


# ── Экраны админки ────────────────────────────────────────────────────────────

def _back():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")]])


def _usage_back():
    """Возврат из просмотра потребления: он живёт в «Логах»,
    а не в меню Remnawave, поэтому ведём туда, а не в rw_menu."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К логам", callback_data="ctl_menu")]])


async def handle_rw_menu(query, context=None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    s = settings()
    url = f"<code>{escape(s['url'])}</code>" if s["url"] else "не задан"
    token = "задан" if s["token"] else "не задан"
    squads = f"выбрано <b>{len(s['squads'])}</b>" if s["squads"] else "не выбраны"

    lines = ["🖥 <b>Панель Remnawave</b>", "",
             "<blockquote>"
             f"🌐 Адрес: {url}\n"
             f"🔑 Токен: <b>{token}</b>\n"
             f"👥 Сквады: {squads}</blockquote>", "",
             "<i>Через неё идут выдача, продление, лимиты устройств, "
             "перевыпуск ключа и заморозка.</i>"]

    kb = [[InlineKeyboardButton("🌐 Адрес панели", callback_data="rw_url"),
           InlineKeyboardButton("🔑 Токен", callback_data="rw_token")]]
    if is_configured():
        kb.append([InlineKeyboardButton("🔗 Основные ссылки", callback_data="rw_links")])
        kb.append([InlineKeyboardButton("🔀 Вариант моста (А/Б)", callback_data="rw_bridge_variant")])
        kb.append([InlineKeyboardButton("🏷 Теги подписчиков", callback_data="rw_tags")])
        kb.append([InlineKeyboardButton("🔌 Проверить", callback_data="rw_test")])
        kb.append([InlineKeyboardButton("🩺 Здоровье узлов", callback_data="healthcheck")])
        kb.append([InlineKeyboardButton("📉 Падения и сбои", callback_data="rw_downtime")])
        kb.append([InlineKeyboardButton("☁️ Яндекс Клауд", callback_data="rw_yandex")])
        kb.append([InlineKeyboardButton("🔄 Синхронизация",
                                        callback_data="panel_sync_menu")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


# ── Основные ссылки ─────────────────────────────────────────────────────────
# Справка по адресам проекта: панель, сайт, домены подписки, ноды и хосты.
# Авто-значения: rw_url и webapi_public из конфига, домены — константы
# config; ноды и хосты — живьём из панели. Ручные правки — config.main_links
# (те же, что редактируются в веб-админке, PATCH /links): перекрывают авто.

LINK_FIELDS = (
    ("panel_url", "🌐 Панель Remnawave", "url"),
    ("site_url", "🏠 Сайт и кабинет", "url"),
    ("key_domain", "🔑 Подписка — основной домен (origin)", "domain"),
    ("sub_domain", "☁️ Подписка — через CDN", "domain"),
)


def links_values() -> tuple[dict, dict, dict]:
    """(auto, overrides, effective) для основных ссылок."""
    from config import SUB_DISPLAY_DOMAIN, SUB_STORED_DOMAIN, load_config
    cfg = load_config()
    auto = {
        "panel_url": (cfg.get("rw_url") or "").rstrip("/"),
        "site_url": (cfg.get("webapi_public") or "").rstrip("/"),
        "key_domain": SUB_STORED_DOMAIN,
        "sub_domain": SUB_DISPLAY_DOMAIN,
    }
    overrides = {k: str(v).strip() for k, v in (cfg.get("main_links") or {}).items()
                 if isinstance(v, str) and str(v).strip()}
    eff = {k: overrides.get(k) or auto.get(k) or "" for k, _, _ in LINK_FIELDS}
    return auto, overrides, eff


def save_link_override(key: str, value: str) -> None:
    """Сохранить/очистить (value="") одну правку основной ссылки."""
    from config import atomic_update

    def _apply(cfg):
        cur = dict(cfg.get("main_links") or {})
        cur[key] = value
        cfg["main_links"] = cur
    atomic_update(_apply)


async def handle_rw_links(query, context=None):
    """Экран «Основные ссылки»: адреса + живые ноды и хосты из панели."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    _auto, overrides, eff = links_values()
    lines = ["🔗 <b>Основные ссылки</b>", ""]
    for key, label, kind in LINK_FIELDS:
        val = eff[key]
        shown = val if kind == "url" or "://" in val else f"https://{val}"
        mark = " <i>(правка)</i>" if key in overrides else ""
        lines.append(f"{label}: <code>{escape(shown) if shown else '—'}</code>{mark}")
    nres = await nodes()
    raw = nres.get("data") if nres.get("ok") else None
    items = raw if isinstance(raw, list) else (raw or {}).get("response") or (raw or {}).get("nodes") or []
    lines += ["", "<b>Ноды</b> <i>(из панели)</i>"]
    if items:
        for n in items:
            if not isinstance(n, dict):
                continue
            if n.get("isDisabled"):
                st = "⚫ выключена"
            elif n.get("isConnected") and n.get("isXrayRunning") is not False:
                st = "🟢 онлайн"
            else:
                st = "🔴 офлайн"
            online = n.get("usersOnline")
            tail = f" · {online} чел." if online is not None else ""
            lines.append(f"• {escape(n.get('name') or '')} — "
                         f"<code>{escape(n.get('address') or '')}</code> · {st}{tail}")
    else:
        lines.append("<i>Панель не ответила.</i>")
    hres = await list_hosts()
    hosts = hres.get("hosts") if hres.get("ok") else []
    lines += ["", "<b>Хосты подписки</b> <i>(из панели)</i>"]
    if hosts:
        for x in hosts:
            stub = x.get("port") == 1234 or x.get("address") == "12345"
            addr = "служебный" if stub else f"{x.get('address') or ''}:{x.get('port') or '—'}"
            st = "⚫ выкл" if x.get("isDisabled") else "🟢 вкл"
            sni = f" · SNI <code>{escape(x.get('sni') or '')}</code>" if x.get("sni") else ""
            lines.append(f"• {escape(x.get('remark') or '')} — <code>{escape(addr)}</code>{sni} · {st}")
    else:
        lines.append("<i>Панель не ответила.</i>")
    kb = [
        [InlineKeyboardButton("✏️ Поправить", callback_data="rw_links_edit"),
         InlineKeyboardButton("🔄 Обновить", callback_data="rw_links")],
        [InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")],
    ]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_rw_links_edit(query, context=None):
    """Меню правок основных ссылок: по кнопке на поле + сброс всех правок."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    _auto, overrides, eff = links_values()
    lines = ["✏️ <b>Поправить основные ссылки</b>", "",
             "<i>Правка перекрывает авто-значение и действует и здесь, "
             "и в веб-админке. Серверы правятся в самой панели — здесь "
             "они только показываются.</i>"]
    kb = []
    for key, label, _kind in LINK_FIELDS:
        mark = " (правка)" if key in overrides else ""
        kb.append([InlineKeyboardButton(f"{label}{mark}", callback_data=f"rw_link_set:{key}")])
    if overrides:
        kb.append([InlineKeyboardButton("🧹 Сбросить все правки", callback_data="rw_links_reset")])
    kb.append([InlineKeyboardButton("◀️ К ссылкам", callback_data="rw_links")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_rw_link_set(query, context, key: str):
    """Запросить новое значение одного поля основной ссылки."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.states import AWAITING_LINK_FIELD
    spec = {k: (label, kind) for k, label, kind in LINK_FIELDS}.get(key)
    if spec is None:
        return
    label, kind = spec
    auto, overrides, eff = links_values()
    context.user_data["state"] = AWAITING_LINK_FIELD
    context.user_data["link_field"] = key
    hint = ("адрес целиком, например <code>https://panel.drbl.tech</code>"
            if kind == "url" else "домен без https://, например <code>sub.drbl.tech</code>")
    lines = [f"✏️ <b>{label}</b>", "",
             f"Сейчас: <code>{escape(eff[key] or '—')}</code>"
             + (" (правка)" if key in overrides else " (авто)"),
             f"Авто-значение: <code>{escape(auto[key] or '—')}</code>", "",
             f"Пришли новое значение — {hint}.",
             "Пришли <code>-</code>, чтобы убрать правку и вернуть авто."]
    kb = [[InlineKeyboardButton("◀️ Отмена", callback_data="rw_links_edit")]]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_rw_links_reset(query, context=None):
    """Сбросить все ручные правки основных ссылок."""
    from config import atomic_update

    def _apply(cfg):
        cfg["main_links"] = {}
    atomic_update(_apply)
    await handle_rw_links(query, context)


# Пометка хостов бывшего аварийного «плана Б» (функция удалена 2026-11-21
# по решению пользователя: вход через DE на мобильном интернете бессмыслен).
# Константа осталась, чтобы переключатель варианта моста такие хосты не трогал.
PLAN_B_MARK = "(план Б)"
# Пометка хостов докового моста (вариант Б).
VARIANT_B_MARK = "(вариант Б)"
# Адреса основной линейки: IP oblako и его домен — хост опознаётся по любому.
PLAN_B_MAIN_ADDRESSES = {"187.54.0.243", "most2.tembadr.tech"}


# ── Вариант моста: А (DNAT) ↔ Б (доковый, server-side routing) ─────────────
# Оба варианта — вход через oblako. Вариант А: основная линейка, трафик идёт
# DNAT-пробросом в инбаунды выходных нод. Вариант Б: те же страны через
# официальный мост Remnawave — Xray на oblako сам ведёт трафик в выходные
# ноды по профилю BRIDGE; хосты помечены «(вариант Б)» и в мирное время
# выключены. Переключатель гасит один вариант и поднимает другой; порядок —
# сначала включения, потом выключения, как в плане Б. Аварийный план Б
# (мост DE) сюда не входит и переключателем не трогается.


def _variant_split(hosts):
    # Вариант А — основная линейка на most2 плюс обычный «Автовыбор»:
    # у него адрес-заглушка, поэтому опознаём по названию. LTE-автовыбор
    # ([LTE]) — отдельная система, переключатель его не трогает никогда.
    a_hosts = [h for h in hosts
               if (h["address"] in PLAN_B_MAIN_ADDRESSES
                   or ("Автовыбор" in h["remark"] and "[LTE]" not in h["remark"]))
               and VARIANT_B_MARK not in h["remark"]
               and PLAN_B_MARK not in h["remark"]]
    b_hosts = [h for h in hosts if VARIANT_B_MARK in h["remark"]]
    return a_hosts, b_hosts


async def bridge_variant_state() -> dict:
    r = await list_hosts()
    if not r.get("ok"):
        return {"ok": False}
    a_hosts, b_hosts = _variant_split(r["hosts"])
    return {
        "ok": True,
        "a_hosts": a_hosts,
        "b_hosts": b_hosts,
        "a_on": sum(1 for h in a_hosts if not h["isDisabled"]),
        "b_on": sum(1 for h in b_hosts if not h["isDisabled"]),
    }


async def set_bridge_variant(variant: str) -> dict:
    """variant='b' — трафик на доковый мост, 'a' — обратно на DNAT."""
    st = await bridge_variant_state()
    if not st.get("ok"):
        return {"ok": False, "error": "Панель не ответила"}
    if not st["b_hosts"]:
        return {"ok": False, "error": "Хосты варианта Б в панели не найдены"}
    if not st["a_hosts"]:
        return {"ok": False, "error": "Хосты варианта А в панели не найдены"}
    to_b = variant == "b"
    plan = [(h, not to_b) for h in st["b_hosts"]]
    plan += [(h, to_b) for h in st["a_hosts"]]
    plan.sort(key=lambda t: t[1])  # сначала включения (isDisabled=False)
    changed = failed = 0
    for h, disabled in plan:
        if h["isDisabled"] == disabled:
            continue
        res = await patch_host(h["uuid"], {"isDisabled": disabled})
        if res.get("ok"):
            changed += 1
        else:
            failed += 1
    after = await bridge_variant_state()
    return {"ok": failed == 0, "changed": changed, "failed": failed,
            "state": after}


async def handle_rw_bridge_variant(query, context=None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    st = await bridge_variant_state()
    if not st.get("ok"):
        text = ("🔀 <b>Вариант моста</b>\n\n"
                "<i>Панель не ответила — состояние хостов неизвестно.</i>")
        kb = [[InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")]]
        await query.edit_message_text(text, parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup(kb))
        return
    if st["b_on"] and not st["a_on"]:
        mode = "✅ <b>Сейчас работает вариант Б</b> — доковый мост Remnawave."
    elif st["a_on"] and not st["b_on"]:
        mode = "✅ <b>Сейчас работает вариант А</b> — DNAT через oblako."
    elif st["a_on"] and st["b_on"]:
        mode = "⚠️ <b>Включены оба варианта</b> — клиенты видят и А, и Б."
    else:
        mode = "⚠️ <b>Оба варианта выключены</b> — ни один мост не поднят!"
    lines = ["🔀 <b>Вариант моста</b>", "",
             f"<blockquote>Вариант А (DNAT): включено {st['a_on']} из {len(st['a_hosts'])}\n"
             f"Вариант Б (доковый): включено {st['b_on']} из {len(st['b_hosts'])}</blockquote>",
             "", mode, "",
             "<i>Оба варианта — вход через oblako. А — проброс DNAT в выходные ноды, "
             "Б — официальный мост Remnawave (профиль BRIDGE). Вариант Б — резерв на случай, "
             "если DNAT-путь сломается.</i>"]
    kb = []
    if st["a_hosts"] and st["b_hosts"]:
        if not st["b_on"]:
            kb.append([InlineKeyboardButton("🔀 Включить вариант Б (доковый)",
                                            callback_data="rw_variant_b")])
        if st["b_on"] or not st["a_on"]:
            kb.append([InlineKeyboardButton("↩️ Вернуть вариант А (DNAT)",
                                            callback_data="rw_variant_a")])
    kb.append([InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_rw_bridge_variant_set(query, context, variant: str):
    await query.edit_message_text("⏳ Переключаю хосты…")
    res = await set_bridge_variant(variant)
    if not res.get("ok") and not res.get("state"):
        await query.edit_message_text(
            f"❌ <b>Не получилось переключить</b>\n\n<i>{escape(res.get('error') or 'ошибка панели')}</i>",
            parse_mode="HTML",
            reply_markup=_back())
        return
    st = res.get("state") or {}
    head = ("🔀 <b>Вариант Б включён</b> — трафик идёт через доковый мост Remnawave."
            if variant == "b" else
            "✅ <b>Вариант А возвращён</b> — трафик идёт через DNAT (oblako).")
    lines = [head, "",
             f"<blockquote>Переключено хостов: {res.get('changed', 0)}"
             + (f"\n⚠️ Не удалось переключить: {res['failed']}" if res.get("failed") else "")
             + f"\nВариант А: включено {st.get('a_on', '?')} из {len(st.get('a_hosts') or [])}"
             f"\nВариант Б: включено {st.get('b_on', '?')} из {len(st.get('b_hosts') or [])}</blockquote>",
             "",
             "<i>Клиенты подхватят новые хосты при следующем обновлении подписки в приложении.</i>"]
    from core.log_channel import send_log
    try:
        await send_log(context.bot,
                       ("🔀 <b>Включён вариант Б</b> — хосты переведены на доковый мост Remnawave"
                        if variant == "b" else
                        "✅ <b>Возвращён вариант А</b> — хосты переведены обратно на DNAT")
                       + f" (переключено: {res.get('changed', 0)})")
    except Exception:
        pass
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=_back())


async def handle_rw_tags(query, context=None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from services.panel_tags import ALL_TAGS, TAG_LABELS, tag_counters
    counts = await tag_counters()
    rows = "\n".join(f"{TAG_LABELS[t]}: <b>{counts.get(t, 0)}</b>"
                     for t in ALL_TAGS)
    lines = ["🏷 <b>Теги подписчиков</b>", "",
             f"<blockquote>{rows}\nВсего: <b>{counts.get('total', 0)}</b></blockquote>",
             "",
             "<i>Тег стоит у клиента в панели и показывает статус человека. "
             "Счётчики — по данным бота. Кнопка ниже приведёт теги в панели "
             "к этим статусам; дальше бот обновляет тег сам при смене "
             "статуса: оплата, выдача, истечение, бан и разбан.</i>"]
    kb = [[InlineKeyboardButton("🏷 Применить ко всем",
                                 callback_data="rw_tags_apply")],
          [InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")]]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_rw_tags_apply(query, context=None):
    from services.panel_tags import apply_all_tags
    await query.edit_message_text("⏳ Применяю теги всем подписчикам…")
    res = await apply_all_tags()
    counts = res.get("counts") or {}
    rows = "\n".join(f"{t}: {counts.get(t, 0)}"
                     for t in ("BANNED", "TRIAL", "PAID", "ADMIN", "EXPIRED"))
    lines = ["🏷 <b>Теги применены</b>", "",
             f"<blockquote>Обработано людей: {res.get('people', 0)}\n{rows}\n"
             f"Клиентов обновлено: {res.get('updated', 0)}\n"
             f"Без изменений: {res.get('unchanged', 0)}\n"
             f"Ошибок: {res.get('errors', 0)}</blockquote>"]
    if res.get("error_samples"):
        lines += ["", "<i>Первые ошибки: " +
                  escape("; ".join(res["error_samples"])) + "</i>"]
    from core.log_channel import send_log
    try:
        await send_log(context.bot,
                       f"🏷 <b>Теги подписчиков применены ко всем</b> "
                       f"(людей: {res.get('people', 0)}, обновлено клиентов: "
                       f"{res.get('updated', 0)}, ошибок: {res.get('errors', 0)})")
    except Exception:
        pass
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=_back())


async def handle_rw_yandex(query, context=None):
    """Меню «Яндекс Клауд»: CDN-зеркало подписки и белые списки."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    lines = ["☁️ <b>Яндекс Клауд</b>", "",
             "<i>CDN-зеркало страницы подписки и белые списки.</i>"]
    kb = [
        [InlineKeyboardButton("📄 Страница подписки", callback_data="rw_yandex_sub")],
        [InlineKeyboardButton("📋 Белые списки", callback_data="rw_yandex_whitelist")],
        [InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")],
    ]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_rw_yandex_whitelist(query, context=None):
    """Белые списки Яндекс Клауд — по образцу инструкции страницы подписки.

    Два места: поле «Доступ по IP-адресам» в ресурсе CDN (у нас ВЫКЛЮЧЕНО —
    клиенты с любого IP) и белый список edge-IP Яндекса на origin
    (только Яндекс может дёргать XHTTP-порт дубликата ноды).
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    lines = [
        "📋 <b>Белые списки</b>",
        "",
        "В Yandex Cloud CDN белые списки — в двух местах: поле в самом ресурсе",
        "и список IP edge-серверов для origin.",
        "",
        "<b>1. В ресурсе CDN — ВЫКЛЮЧЕНО</b>",
        "Шаг 1 «Основные параметры», поля «Доступ по IP-адресам»,",
        "«Доступ по странам», «Доступ по защищённому токену» — выкл.",
        "для ВСЕХ наших ресурсов: sub.drbl.tech, de1cdn, fin1cdn, se1cdn, ro1cdn.",
        "Клиенты заходят с любого IP по всей России — включишь и впишешь",
        "свой IP, отрежешь всех остальных.",
        "",
        "<b>2. Белый список на origin — IP Яндекса</b>",
        "Origin (нода) должен отвечать ТОЛЬКО edge-серверам Яндекса,",
        "а не кому попало напрямую. Официальный список:",
        "<code>https://tech.cdn.yandex.net/prefixes/yc.json</code>",
        "(дока Яндекса «Диапазоны публичных IP-адресов» → Cloud CDN).",
        "Список меняется — скачивать свежий при каждом применении.",
        "",
        "<b>3. Применить на ноде (дубликат [CDN], порт 8880)</b>",
        "На сервере ноды (Швеция, Румыния, Германия, Финляндия — дубликат):",
        "<code>ufw status</code>",
        "Если выключен — сначала <code>ufw allow 22/tcp</code>, потом",
        "<code>ufw enable</code>, иначе потеряешь SSH.",
        "Затем разрешить Яндекс на 8880:",
        "<code>curl -s https://tech.cdn.yandex.net/prefixes/yc.json | python3 -c \"import json,sys; print('\\n'.join(p for p in json.load(sys.stdin)['prefixes'] if ':' not in p))\" | while read ip; do ufw allow from $ip to any port 8880 proto tcp; done</code>",
        "Правило для 12222 (только IP панели) и порт 22 — НЕ трогать.",
        "Порты основной ноды (VTR, HY2) — тоже не трогать: они прямые, не через CDN.",
        "",
        "<b>4. body-brown (подписка) — НЕ ставится</b>",
        "На 443 висят ещё панель и сайт — белый список на файрволе",
        "отрежет и их. Для зеркала sub.drbl.tech он не нужен:",
        "клиенты идут на sub.drbl.tech, а key.drbl.tech напрямую и так режет DPI.",
        "",
        "<b>5. Проверка</b>",
        "Напрямую на origin-порт с обычного IP — таймаут (закрыто).",
        "Через CDN-домен (se1cdn.drbl.tech:443) — подключается.",
        "Это hardening, без него всё работает — делать после того,",
        "как нода [CDN] уже зелёная в панели.",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К Яндекс Клауд", callback_data="rw_yandex")]]),
        disable_web_page_preview=True)


async def handle_rw_yandex_sub(query, context=None):
    """Страница подписки: зеркало через CDN (Yandex Cloud).

    Подробно по каждому полю: какой сертификат делать,
    что писать в ресурсе CDN, что включать и выключать.
    sub.drbl.tech — основная ссылка подписки, которую бот даёт
    пользователям (кнопка «🪞 Зеркало подписки» в «Моей подписке»
    отдаёт запасной адрес через key.drbl.tech). Кэш в CDN полностью
    выключен — иначе один юзер получит чужой конфиг.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    lines = [
        "📄 <b>Страница подписки — зеркало через CDN</b>",
        "",
        "sub.drbl.tech — основная ссылка подписки, которую бот даёт пользователям",
        "(кнопка «🪞 Зеркало подписки» в «Моей подписке» отдаёт запасной адрес",
        "через key.drbl.tech).",
        "<b>Кэш полностью ВЫКЛЮЧЕН</b> — иначе один юзер получит чужой конфиг.",
        "",
        "<b>1. Сертификат (Certificate Manager)</b>",
        "В Яндексе нужен только один сертификат — для sub.drbl.tech.",
        "Остальные домены проекта (key, vpn, panel) — на Let's Encrypt на сервере, их не трогаем.",
        "Certificate Manager → «Создать сертификат»:",
        "Имя: <code>sub-drbl-tech</code>",
        "Домены: <code>sub.drbl.tech</code>",
        "Тип проверки: DNS.",
        "Нажми «Создать» — Яндекс покажет TXT-запись.",
        "В DNS добавь TXT <code>_acme-challenge.sub.drbl.tech</code> со значением от Яндекса.",
        "Дождись статуса Issued.",
        "",
        "<b>2. Ресурс CDN — шаг 1 «Основные параметры»</b>",
        "Cloud CDN → «Создать ресурс»:",
        "Источник: <code>key.drbl.tech</code>",
        "Протокол для источника: HTTPS.",
        "Заголовок Host: «Свое значение» = <code>key.drbl.tech</code>.",
        "(«Основное доменное имя» — это домен самого ресурса, не источника.)",
        "SNI вручную: выкл.",
        "Доменное имя: <code>sub.drbl.tech</code>",
        "Тип сертификата: «Из Certificate Manager» → <code>sub-drbl-tech</code>.",
        "Нажми «Далее».",
        "",
        "<b>3. Ресурс CDN — шаг 2 «Кэширование»</b>",
        "Кэширование в CDN: <b>ВЫКЛЮЧИТЬ</b> (тумблер).",
        "Кэш браузера: выкл.",
        "(В ссылке токен юзера — кэш даст чужой конфиг.)",
        "Нажми «Далее».",
        "",
        "<b>4. Ресурс CDN — шаг 3 «Заголовки»</b>",
        "Заголовки: ничего не добавлять (x-hwid проходит сам).",
        "Скрытие заголовков: «Не скрывать».",
        "CORS: «Не добавлять».",
        "Методы: GET, HEAD.",
        "Кастомный HTTP-ответ: выкл.",
        "Нажми «Далее», проверь сводку и «Создать ресурс».",
        "",
        "<b>5. DNS</b>",
        "На вкладке «Обзор» ресурса → «Настройки DNS»: скопируй домен вида",
        "<code>xxx.topology.gslb.yccdn.ru</code>.",
        "В DNS: CNAME <code>sub.drbl.tech</code> → этот домен.",
        "Подожди пару минут, пока edge подхватит сертификат",
        "(сразу может дать ERR_CONNECTION_CLOSED — это нормально).",
        "",
        "<b>6. Проверка</b>",
        "<code>curl https://sub.drbl.tech/&lt;uuid&gt;</code> → 200.",
        "Решающий тест: INCY на МТС без VPN обновляет подписку по зеркальной ссылке",
        "(кнопка «🪞 Зеркало подписки» в «Моей подписке»).",
        "",
        "<b>Цена:</b> 150 ₽/мес за ресурс (150 ГБ + 100 млн запросов), сверх — ~1,05 ₽/ГБ.",
        "Основная ссылка — sub.drbl.tech, key.drbl.tech — запасной адрес.",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К Яндекс Клауд", callback_data="rw_yandex")]]),
        disable_web_page_preview=True)


async def handle_panel_sync_menu(query, context=None):
    """Меню «Синхронизация»: всё, что сверяет бота с панелью, в одном месте."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    lines = ["🔄 <b>Синхронизация</b>", "",
             "<blockquote>Запускается <b>только вручную</b> — кнопками ниже. "
             "Само по расписанию ничего не сверяется.</blockquote>", "",
             "<b>Полная синхронизация</b> одним проходом:",
             "🔄 подписки: всё, что поменял в панели (ключи, ссылки, сроки, "
             "лимиты устройств и трафика), переезжает в базу бота;",
             "👤 ники и юзернеймы — проверяются напрямую в Telegram и пишутся "
             "в описания клиентов панели;",
             "🖥 ресурсы и узлы — панель, выдача подписок и все узлы: живы ли, "
             "кто онлайн;",
             "🌐 хосты и сквады панели — состав, отключённые, скрытые, "
             "не пропали ли выбранные;",
             "🌍 сайт и кабинет — пересборка, если что-то поменялось;",
             "🚫 общий чёрный список — скачать и применить;",
             "🔍 сверка с Platega — отчёт о расхождениях."]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Полная синхронизация",
                                  callback_data="panel_sync")],
            [InlineKeyboardButton("👤 Только ники и юзернеймы",
                                  callback_data="panel_names_sync")],
            [InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")]]))


async def handle_panel_names_sync(query, context=None):
    """Актуализация: юзернеймы и ники платных и админских подписок —
    в описание каждого клиента панели, единым форматом со штампом времени.

    Данные берутся живой проверкой в Telegram (getChat по TG ID),
    а не из базы бота: человек мог сменить ник/юзернейм, а боту ещё
    не написать."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if not is_configured():
        await query.answer("Сначала задай адрес панели и токен", show_alert=True)
        return
    bot = getattr(context, "bot", None) if context else None
    if not bot:
        await query.answer("Нужен доступ к Telegram для проверки",
                           show_alert=True)
        return
    await query.edit_message_text(
        "👤 Проверяю каждого человека в Telegram и переписываю описания в панели…")
    from services.panel import refresh_panel_descriptions, tg_chat_resolver
    res = await refresh_panel_descriptions(
        resolve_chat=await tg_chat_resolver(bot))
    errors = res.get("errors") or []
    by_table = res.get("by_table") or {}
    paid = by_table.get("paid_subs", {})
    admin = by_table.get("admin_subs", {})
    lines = ["👤 <b>Юзернеймы и ники актуализированы</b>", "",
             "<blockquote>"
             f"Проверено подписок: <b>{res['checked']}</b> "
             f"(платных: {paid.get('checked', 0)}, "
             f"админских: {admin.get('checked', 0)})\n"
             f"Обновлено описаний: <b>{res['updated']}</b>\n"
             f"С ошибкой: <b>{len(errors)}</b></blockquote>"]
    if errors:
        shown = "\n".join(escape(e[:120]) for e in errors[:5])
        lines += ["", "⚠️ <b>Не получилось</b>", f"<blockquote>{shown}</blockquote>"]
        if len(errors) > 5:
            lines.append(f"<i>…и ещё {len(errors) - 5}</i>")
    lines += ["", "<i>Формат описания в панели:</i>",
              "<code>Drebol VPN · @юзернейм · Ник · TG ID · "
              "Актуализировано ДД.ММ.ГГГГ - ЧЧ.ММ.СС</code>",
              "<i>Ники сверены напрямую с Telegram на момент прогона, а не "
              "взяты из базы бота, — и заодно сохранены в базу, чтобы и "
              "остальные экраны показывали свежие данные. Кого Telegram не "
              "отдал (заблокировал бота, чат не найден), того не трогали: "
              "переписывать описание устаревшими данными было бы враньём. "
              "Имя клиента и ссылка подписки при этом не меняются.</i>"]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Ещё раз", callback_data="panel_names_sync"),
             InlineKeyboardButton("🔄 К синхронизации",
                                  callback_data="panel_sync_menu")],
            [InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")]]))


async def handle_panel_sync(query, context=None):
    """Ручной запуск полной синхронизации: панель, ники, узлы, хосты,
    сквады, сайт, чёрный список и сверка Platega — одним проходом."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if not is_configured():
        await query.answer("Сначала задай адрес панели и токен", show_alert=True)
        return
    await query.edit_message_text(
        "🔄 <b>Полная синхронизация</b>\n\n"
        "Сверяю подписки и ники с панелью, проверяю узлы, хосты и сквады, "
        "обновляю сайт, чёрный список и сверку Platega. Это может занять "
        "минуту-другую…", parse_mode="HTML")
    bot = getattr(context, "bot", None) if context else None
    res = await run_full_sync(bot)
    await query.edit_message_text(
        full_sync_report_text(res), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Ещё раз", callback_data="panel_sync"),
             InlineKeyboardButton("◀️ К синхронизации",
                                  callback_data="panel_sync_menu")]]))


async def handle_rw_url(query, context):
    from core.states import AWAITING_RW_URL
    context.user_data["state"] = AWAITING_RW_URL
    await query.edit_message_text(
        "🌐 <b>Адрес панели Remnawave</b>\n\n"
        "Пришли адрес целиком, например <code>https://panel.drbl.tech</code>.\n"
        "<i>Без /api на конце — бот допишет сам.</i>",
        parse_mode="HTML", reply_markup=_back(),
    )


async def handle_rw_token(query, context):
    from core.states import AWAITING_RW_TOKEN
    context.user_data["state"] = AWAITING_RW_TOKEN
    await query.edit_message_text(
        "🔑 <b>API-токен Remnawave</b>\n\n"
        "Создай токен в панели (Настройки → API-токены) и пришли его сюда.\n\n"
        "⚠️ Сообщение с токеном удалю сразу после сохранения.",
        parse_mode="HTML", reply_markup=_back(),
    )


async def handle_rw_test(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🔌 Проверяю связь с панелью…")
    r = await test_connection()
    if r["ok"]:
        text = ("✅ <b>Панель отвечает</b>\n\n"
                f"<blockquote>Внутренних сквадов: <b>{r['squads']}</b></blockquote>")
    else:
        text = ("❌ <b>Не подключиться</b>\n\n"
                f"<blockquote><code>{escape(str(r.get('error'))[:300])}</code></blockquote>\n\n"
                "<i>Проверь адрес и токен. Если панель за прокси — она должна "
                "отвечать по этому адресу снаружи.</i>")
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Ещё раз", callback_data="rw_test"),
             InlineKeyboardButton("◀️ Назад", callback_data="rw_menu")]]),
    )


async def handle_rw_squads(query, context):
    """Какие сквады выдавать клиентам."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("👥 Загружаю сквады…")
    r = await list_squads()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить список</b>\n\n<code>{escape(str(r.get('error'))[:300])}</code>",
            parse_mode="HTML", reply_markup=_back())
        return

    chosen = set(settings()["squads"])
    rows = []
    for sq in r["squads"]:
        mark = "✅ " if sq["uuid"] in chosen else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{sq['name']} · {sq['inbounds']} инб · {sq['members']} чел",
            callback_data=f"rw_squad:{sq['uuid']}")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="rw_menu")])

    await query.edit_message_text(
        "👥 <b>Сквады для клиентов</b>\n\n"
        "Отметь, какие выдавать. Выбранные получат все новые подписки "
        "и все, кого заводим пачкой.\n\n"
        + ("<i>Ничего не выбрано — панель заведёт людей без доступа.</i>"
           if not chosen else ""),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_rw_squad_toggle(query, context, uuid: str):
    chosen = settings()["squads"]
    if uuid in chosen:
        chosen.remove(uuid)
    else:
        chosen.append(uuid)
    save_settings(rw_squads=chosen)
    await handle_rw_squads(query, context)


