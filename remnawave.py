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
# панель просит паузу между запросами при пачке — переносим неспешно
STEP_PAUSE = 0.08


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
CDN_MONTHLY_GB = LTE_MONTHLY_GB  # старое имя, на всякий случай


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
    """TG ID, зашитый в имя панели: paid_<tg_id>_<username> или
    <tg_id>_<username> у админских подписок. None, если имя не по
    этому шаблону (например, заведено в панели вручную)."""
    m = re.match(r"^(?:paid_)?(\d+)_", panel_username or "")
    return int(m.group(1)) if m else None


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
        import database as db
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
                 InlineKeyboardButton("◀️ К Remnawave",
                                      callback_data="rw_menu")])
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
    """Выбор узла для потребления за выбранный период (по умолчанию —
    текущий месяц)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if not is_configured():
        await query.edit_message_text(
            "❌ <b>Панель не настроена</b>\n\n"
            "Сначала задай адрес и токен в меню Remnawave.",
            parse_mode="HTML", reply_markup=_back())
        return
    await query.edit_message_text("📊 Загружаю узлы…")
    r = await nodes()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить узлы</b>\n\n"
            f"<code>{escape(str(r.get('error'))[:300])}</code>",
            parse_mode="HTML", reply_markup=_back())
        return
    parsed = _parse_nodes(r["data"])
    _, _, period, _code = resolve_usage_period(context)
    if not parsed:
        await query.edit_message_text(
            "📊 <b>Потребление ГБ</b>\n\n<i>В панели нет узлов.</i>",
            parse_mode="HTML", reply_markup=_back())
        return
    rows = []
    for n in parsed:
        mark = "⛔ " if n["disabled"] else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{n['name']}",
            callback_data=f"rw_usage_node:{n['uuid']}:1")])
    rows.append([InlineKeyboardButton("🌐 Все ноды",
                                      callback_data="rw_usage_all:1")])
    rows.append([InlineKeyboardButton(f"📅 Период: {period}",
                                      callback_data="rw_usage_period")])
    rows.append([InlineKeyboardButton("◀️ К Remnawave",
                                      callback_data="rw_menu")])
    await query.edit_message_text(
        "📊 <b>Потребление ГБ</b>\n\n"
        f"Период: <b>{period}</b>\n\n"
        "Выбери узел — покажу каждого пользователя (имя, @username, "
        "TG ID и срок подписки из базы бота) и сколько он потратил "
        "на этом узле. «Все ноды» — суммарно по всем узлам.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


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
    from states import AWAITING_RW_USAGE_PERIOD
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
    from database import DB_PATH
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
        traffic = pu.get("userTraffic") or {}
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


# ── Расписание синхронизации ─────────────────────────────────────────────────

def panel_sync_schedule_text(cfg: dict) -> str:
    mode = cfg.get("panel_sync_mode") or "off"
    if mode == "interval":
        hours = int(cfg.get("panel_sync_interval_hours") or 24)
        if hours % 24 == 0 and hours >= 24:
            days = hours // 24
            return f"каждые {days} дн." if days > 1 else "каждый день"
        return f"каждые {hours} ч."
    if mode == "daily":
        return f"каждый день в {cfg.get('panel_sync_daily_time') or '—'}"
    return "выключено"


def panel_sync_due(cfg: dict, now=None) -> bool:
    """Пора ли запускать плановую синхронизацию. Тик ходит каждые
    15 минут, поэтому точность — до 15 минут."""
    mode = cfg.get("panel_sync_mode") or "off"
    if mode == "off":
        return False
    now = now or datetime.now()
    last_raw = cfg.get("panel_sync_last_run")
    last = None
    if last_raw:
        try:
            last = datetime.fromisoformat(str(last_raw))
        except ValueError:
            last = None
    if mode == "interval":
        hours = int(cfg.get("panel_sync_interval_hours") or 24)
        return last is None or (now - last).total_seconds() >= hours * 3600
    if mode == "daily":
        try:
            hh, mm = (cfg.get("panel_sync_daily_time") or "03:00").split(":")
            sched = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except (ValueError, TypeError):
            return False
        return now >= sched and (last is None or last < sched)
    return False


_SYNC_RUNNING = False


async def panel_sync_tick(context):
    """Плановая синхронизация: проверяет расписание и, если пора,
    запускает run_panel_sync(). Админу пишет только если есть что
    показать: изменения, ошибки или расхождения."""
    global _SYNC_RUNNING
    if _SYNC_RUNNING:
        return
    from config import ADMIN_ID, load_config, save_config
    cfg = load_config()
    if not panel_sync_due(cfg):
        return
    _SYNC_RUNNING = True
    try:
        res = await run_panel_sync()
        cfg = load_config()
        if res.get("ok"):
            cfg["panel_sync_last_run"] = datetime.now().isoformat(timespec="seconds")
            cfg["panel_sync_last_report"] = {
                "at": cfg["panel_sync_last_run"],
                "checked": res["checked"], "updated": res["updated_subs"],
                "orphans": len(res["orphans"]), "missing": len(res["missing"])}
        save_config(cfg)
        if ADMIN_ID and (not res.get("ok") or res.get("updated_subs")
                         or res.get("orphans") or res.get("missing")):
            try:
                await context.bot.send_message(
                    ADMIN_ID, panel_sync_report_text(res, "⏰ Плановая синхронизация с панелью"),
                    parse_mode="HTML")
            except Exception:
                pass
    finally:
        _SYNC_RUNNING = False


def _parse_interval_hours(text: str) -> int | None:
    """«3», «72ч», «3 дня», «2d» → часы. Допустимо от 1 часа до 30 дней."""
    t = (text or "").strip().lower().replace(" ", "")
    if not t:
        return None
    mult, num = 1, t
    for suf in ("дней", "дня", "день", "дн", "д", "day", "days"):
        if t.endswith(suf):
            mult, num = 24, t[:-len(suf)]
            break
    else:
        for suf in ("часов", "часа", "час", "ч", "hour", "hours", "h"):
            if t.endswith(suf):
                num = t[:-len(suf)]
                break
    try:
        hours = int(num) * mult
    except ValueError:
        return None
    return hours if 1 <= hours <= 24 * 30 else None


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
        kb.append([InlineKeyboardButton("👥 Сквады", callback_data="rw_squads"),
                   InlineKeyboardButton("🔌 Проверить", callback_data="rw_test")])
        kb.append([InlineKeyboardButton("🩺 Здоровье узлов", callback_data="healthcheck")])
        kb.append([InlineKeyboardButton("📊 Потребление ГБ", callback_data="rw_usage")])
        kb.append([InlineKeyboardButton("🔄 Синхронизация",
                                        callback_data="panel_sync_menu")])
        kb.append([InlineKeyboardButton("📨 Разослать ссылки клиентам",
                                        callback_data="rw_notify")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_panel_sync_menu(query, context=None):
    """Меню «Синхронизация»: всё, что сверяет бота с панелью, в одном месте."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if context:
        context.user_data.pop("state", None)
    cfg = load_config()
    lines = ["🔄 <b>Синхронизация</b>", "",
             "<blockquote>"
             f"Расписание: <b>{panel_sync_schedule_text(cfg)}</b></blockquote>", "",
             "🔄 <b>Точечная синхронизация</b> — сверяет базу бота с панелью: "
             "ключи, ссылки, сроки, лимиты устройств и трафика.",
             "⏰ <b>Расписание</b> — когда сверка запускается сама.",
             "👤 <b>Актуализация юзернеймов и ников</b> — проверяет каждого "
             "человека напрямую в Telegram и переписывает описание клиента "
             "в панели по свежим данным:",
             "<code>Drebol VPN · @юзернейм · Ник · TG ID · "
             "Актуализировано ДД.ММ.ГГГГ - ЧЧ.ММ.СС</code>"]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Точечная синхронизация",
                                  callback_data="panel_sync")],
            [InlineKeyboardButton("⏰ Расписание синхронизации",
                                  callback_data="panel_sync_schedule")],
            [InlineKeyboardButton("👤 Актуализация юзернеймов и ников",
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
    from panel import refresh_panel_descriptions, tg_chat_resolver
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
    """Ручной запуск: идём в панель, сверяем каждую подписку с базой."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if not is_configured():
        await query.answer("Сначала задай адрес панели и токен", show_alert=True)
        return
    await query.edit_message_text("🔄 Иду в панель и сверяю каждую подписку…")
    res = await run_panel_sync()
    if res.get("ok"):
        cfg = load_config()
        cfg["panel_sync_last_run"] = datetime.now().isoformat(timespec="seconds")
        cfg["panel_sync_last_report"] = {
            "at": cfg["panel_sync_last_run"],
            "checked": res["checked"], "updated": res["updated_subs"],
            "orphans": len(res["orphans"]), "missing": len(res["missing"])}
        save_config(cfg)
    await query.edit_message_text(
        panel_sync_report_text(res), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Ещё раз", callback_data="panel_sync"),
             InlineKeyboardButton("⏰ Расписание", callback_data="panel_sync_schedule")],
            [InlineKeyboardButton("◀️ К синхронизации",
                                  callback_data="panel_sync_menu")]]))


def _panel_sync_schedule_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ Выкл", callback_data="panel_sync_off")],
        [InlineKeyboardButton("🔁 Каждый час", callback_data="panel_sync_set:interval:1"),
         InlineKeyboardButton("🔁 Каждые 6 ч.", callback_data="panel_sync_set:interval:6")],
        [InlineKeyboardButton("🔁 Каждые 12 ч.", callback_data="panel_sync_set:interval:12"),
         InlineKeyboardButton("🔁 Каждые 3 дня", callback_data="panel_sync_set:interval:72")],
        [InlineKeyboardButton("🔁 Каждую неделю", callback_data="panel_sync_set:interval:168")],
        [InlineKeyboardButton("📅 Каждый день в …", callback_data="panel_sync_daily"),
         InlineKeyboardButton("✏️ Свой интервал", callback_data="panel_sync_interval")],
        [InlineKeyboardButton("◀️ К синхронизации",
                              callback_data="panel_sync_menu")]])


async def handle_panel_sync_schedule(query, context=None):
    """Экран расписания: текущий режим, последний отчёт, выбор периода."""
    if context:
        context.user_data.pop("state", None)
    cfg = load_config()
    lines = ["⏰ <b>Расписание синхронизации</b>", "",
             f"<blockquote>Сейчас: <b>{panel_sync_schedule_text(cfg)}</b>"]
    last = cfg.get("panel_sync_last_report") or {}
    if last.get("at"):
        lines.append(f"Последний запуск: {last['at'][:16].replace('T', ' ')} · "
                     f"сверено {last.get('checked', 0)}, обновлено {last.get('updated', 0)}, "
                     f"в панели без базы {last.get('orphans', 0)}, "
                     f"в базе без панели {last.get('missing', 0)}")
    lines.append("</blockquote>")
    lines += ["", "<i>Плановая проверка ходит каждые 15 минут и запускается, "
              "когда подошло время. Если панель недоступна — база не меняется, "
              "а запуск повторится при следующей проверке. Ручная кнопка "
              "«Точечная синхронизация» работает всегда, вне расписания.</i>"]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=_panel_sync_schedule_keyboard())


async def handle_panel_sync_set(query, context, mode: str, value: str):
    cfg = load_config()
    if mode == "interval":
        cfg["panel_sync_mode"] = "interval"
        cfg["panel_sync_interval_hours"] = int(value)
    save_config(cfg)
    await handle_panel_sync_schedule(query, context)


async def handle_panel_sync_off(query, context=None):
    cfg = load_config()
    cfg["panel_sync_mode"] = "off"
    save_config(cfg)
    await handle_panel_sync_schedule(query, context)


async def handle_panel_sync_daily(query, context):
    from states import AWAITING_PANEL_SYNC_DAILY
    context.user_data["state"] = AWAITING_PANEL_SYNC_DAILY
    await query.edit_message_text(
        "📅 <b>Каждый день в …</b>\n\n"
        "Пришли время в формате <code>ЧЧ:ММ</code>, например <code>03:00</code>.\n"
        "<i>Время — по часовому поясу сервера.</i>",
        parse_mode="HTML", reply_markup=_back())


async def handle_panel_sync_interval(query, context):
    from states import AWAITING_PANEL_SYNC_INTERVAL
    context.user_data["state"] = AWAITING_PANEL_SYNC_INTERVAL
    await query.edit_message_text(
        "✏️ <b>Свой интервал</b>\n\n"
        "Пришли, как часто сверяться: <code>2</code> — каждые 2 часа, "
        "<code>72ч</code> — каждые 72 часа, <code>3 дня</code> — каждые 3 дня.\n"
        "<i>От 1 часа до 30 дней.</i>",
        parse_mode="HTML", reply_markup=_back())


async def handle_rw_url(query, context):
    from states import AWAITING_RW_URL
    context.user_data["state"] = AWAITING_RW_URL
    await query.edit_message_text(
        "🌐 <b>Адрес панели Remnawave</b>\n\n"
        "Пришли адрес целиком, например <code>https://panel.drbl.tech</code>.\n"
        "<i>Без /api на конце — бот допишет сам.</i>",
        parse_mode="HTML", reply_markup=_back(),
    )


async def handle_rw_token(query, context):
    from states import AWAITING_RW_TOKEN
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


# ── Рассылка новых ссылок ─────────────────────────────────────────────────────

async def handle_rw_notify(query, context):
    """Спрашивает подтверждение: ссылки уходят живым людям, молча нельзя."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import live_paid_subs
    rows = await live_paid_subs()
    with_link = [r for r in rows if r[10]]
    if not with_link:
        await query.answer("Некому: ссылок в базе нет", show_alert=True)
        return

    await query.edit_message_text(
        "📨 <b>Новые ссылки клиентам</b>\n\n"
        f"<blockquote>Получат сообщение: <b>{len(with_link)}</b></blockquote>\n\n"
        "Каждому уйдёт его новая ссылка подписки и просьба заменить старую "
        "в приложении.\n\n"
        "<i>Сначала убедись, что ссылка из панели работает: после рассылки "
        "отменить сообщения нельзя.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📨 Разослать", callback_data="rw_notify_go")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="rw_menu")],
        ]),
    )


async def handle_rw_notify_go(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
    from paidsub.storage import live_paid_subs
    rows = [r for r in await live_paid_subs() if r[10]]
    await query.edit_message_text("📨 Рассылаю…")

    sent = failed = 0
    for i, row in enumerate(rows, 1):
        tg_id, link = row[1], row[10]
        if not tg_id:
            continue
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=("🔄 <b>Мы обновили серверы</b>\n\n"
                      "<blockquote>Вот твоя новая ссылка подписки:\n"
                      f"<code>{escape(str(link))}</code></blockquote>\n\n"
                      "Замени её в приложении — старая больше не обновляется. "
                      "Срок подписки и устройства остались как были."),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Скопировать ссылку",
                                          copy_text=CopyTextButton(text=str(link)))],
                    [InlineKeyboardButton("📖 Как подключиться", callback_data="how_to")],
                ]),
                disable_web_page_preview=True,
            )
            sent += 1
        except Exception:
            failed += 1
        # телеграм не любит спешку на больших рассылках
        await asyncio.sleep(0.08)
        if i % 25 == 0:
            try:
                await query.edit_message_text(
                    f"📨 Рассылаю… <b>{i}</b> из <b>{len(rows)}</b>", parse_mode="HTML")
            except Exception:
                pass

    from log_channel import send_log
    await send_log(context.bot,
                   f"📨 Новые ссылки Remnawave: доставлено {sent}, не дошло {failed}")
    await query.edit_message_text(
        "✅ <b>Рассылка закончена</b>\n\n"
        f"<blockquote>Доставлено: <b>{sent}</b>\n"
        f"Не дошло: <b>{failed}</b></blockquote>\n\n"
        "<i>Не дошло — чаще всего бот заблокирован у человека.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")]]),
    )
