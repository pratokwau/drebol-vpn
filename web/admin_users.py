"""Веб-админка Drebol VPN — фаза 2: юзеры и подписки.

Читает те же таблицы и вызывает те же функции, что и ТГ-админка:
поиск — search_users(), карточка — get_user_info() + profile() из
кабинета (карточка «как видит юзер»), подписки — чистые хелперы
paidsub/service.py (их извлекает отдельный шаг из paidsub/handlers.py:
каждое действие пишет И в bot.db, И в панель Remnawave).
"""
from __future__ import annotations

import logging

from web.admin_api import (
    _audit, _csv_response, _require_actor, _require_mutation,
    confirm_needed_response, get_bot, issue_confirm, take_confirm,
)


def _paid_sub_dict(row) -> dict | None:
    if not row:
        return None
    def g(i, default=None):
        return row[i] if len(row) > i else default
    # expire_date в базе хранится «dd.mm.yyyy hh:mm:ss»; наружу отдаём ISO,
    # иначе фронт не может её распарсить (показывал сырьём и ломал статусы)
    from core.database import _expire_to_iso
    return {
        "id": g(0), "tg_id": g(1), "email": g(2), "uuid": g(3),
        "sub_id": g(4), "sub_url": g(5), "expire_date": _expire_to_iso(g(6)),
        "limit_ip": g(7), "limit_hwid": g(8), "total_gb": g(9),
        "created_at": str(g(10) or ""), "status": g(11),
        "times_renewed": g(12), "trial_period": g(13),
        "extra_devices": g(18, 0), "lte_gb": g(19),
        "lte_fallback_month": g(20, ""),
    }


def _service():
    """Чистые хелперы подписок (paidsub/service.py)."""
    from paidsub import service
    return service


# Вкладки и сортировки админских подписок — те же, что в ТГ
# (ADMIN_TABS / ADMIN_SORT_LABELS в adminsub/keyboards.py).
_ADMIN_SCOPES = ("all", "active", "soon", "expired")
_ADMIN_SORTS = ("new", "expire", "name")

# Вкладки и сортировки платных подписок — те же, что в ТГ
# (PAID_TABS / SORT_LABELS в paidsub/keyboards.py, экран —
# handle_paid_subs_menu в paidsub/handlers.py).
_PAID_SCOPES = ("all", "active", "soon", "expired", "off", "trial", "paying")
_PAID_SORTS = ("new", "expire", "name")
_PAID_PER_PAGE = 25

# Состояния клиентов в панели меняются редко, а список листают часто —
# тот же кэш на 60 с, что в paidsub/handlers.py (panel_states).
_PANEL_STATES = {"at": 0.0, "states": {}, "ok": False}
_PANEL_STATES_TTL = 60

# Подписи событий истории — копия _HISTORY_LABELS из
# paidsub/handlers.py (там же источник истины; неизвестное действие
# показываем сырым именем, как в ТГ).
_HISTORY_LABELS = {
    "trial_approved": "🆓 Триал одобрен",
    "trial_rejected": "🚫 Триал отклонён",
    "trial_stopped": "⏹ Триал остановлен",
    "key_reissued": "🔁 Ключ перевыпущен",
    "settings_changed": "⚙️ Изменены настройки",
    "device_removed": "📱 Устройство убрано",
    "promo_days": "🎟 Промокод: начислены дни",
    "promo_issued": "🎟 Выдан промокод",
    "blacklisted": "⛔ Чёрный список: добавлен",
    "unblacklisted": "✅ Чёрный список: убран",
}


def _admin_sub_status(expire_raw) -> str:
    """Статус админской подписки: в базе status нет, как в ТГ
    (handle_sub_view) активна/истекла выводится из срока."""
    from datetime import datetime
    from core.database import _expire_to_iso
    try:
        iso = _expire_to_iso(expire_raw)
        dt = datetime.fromisoformat(iso) if iso else None
    except Exception:
        dt = None
    if dt is None:
        return "active"
    return "active" if dt > datetime.now() else "expired"


async def _json_body(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


# ── Поиск и карточка юзера ──────────────────────────────────────────────────

async def users_search(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import get_user_info, search_users
    needle = (request.query.get("search") or "").strip()
    rows = await search_users(needle, 12) if needle else []
    if needle.isdigit() and not rows:
        info = await get_user_info(int(needle))
        if info:
            rows = [(int(needle), info[1], info[2], None)]
    return web.json_response({"users": [
        {"tg_id": r[0], "first_name": r[1], "username": r[2],
         "sub_status": r[3]} for r in rows]})


async def users_recent(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import recent_visitors
    rows = await recent_visitors(6)
    return web.json_response({"users": [
        {"tg_id": r[0], "first_name": r[1], "username": r[2],
         "last_seen": str(r[3] or "")} for r in rows]})


# Вкладки и сортировки списка пользователей — тот же паттерн, что у
# платных подписок (вкладки по статусу последней платной подписки).
_USERS_SCOPES = ("all", "active", "expired", "none")
_USERS_SORTS = ("new", "name", "id")
_USERS_PER_PAGE = 25

# Последний статус платной подписки юзера (NULL — подписки не было).
# В paid_subs на практике только active/expired (renewal мигрирует
# в active при старте, frozen — состояние панели, не статус строки).
_LATEST_SUB_STATUS = ("(SELECT status FROM paid_subs p WHERE p.tg_id = u.id "
                      "ORDER BY p.id DESC LIMIT 1)")


async def _users_counts() -> dict:
    """Счётчики вкладок списка пользователей — по последнему статусу
    платной подписки (глобальные, без учёта поиска — как paid_counts)."""
    from core.database import DB_PATH
    import aiosqlite
    counts = {"all": 0, "active": 0, "expired": 0, "none": 0}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(" + _LATEST_SUB_STATUS + ", 'none'), COUNT(*) "
            "FROM users u GROUP BY 1") as cur:
            async for st, n in cur:
                counts["all"] += n
                if st in counts:
                    counts[st] += n
    return counts


def _users_where(q: str, scope: str) -> tuple:
    """(where_sql, params) списка пользователей: поиск + вкладка.
    Общая для users_list и users_export — экспорт отдаёт ровно
    те же строки, что список при тех же фильтрах."""
    where = ""
    params: list = []
    if q:
        like = f"%{q.lower()}%"
        # Скобки вокруг OR-условий обязательны: иначе добавленный следом
        # AND scope (AND связывает сильнее OR) применился бы только
        # к последней ветке EXISTS.
        where = """WHERE (CAST(u.id AS TEXT) LIKE ?
               OR lower(u.username) LIKE ?
               OR lower(u.first_name) LIKE ?
               OR EXISTS (SELECT 1 FROM paid_subs p
                          WHERE p.tg_id = u.id AND lower(p.email) LIKE ?))"""
        params = [like, like, like, like]
    if scope == "active":
        where += (" AND " if where else "WHERE ") + _LATEST_SUB_STATUS + " = 'active'"
    elif scope == "expired":
        where += (" AND " if where else "WHERE ") + _LATEST_SUB_STATUS + " = 'expired'"
    elif scope == "none":
        where += (" AND " if where else "WHERE ") + "NOT EXISTS (SELECT 1 FROM paid_subs p WHERE p.tg_id = u.id)"
    return where, params


def _users_order(sort: str) -> str:
    return {"new": "ORDER BY u.created_at DESC, u.id DESC",
            "name": "ORDER BY lower(u.first_name) ASC, lower(u.username) ASC, u.id ASC",
            "id": "ORDER BY u.id DESC"}[sort]


async def users_list(request):
    """Все пользователи: вкладки по статусу подписки, сортировка, поиск,
    страницы. Клик по строке — карточка юзера (openUserEditor).
    Запрос — локально через aiosqlite: те же колонки и то же WHERE поиска,
    что core.admin_list_users (core не трогается — прецедент subs_list)."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import DB_PATH
    import aiosqlite
    try:
        page = int(request.query.get("page") or 1)
    except ValueError:
        return web.json_response({"error": "bad_page"}, status=400)
    scope = (request.query.get("scope") or "all").strip()
    if scope not in _USERS_SCOPES:
        return web.json_response({"error": "bad_scope"}, status=400)
    sort = (request.query.get("sort") or "new").strip()
    if sort not in _USERS_SORTS:
        return web.json_response({"error": "bad_sort"}, status=400)
    q = (request.query.get("q") or "").strip()
    where, params = _users_where(q, scope)
    order = _users_order(sort)
    cols = """u.id, u.first_name, u.username,
              (SELECT status FROM paid_subs p WHERE p.tg_id = u.id
               ORDER BY p.id DESC LIMIT 1), u.created_at"""
    per_page = _USERS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                f"SELECT COUNT(*) FROM users u {where}", params) as cur:
            total = (await cur.fetchone())[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page
        async with db.execute(
                f"SELECT {cols} FROM users u {where} {order} "
                "LIMIT ? OFFSET ?", (*params, per_page, offset)) as cur:
            rows = await cur.fetchall()
    counts = await _users_counts()
    return web.json_response({"users": [
        {"tg_id": r[0], "first_name": r[1], "username": r[2],
         "sub_status": r[3], "created_at": str(r[4] or "")} for r in rows],
        "page": page, "total_pages": total_pages, "total": total,
        "scope": scope, "sort": sort, "counts": counts})


async def users_export(request):
    """Экспорт пользователей в CSV: те же вкладка, сортировка и поиск,
    что в списке (тот же _users_where), без пагинации. Сверх
    EXPORT_MAX_ROWS — 409 too_large с total, а не обрезанный молча
    файл (как в ТГ-выгрузке логов — там truncation виден в подписи)."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from datetime import date
    from handlers.control import EXPORT_MAX_ROWS
    from core.database import DB_PATH
    import aiosqlite
    scope = (request.query.get("scope") or "all").strip()
    if scope not in _USERS_SCOPES:
        return web.json_response({"error": "bad_scope"}, status=400)
    sort = (request.query.get("sort") or "new").strip()
    if sort not in _USERS_SORTS:
        return web.json_response({"error": "bad_sort"}, status=400)
    q = (request.query.get("q") or "").strip()
    where, params = _users_where(q, scope)
    order = _users_order(sort)
    cols = """u.id, u.first_name, u.username,
              (SELECT email FROM paid_subs p WHERE p.tg_id = u.id
               ORDER BY p.id DESC LIMIT 1),
              (SELECT status FROM paid_subs p WHERE p.tg_id = u.id
               ORDER BY p.id DESC LIMIT 1), u.created_at"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                f"SELECT COUNT(*) FROM users u {where}", params) as cur:
            total = (await cur.fetchone())[0]
        if total > EXPORT_MAX_ROWS:
            return web.json_response(
                {"error": "too_large", "total": total,
                 "max": EXPORT_MAX_ROWS}, status=409)
        async with db.execute(
                f"SELECT {cols} FROM users u {where} {order} "
                f"LIMIT {EXPORT_MAX_ROWS}", params) as cur:
            rows = await cur.fetchall()
    return _csv_response(
        ["tg_id", "first_name", "username", "email", "sub_status",
         "created_at"],
        [[r[0], r[1] or "", ("@" + r[2]) if r[2] else "", r[3] or "",
          r[4] or "none", str(r[5] or "")] for r in rows],
        f"drebol-users-{scope}-{date.today().isoformat()}.csv")


async def user_profile(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import get_user_info, user_payments
    from features.blacklist import entry as bl_entry, public_reason
    from paidsub.storage import get_paid_sub_by_tg_id, get_referral_stats
    try:
        tg_id = int(request.match_info["tg_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    info = await get_user_info(tg_id)
    if not info:
        return web.json_response({"error": "not_found"}, status=404)
    sub = await get_paid_sub_by_tg_id(tg_id)
    ref = await get_referral_stats(tg_id)
    pays, pays_count, pays_sum = await user_payments(tg_id, 10)
    ble = await bl_entry(tg_id)
    # Карточка «как видит юзер»: те же данные, что отдаёт кабинет
    # (подписка, трафик, LTE, устройства, оплаты, рефералка).
    as_user = None
    as_user_error = None
    try:
        from web.webapi import profile
        as_user = await profile(tg_id)
    except Exception as ex:
        as_user_error = f"{type(ex).__name__}: {ex}"
    out = {
        "tg_id": tg_id, "first_name": info[1], "username": info[2],
        "subscription": _paid_sub_dict(sub),
        "referral": {"invited": int(ref["total"] or 0),
                     "rewarded": int(ref["rewarded"] or 0)},
        "payments": [{"id": r[0], "provider": r[1] or "", "amount": r[2],
                      "status": r[3], "date": str(r[4] or "")[:16],
                      "promo": r[5] or ""} for r in pays],
        "payments_total": {"count": pays_count, "sum": pays_sum},
        "blacklist": ({"source": ble["source"],
                       "reason": public_reason(ble["reason"])}
                      if ble else None),
        "as_user": as_user, "as_user_error": as_user_error,
    }
    return web.json_response(out)


# Вкладки активности пользователя — те же 3, что USER_TABS
# в handlers/control.py (handle_user_activity).
USER_ACTIVITY_SCOPES = ("all", "important", "subs")


async def user_activity(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    try:
        tg_id = int(request.match_info["tg_id"])
        page = max(1, int(request.query.get("page", "1")))
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    scope = request.query.get("scope") or "all"
    if scope not in USER_ACTIVITY_SCOPES:
        return web.json_response({"error": "bad_scope"}, status=400)
    # Строки — тем же форматированием, что лента логов
    # (_activity_row/_history_row из admin_infra): подпись действия
    # и обрезанные детали вместо сырых кодов.
    from web.admin_infra import _activity_row, _history_row

    async def _fetch(pg):
        if scope == "subs":
            # Как в ТГ: история подписок живёт отдельно от activity_log.
            from paidsub.storage import get_user_history
            rows, pgs = await get_user_history(tg_id, pg, 15)
            return [_history_row((r[0], r[1], r[2], r[3], r[4], "", ""))
                    for r in rows], pgs
        from core.database import list_activity
        key = f"user_important:{tg_id}" if scope == "important" else f"user:{tg_id}"
        rows, pgs = await list_activity(key, pg, 15)
        return [_activity_row(r) for r in rows], pgs

    out, pages = await _fetch(page)
    if page > pages:
        # Кламп как в ТГ (page ≤ total_pages): перечитать последнюю.
        page = pages
        out, pages = await _fetch(page)
    return web.json_response({"activity": out, "page": page,
                              "pages": pages, "scope": scope})


# ── DM и подарок ───────────────────────────────────────────────────────────

async def user_dm(request):
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        tg_id = int(request.match_info["tg_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    body = await _json_body(request)
    text = str(body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "empty_text"}, status=400)
    bot = get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    try:
        await bot.send_message(chat_id=tg_id, text=text)
    except Exception as ex:
        logging.error("админка: dm %s: %s", tg_id, ex)
        return web.json_response({"error": "send_failed"}, status=502)
    await _audit(actor, "user_dm", f"tg_id: {tg_id}")
    return web.json_response({"ok": True})


async def user_gift(request):
    """Подарок подписки: тот же apply_gift_payment(), что и в ТГ."""
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        tg_id = int(request.match_info["tg_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    body = await _json_body(request)
    try:
        amount = int(body.get("amount") or 0)
    except (TypeError, ValueError):
        return web.json_response({"error": "bad_amount"}, status=400)
    if amount <= 0:
        return web.json_response({"error": "bad_amount"}, status=400)
    period = body.get("period_seconds")
    try:
        period = int(period) if period is not None else None
    except (TypeError, ValueError):
        return web.json_response({"error": "bad_period"}, status=400)
    bot = get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)

    class _Ctx:
        def __init__(self, bot):
            self.bot = bot

    giver = _actor_tg_id(actor)
    try:
        from paidsub import service as svc
        res = await svc.gift_sub(tg_id, giver, amount, bot=bot,
                                 promo_code=body.get("promo_code") or None,
                                 period_seconds=period)
    except ImportError:
        from paidsub.handlers import apply_gift_payment
        res = await apply_gift_payment(
            tg_id, giver, amount, _Ctx(bot),
            promo_code=body.get("promo_code") or None,
            period_seconds=period)
    if not res.get("ok"):
        return web.json_response(
            {"error": "gift_failed", "details": str(res.get("error") or "")},
            status=400)
    await _audit(actor, "user_gift",
                 f"tg_id: {tg_id}, amount: {amount}")
    return web.json_response({"ok": True, "result": {
        k: v for k, v in res.items() if k not in ("sub_url",)}})


def _actor_tg_id(actor: dict) -> int:
    return int(actor["tg_id"]) if actor["kind"] == "mark" else 0


# ── Заявки на подписку ─────────────────────────────────────────────────────

async def subs_requests_list(request):
    """Ждущие заявки на подписку: тот же экран «📥 Заявки», что в ТГ
    (handle_paid_requests в paidsub/handlers.py)."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from paidsub.storage import count_pending_requests, list_pending_requests
    rows = await list_pending_requests()
    return web.json_response({
        "requests": [
            {"tg_id": r[0], "created_at": str(r[1] or "")[:16],
             "first_name": r[2], "username": r[3]} for r in rows],
        "count": await count_pending_requests()})


async def _subs_request_action(request, action: str):
    """Одобрить / отклонить заявку: тот же смысл, что handle_approve /
    handle_reject в ТГ, с подтверждением, как остальные действия по
    подпискам в вебе.

    Отличие от ТГ сознательное: заявка переводится из pending только
    после успешного создания подписки — иначе при сбое панели заявка
    теряется, а подписки у человека нет.
    """
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        tg_id = int(request.match_info["tg_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    if tg_id <= 0:
        return web.json_response({"error": "bad_id"}, status=400)
    body = await _json_body(request)
    token = str(body.get("confirm_token") or "")
    if not token:
        summary = (f"Одобрить заявку на подписку от {tg_id} (выдать триал)"
                   if action == "approve"
                   else f"Отклонить заявку на подписку от {tg_id}")
        tok = issue_confirm(actor, f"sub_request_{action}",
                            {"tg_id": tg_id}, summary)
        return confirm_needed_response(tok, summary)
    payload = take_confirm(actor, token, f"sub_request_{action}")
    if payload is None or payload.get("tg_id") != tg_id:
        return web.json_response({"error": "bad_confirm"}, status=403)
    from paidsub.storage import (add_history, get_paid_sub_by_tg_id,
                                 get_pending_request, resolve_request)
    pending = await get_pending_request(tg_id)
    if not pending:
        return web.json_response({"error": "request_not_found"}, status=404)
    bot = get_bot()
    if action == "reject":
        await resolve_request(tg_id, "rejected")
        await add_history(tg_id, "trial_rejected")
        notified = await _notify_request_user(
            bot, tg_id,
            "😕 <b>Запрос на подписку отклонён</b>\n\n"
            "<i>Если это ошибка — напишите в поддержку, разберёмся.</i>")
        await _audit(actor, "sub_request_reject", f"tg_id: {tg_id}")
        return web.json_response({"ok": True, "notified": notified})
    existing = await get_paid_sub_by_tg_id(tg_id)
    if existing:
        await resolve_request(tg_id, "approved")
        await _audit(actor, "sub_request_approve",
                     f"tg_id: {tg_id}, already_has_sub")
        return web.json_response({"ok": True, "already_has_sub": True})
    svc = _service()
    try:
        res = await svc.create_paid_sub(tg_id, trial=True, bot=bot)
    except Exception as ex:
        logging.error("админка: request approve %s: %s", tg_id, ex)
        return web.json_response({"error": "create_failed"}, status=502)
    if not res.get("ok"):
        return web.json_response(
            {"error": "panel_failed",
             "details": str(res.get("error") or "")}, status=502)
    await resolve_request(tg_id, "approved")
    await add_history(tg_id, "trial_approved")
    # Уведомление юзеру — тот же текст «Подписка готова!», что шлёт
    # do_create_paid_sub; ссылка — показная, через sub.drbl.tech.
    notified = False
    if bot is not None:
        from config import sub_url_for_display
        sub_link = sub_url_for_display(res["sub_url"])
        notified = await _notify_request_user(
            bot, tg_id,
            "🎉 <b>Подписка готова!</b>\n\n"
            f"<blockquote>📅 Действует до: <b>{res['expire'][:16]}</b></blockquote>\n\n"
            "🔑 <b>Ссылка для подключения</b>\n"
            f"<code>{sub_link}</code>\n\n"
            "<i>Нажмите на ссылку — она скопируется — и вставьте её в INCY.</i>")
    # Реферальный бонус — та же _process_referral_bonus, что в ТГ после
    # одобрения; сбой бонуса не отменяет выданную подписку, только
    # фиксируется в ответе.
    bonus_error = None
    if bot is not None:
        try:
            from types import SimpleNamespace
            from paidsub.handlers import _process_referral_bonus
            await _process_referral_bonus(tg_id, SimpleNamespace(bot=bot))
        except Exception as ex:
            logging.error("админка: request approve bonus %s: %s", tg_id, ex)
            bonus_error = f"{type(ex).__name__}: {ex}"
    await _audit(actor, "sub_request_approve",
                 f"tg_id: {tg_id}, sub_id: {res['sub_id']}")
    out = {"ok": True, "notified": notified,
           "subscription": {"id": res["sub_id"], "email": res["email"],
                            "expire": res["expire"]}}
    if bonus_error:
        out["referral_bonus_error"] = bonus_error
    return web.json_response(out)


async def _notify_request_user(bot, tg_id: int, text: str) -> bool:
    """Уведомление юзеру в Telegram. False — бота нет или отправка не
    прошла; действие при этом уже выполнено и не откатывается."""
    if bot is None:
        return False
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML")
    except Exception as ex:
        logging.error("админка: request notify %s: %s", tg_id, ex)
        return False
    return True


# ── История подписки ─────────────────────────────────────────────────────

async def _sub_history(request, kind: str):
    """История событий подписки: та же get_user_history, что в ТГ
    (handle_paid_sub_history / handle_sub_history), 8 событий на
    страницу. У подписки без TG ID истории нет — как в ТГ."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    try:
        sub_id = int(request.match_info["sub_id"])
        page = max(1, int(request.query.get("page", "1")))
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    if kind == "admin":
        from adminsub.storage import get_sub
        row = await get_sub(sub_id)
    else:
        from paidsub.storage import get_paid_sub
        row = await get_paid_sub(sub_id)
    if not row:
        return web.json_response({"error": "not_found"}, status=404)
    tg_id = row[1]
    if not tg_id:
        return web.json_response({"events": [], "page": 1, "total_pages": 1,
                                  "no_tg_id": True})
    from paidsub.storage import get_user_history
    rows, total_pages = await get_user_history(tg_id, page, 8)
    if page > total_pages:
        page = total_pages
        rows, _ = await get_user_history(tg_id, page, 8)
    return web.json_response({"events": [
        {"id": r[0], "action": r[2],
         "label": _HISTORY_LABELS.get(r[2], r[2]),
         "details": r[3] or "", "created_at": str(r[4] or "")[:16]}
        for r in rows], "page": page, "total_pages": total_pages})


async def sub_history(request):
    return await _sub_history(request, "paid")


async def admin_sub_history(request):
    return await _sub_history(request, "admin")


# ── Подписки: действия ─────────────────────────────────────────────────────

async def _paid_panel_states() -> dict:
    """Живые состояния клиентов панели с кэшем на 60 с — как panel_states
    в paidsub/handlers.py: {"ok": bool, "states": {email: STATUS}}."""
    import time
    if (_PANEL_STATES["ok"]
            and time.time() - _PANEL_STATES["at"] < _PANEL_STATES_TTL):
        return _PANEL_STATES
    try:
        from services.panel import get_client_states
        got = await get_client_states()
    except Exception:
        logging.exception("админка: subs_list: панель недоступна")
        got = {"ok": False, "states": {}}
    if got.get("ok"):
        _PANEL_STATES.update(at=time.time(), states=got["states"], ok=True)
    else:
        _PANEL_STATES.update(ok=False, states={})
    return _PANEL_STATES


def _paid_mark_raw(row, states: dict) -> str:
    """Значок подписки в списке — копия _sub_mark из paidsub/handlers.py:
    что с ней прямо сейчас. row — полная строка, как в _paid_sub_dict
    (логин — [2], срок — [6], статус — [11])."""
    from datetime import datetime
    from paidsub.storage import SOON_DAYS, parse_sub_date
    if states.get(row[2] or "") == "DISABLED":
        return "⏸"
    if row[11] == "expired":
        return "🔴"
    end = parse_sub_date(row[6])
    if end and (end - datetime.now()).total_seconds() <= SOON_DAYS * 86400:
        return "⏳"
    return "🟢"


async def _paid_full_rows(ids: list) -> list:
    """Полные строки платных подписок по id — те же колонки, что в
    admin_list_paid_subs (core/database.py), плюс имена владельцев."""
    from core.database import DB_PATH
    import aiosqlite
    cols = ("s.id, s.tg_id, s.email, s.uuid, s.sub_id, s.sub_url, s.expire_date,"
            " s.limit_ip, s.limit_hwid, s.total_gb, s.created_at, s.status,"
            " s.times_renewed, s.ind_trial_period, s.ind_pay_period,"
            " s.ind_renew_time, s.ind_price, s.ind_pay_url,"
            " s.extra_devices, s.lte_gb, s.lte_fallback_month,"
            " u.first_name, u.username")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT " + cols + " FROM paid_subs s "
            "LEFT JOIN users u ON u.id = s.tg_id "
            f"WHERE s.id IN ({','.join('?' * len(ids))})", ids) as cur:
            return await cur.fetchall()


async def _paid_subs_enriched(short_rows, states: dict) -> list:
    """Короткие строки (id, tg_id, email, ...) из paidsub/storage.py →
    полные dict для фронта: те же поля, что раньше, плюс значок mark.
    Порядок коротких строк (сортировка вкладки) сохраняется."""
    if not short_rows:
        return []
    by_id = {r[0]: r for r in await _paid_full_rows([r[0] for r in short_rows])}
    subs = []
    for sr in short_rows:
        r = by_id.get(sr[0])
        if r is None:
            continue
        d = _paid_sub_dict(r)
        d["first_name"] = r[-2]
        d["username"] = r[-1]
        d["mark"] = _paid_mark_raw(r, states)
        subs.append(d)
    return subs


async def subs_list(request):
    """Платные подписки: вкладки, сортировка, поиск и счётчики — тот же
    экран, что handle_paid_subs_menu в ТГ (paidsub/handlers.py):
    list_paid_subs / paid_counts / search_paid_subs из paidsub/storage.py,
    выключенные — из живых состояний панели, как в ТГ."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from paidsub.storage import (all_paid_subs, list_paid_subs, paid_counts,
                                 paid_emails, search_paid_subs)
    try:
        page = max(1, int(request.query.get("page", "1")))
    except ValueError:
        return web.json_response({"error": "bad_page"}, status=400)
    scope = (request.query.get("scope") or "all").strip()
    if scope not in _PAID_SCOPES:
        scope = "all"
    sort = (request.query.get("sort") or "new").strip()
    if sort not in _PAID_SORTS:
        sort = "new"
    q = (request.query.get("q") or "").strip()
    counts = await paid_counts()
    panel = await _paid_panel_states()
    states = panel["states"]
    off_emails = {e for e, st in states.items() if st == "DISABLED"}
    counts["off"] = (len(off_emails & await paid_emails())
                     if panel["ok"] else None)
    if q:
        # Поиск — отдельным экраном, как в ТГ (apply_paid_search):
        # вкладки и страницы не применяются, найдено — до 20 строк.
        subs = await _paid_subs_enriched(await search_paid_subs(q), states)
        return web.json_response({"subs": subs, "page": 1, "total_pages": 1,
                                  "scope": scope, "sort": sort,
                                  "counts": counts, "panel_ok": panel["ok"]})
    if scope == "off":
        # Выключенных знает только панель: фильтруем уже выбранные строки.
        picked = [r for r in await all_paid_subs("all", sort)
                  if r[2] in off_emails]
        total_pages = max(1, (len(picked) + _PAID_PER_PAGE - 1)
                          // _PAID_PER_PAGE)
        page = min(page, total_pages)
        short = picked[(page - 1) * _PAID_PER_PAGE:page * _PAID_PER_PAGE]
    else:
        short, total_pages = await list_paid_subs(page, scope, sort,
                                                  _PAID_PER_PAGE)
        page = min(page, total_pages)
    subs = await _paid_subs_enriched(short, states)
    return web.json_response({"subs": subs, "page": page,
                              "total_pages": total_pages, "scope": scope,
                              "sort": sort, "counts": counts,
                              "panel_ok": panel["ok"]})


async def subs_export(request):
    """Экспорт платных подписок в CSV: та же выборка, что в списке
    (вкладка/сортировка/поиск; off — из живых состояний панели),
    без пагинации. Битые scope/sort — дефолты all/new, как в списке.
    Поиск — без капа списка (search_paid_subs отдаёт до 20, здесь —
    до EXPORT_MAX_ROWS+1, чтобы заметить переполнение). Сверх капа —
    409 too_large с total, а не обрезанный молча файл."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from datetime import date
    from handlers.control import EXPORT_MAX_ROWS
    from paidsub.storage import (all_paid_subs, search_paid_subs)
    scope = (request.query.get("scope") or "all").strip()
    if scope not in _PAID_SCOPES:
        scope = "all"
    sort = (request.query.get("sort") or "new").strip()
    if sort not in _PAID_SORTS:
        sort = "new"
    q = (request.query.get("q") or "").strip()
    panel = await _paid_panel_states()
    states = panel["states"]
    if q:
        short = await search_paid_subs(q, limit=EXPORT_MAX_ROWS + 1)
    elif scope == "off":
        off_emails = {e for e, st in states.items() if st == "DISABLED"}
        short = [r for r in await all_paid_subs("all", sort)
                 if r[2] in off_emails]
    else:
        short = await all_paid_subs(scope, sort)
    if len(short) > EXPORT_MAX_ROWS:
        # Для поиска total — «как минимум столько» (лимит +1 оборвал
        # выборку); для вкладок — точное число строк.
        return web.json_response(
            {"error": "too_large", "total": len(short),
             "max": EXPORT_MAX_ROWS}, status=409)
    subs = await _paid_subs_enriched(short, states)
    return _csv_response(
        ["id", "tg_id", "first_name", "username", "email", "uuid",
         "status", "expire_date", "created_at", "times_renewed",
         "limit_ip", "total_gb", "panel"],
        [[d["id"], d["tg_id"], d.get("first_name") or "",
          ("@" + d["username"]) if d.get("username") else "",
          d["email"] or "", d["uuid"] or "", d["status"] or "",
          d["expire_date"] or "", d["created_at"] or "",
          d["times_renewed"] or 0, d["limit_ip"] or "",
          d["total_gb"] or "", d["mark"] or ""] for d in subs],
        f"drebol-subs-{scope}-{date.today().isoformat()}.csv")


async def sub_card(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from paidsub.storage import get_paid_sub_admin
    try:
        sub_id = int(request.match_info["sub_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    row = await get_paid_sub_admin(sub_id)
    if not row:
        return web.json_response({"error": "not_found"}, status=404)
    # Живое состояние из панели + владелец и пригласивший: get_sub_card
    # в paidsub/service.py (раньше здесь звался несуществующий
    # sub_panel_state, и блок «В панели» в карточке никогда не жил).
    panel, user, referrer = {}, None, None
    try:
        svc = _service()
        card = await svc.get_sub_card(sub_id)
        if card.get("ok"):
            panel = card.get("panel") or {}
            user = card.get("user")
            referrer = card.get("referrer")
    except Exception:
        logging.exception("админка: sub_card #%s: панель недоступна", sub_id)
    payments = {"items": [], "count": 0, "sum": 0}
    try:
        from core.database import user_payments
        prows, pcount, psum = await user_payments(row[1], 5)
        payments = {
            "items": [{"id": r[0], "provider": r[1] or "", "amount": r[2],
                       "status": r[3], "date": str(r[4] or "")[:16],
                       "promo": r[5] or ""} for r in prows],
            "count": pcount, "sum": psum,
        }
    except Exception:
        logging.exception("админка: sub_card #%s: платежи недоступны", sub_id)
    from config import (SUB_DISPLAY_DOMAIN, SUB_STORED_DOMAIN,
                        sub_url_for_display, sub_url_with_domain)
    raw_url = row[5] if len(row) > 5 else ""
    return web.json_response({
        "subscription": _paid_sub_dict(row),
        "panel": panel, "user": user, "referrer": referrer,
        "payments": payments,
        "display_url": sub_url_for_display(raw_url),
        "url_sub": sub_url_with_domain(raw_url, SUB_DISPLAY_DOMAIN),
        "url_key": sub_url_with_domain(raw_url, SUB_STORED_DOMAIN),
    })


async def _sub_action(request, action: str):
    """Один экшен подписки через paidsub/service.py."""
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        sub_id = int(request.match_info["sub_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    body = await _json_body(request)
    confirm_actions = {"delete", "reissue", "bulk_extend", "bulk_limits"}
    if action in confirm_actions:
        token = str(body.get("confirm_token") or "")
        if not token:
            summary = {"delete": f"Удалить подписку #{sub_id} (БД + панель)",
                       "reissue": f"Перевыпустить подписку #{sub_id}",
                       "bulk_extend": "Массовый сдвиг сроков",
                       "bulk_limits": "Массовая смена лимитов"}.get(action, action)
            tok = issue_confirm(actor, f"sub_{action}",
                                {"sub_id": sub_id, "body": body}, summary)
            return confirm_needed_response(tok, summary)
        payload = take_confirm(actor, token, f"sub_{action}")
        if payload is None:
            return web.json_response({"error": "bad_confirm"}, status=403)
        body = payload.get("body") or {}
    try:
        svc = _service()
    except ImportError:
        return web.json_response({"error": "service_not_ready"}, status=503)
    fn = {"toggle": svc.toggle_sub, "freeze": svc.freeze_sub,
          "delete": svc.delete_sub, "reissue": svc.reissue_sub,
          "extend": svc.extend_sub, "expire": svc.set_expire,
          "hwid": svc.set_hwid_limit, "traffic": svc.set_traffic_limit,
          "lte": svc.set_lte_limit, "trial": svc.set_trial}.get(action)
    if fn is None:
        return web.json_response({"error": "bad_action"}, status=400)
    # Карта веб-полей в сигнатуры paidsub/service.py.
    kind = body.get("kind") if body.get("kind") in ("paid", "admin") else "paid"
    kwargs = {"kind": kind}
    try:
        if action == "extend":
            seconds = body.get("seconds")
            if seconds is None:
                seconds = int(body.get("days") or 0) * 86400
            kwargs["seconds"] = int(seconds)
            res = await fn(sub_id, kwargs.pop("seconds"), **kwargs)
        elif action == "expire":
            res = await fn(sub_id, str(body.get("until") or ""), **kwargs)
        elif action == "hwid":
            res = await fn(sub_id, int(body.get("limit") or 0), **kwargs)
        elif action == "traffic":
            res = await fn(sub_id, int(body.get("gb") or 0), **kwargs)
        elif action == "lte":
            lte = body.get("gb")
            res = await fn(sub_id, None if lte is None else int(lte), **kwargs)
        elif action == "trial":
            seconds = body.get("seconds")
            if seconds is None:
                seconds = int(body.get("period_days") or 0) * 86400
            res = await fn(sub_id, int(seconds), **kwargs)
        else:
            res = await fn(sub_id, **kwargs)
    except (TypeError, ValueError) as ex:
        return web.json_response({"error": "bad_params", "details": str(ex)},
                                 status=400)
    except Exception as ex:
        logging.error("админка: sub %s #%s: %s", action, sub_id, ex)
        return web.json_response({"error": "action_failed"}, status=502)
    if not res.get("ok"):
        return web.json_response(
            {"error": "action_failed", "details": str(res.get("error") or "")},
            status=400)
    await _audit(actor, f"sub_{action}",
                 f"sub_id: {sub_id}" + (", kind: admin" if kind == "admin"
                                         else ""))
    return web.json_response({"ok": True, "result": res})


async def _sub_devices_impl(request, kind: str):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    try:
        sub_id = int(request.match_info["sub_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    if kind == "admin":
        from adminsub.storage import get_sub
        row = await get_sub(sub_id)
    else:
        from paidsub.storage import get_paid_sub
        row = await get_paid_sub(sub_id)
    if not row:
        return web.json_response({"error": "not_found"}, status=404)
    svc = _service()
    res = await svc.list_devices(sub_id, kind=kind)
    if not res.get("ok"):
        return web.json_response({"error": "action_failed",
                                  "details": str(res.get("error") or "")},
                                 status=400)
    return web.json_response(res)


async def sub_devices(request):
    return await _sub_devices_impl(request, "paid")


async def admin_sub_devices(request):
    return await _sub_devices_impl(request, "admin")


async def _sub_ips_impl(request, kind: str):
    """IP-адреса, с которых подписка ходит в панель (по устройствам)."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    try:
        sub_id = int(request.match_info["sub_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    if kind == "admin":
        from adminsub.storage import get_sub
        row = await get_sub(sub_id)
    else:
        from paidsub.storage import get_paid_sub
        row = await get_paid_sub(sub_id)
    if not row:
        return web.json_response({"error": "not_found"}, status=404)
    svc = _service()
    res = await svc.list_ips(sub_id, kind=kind)
    if not res.get("ok"):
        return web.json_response({"error": "action_failed",
                                  "details": str(res.get("error") or "")},
                                 status=400)
    return web.json_response(res)


async def sub_ips(request):
    return await _sub_ips_impl(request, "paid")


async def admin_sub_ips(request):
    return await _sub_ips_impl(request, "admin")


async def _sub_device_mutation(request, kind: str, sub_kind: str = "paid"):
    """Убрать одно устройство / сбросить все: с подтверждением, как
    остальные разрушительные действия по подписке. Для админских токен
    подтверждения выписывается отдельно (admin_…), чтобы его нельзя
    было применить к платной подписке и наоборот."""
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        sub_id = int(request.match_info["sub_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    body = await _json_body(request)
    confirm_action = kind if sub_kind == "paid" else f"admin_{kind}"
    token = str(body.get("confirm_token") or "")
    if not token:
        summary = (f"Убрать устройство подписки #{sub_id}"
                   if kind == "sub_device_delete"
                   else f"Сбросить все устройства подписки #{sub_id}")
        if sub_kind == "admin":
            summary += " (админская)"
        tok = issue_confirm(actor, confirm_action,
                            {"sub_id": sub_id, "body": body}, summary)
        return confirm_needed_response(tok, summary)
    payload = take_confirm(actor, token, confirm_action)
    if payload is None:
        return web.json_response({"error": "bad_confirm"}, status=403)
    body = payload.get("body") or {}
    svc = _service()
    try:
        if kind == "sub_device_delete":
            res = await svc.delete_device(sub_id, str(body.get("ref") or ""),
                                          kind=sub_kind)
        else:
            res = await svc.clear_hwid(sub_id, kind=sub_kind)
    except Exception as ex:
        logging.error("админка: %s #%s: %s", kind, sub_id, ex)
        return web.json_response({"error": "action_failed"}, status=502)
    if not res.get("ok"):
        return web.json_response(
            {"error": "action_failed",
             "details": str(res.get("error") or "")}, status=400)
    await _audit(actor, confirm_action, f"sub_id: {sub_id}")
    return web.json_response({"ok": True, "result": res})


async def sub_device_delete(request):
    return await _sub_device_mutation(request, "sub_device_delete")


async def sub_devices_clear(request):
    return await _sub_device_mutation(request, "sub_devices_clear")


async def admin_sub_device_delete(request):
    return await _sub_device_mutation(request, "sub_device_delete", "admin")


async def admin_sub_devices_clear(request):
    return await _sub_device_mutation(request, "sub_devices_clear", "admin")


# Вкладки массовых действий — те же 6, что в ТГ
# (BULK_SCOPES в paidsub/handlers.py, экран handle_paid_bulk_menu).
# Иконки и подписи — из PAID_TABS в paidsub/keyboards.py.
_BULK_SCOPES = ("all", "active", "trial", "paying", "soon", "expired")
_BULK_SCOPE_LABELS = {
    "all": ("📋", "Все"),
    "active": ("🟢", "Активные"),
    "trial": ("🆓", "Пробные"),
    "paying": ("💳", "Платящие"),
    "soon": ("⏳", "Скоро кончатся"),
    "expired": ("🔴", "Истёкшие"),
}


def _bulk_scope_label(scope: str) -> str:
    icon, label = _BULK_SCOPE_LABELS.get(scope, ("📋", "Все"))
    return f"{icon} {label}"


def _coerce_int(value, default=None):
    """int из тела запроса: число, строка цифр или None → default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return default


async def bulk_scopes(request):
    """Счётчики вкладок массовых действий — те же, что в меню ТГ
    (paid_counts из paidsub/storage.py). Только чтение."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from paidsub.storage import paid_counts
    counts = await paid_counts()
    return web.json_response({
        "counts": {k: counts.get(k, 0) for k in _BULK_SCOPES},
        "scopes": [{"key": k, "label": _BULK_SCOPE_LABELS[k][1],
                    "icon": _BULK_SCOPE_LABELS[k][0]}
                   for k in _BULK_SCOPES],
    })


async def subs_bulk(request):
    """Массовые действия по платным подпискам — паритет с ТГ
    (handle_paid_bulk_menu / handle_paid_bulk_apply /
    handle_paid_bulk_limits_apply в paidsub/handlers.py):
    выборка — одна из вкладок BULK_SCOPES, счётчики — paid_counts.
    Действие затрагивает только выборку: scope != "all" → only_ids
    через all_paid_subs(scope), как в ТГ. Сдвиг срока: направление
    "extend"/"reduce" (или ±1) и секунды > 0 — раньше фронт слал
    direction строкой, а сервис ждёт int, и «Продлить всем» всегда
    падало в bad_params. Лимиты: kind_limit только "hwid"/"lte"
    (значение "traffic" раньше давало KeyError → 500)."""
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    kind = str(request.match_info.get("kind") or "")
    if kind not in ("extend", "limits", "lte"):
        return web.json_response({"error": "bad_action"}, status=400)
    scope = str(body.get("scope") or "all").strip()
    if scope not in _BULK_SCOPES:
        return web.json_response({"error": "bad_scope"}, status=400)
    # Параметры проверяем ДО подтверждения, чтобы в диалог не уходил
    # заведомо невалидный запрос.
    if kind == "extend":
        seconds = _coerce_int(body.get("seconds"))
        if seconds is None:
            days = _coerce_int(body.get("days"), 0)
            seconds = abs(days) * 86400
            direction = -1 if days < 0 else 1
        else:
            direction = body.get("direction")
            if isinstance(direction, str):
                direction = {"extend": 1, "reduce": -1}.get(direction)
            direction = _coerce_int(direction)
            if direction not in (1, -1):
                direction = 1
            seconds = abs(seconds)
        if seconds <= 0:
            return web.json_response({"error": "bad_params",
                                      "details": "seconds must be > 0"},
                                     status=400)
    else:
        kind_limit = "lte" if kind == "lte" else str(
            body.get("kind_limit") or "hwid")
        if kind_limit not in ("hwid", "lte"):
            return web.json_response({"error": "bad_params",
                                      "details": "bad kind_limit"},
                                     status=400)
        value = _coerce_int(body.get("value"))
        if body.get("value") is not None and value is None:
            return web.json_response({"error": "bad_params",
                                      "details": "value must be int"},
                                     status=400)
    token = str(body.get("confirm_token") or "")
    if not token:
        from paidsub.storage import paid_counts
        count = (await paid_counts()).get(scope, 0)
        base = {"extend": "Массовый сдвиг сроков",
                "limits": "Массовая смена лимитов",
                "lte": "Массовая смена LTE-лимита"}.get(
                    kind, "Массовое действие по подпискам")
        summary = (f"{base} · выборка: {_bulk_scope_label(scope)} — "
                   f"{count} подп.")
        tok = issue_confirm(actor, f"sub_bulk_{kind}", {"body": body},
                            summary)
        return confirm_needed_response(tok, summary)
    payload = take_confirm(actor, token, f"sub_bulk_{kind}")
    if payload is None:
        return web.json_response({"error": "bad_confirm"}, status=403)
    body = payload.get("body") or {}
    # scope перепроверяем из подтверждённого тела — токен привязан
    # к исходному запросу, но защита от подмены не помешает.
    scope = str(body.get("scope") or "all").strip()
    if scope not in _BULK_SCOPES:
        return web.json_response({"error": "bad_scope"}, status=400)
    svc = _service()
    only_ids = None
    if scope != "all":
        from paidsub.storage import all_paid_subs
        only_ids = [r[0] for r in await all_paid_subs(scope)]
    try:
        if kind == "extend":
            seconds = _coerce_int(body.get("seconds"))
            if seconds is None:
                days = _coerce_int(body.get("days"), 0)
                seconds = abs(days) * 86400
                direction = -1 if days < 0 else 1
            else:
                direction = body.get("direction")
                if isinstance(direction, str):
                    direction = {"extend": 1, "reduce": -1}.get(direction)
                direction = _coerce_int(direction)
                if direction not in (1, -1):
                    direction = 1
                seconds = abs(seconds)
            res = await svc.bulk_extend(seconds, direction,
                                        only_ids=only_ids)
        elif kind == "lte":
            res = await svc.bulk_set_limits(
                "lte", _coerce_int(body.get("value")),
                only_ids=only_ids)
        else:
            kind_limit = str(body.get("kind_limit") or "hwid")
            if kind_limit not in ("hwid", "lte"):
                kind_limit = "hwid"
            res = await svc.bulk_set_limits(
                kind_limit, _coerce_int(body.get("value")),
                only_ids=only_ids)
    except (TypeError, ValueError) as ex:
        return web.json_response({"error": "bad_params", "details": str(ex)},
                                 status=400)
    await _audit(actor, f"subs_bulk_{kind}",
                 f"scope={scope} updated: {res.get('updated')}")
    return web.json_response({"ok": True, "result": res,
                              "scope": scope})


async def lte_check_now(request):
    """Проверка LTE сейчас: тот же lte_fallback_tick(), что и кнопка
    «🔍 Проверить LTE сейчас» в ТГ (handle_paid_lte_check_now)."""
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    bot = get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    from types import SimpleNamespace
    from paidsub.handlers import lte_fallback_tick
    context = SimpleNamespace(bot=bot)
    try:
        r = await lte_fallback_tick(context)
    except Exception as ex:
        logging.error("админка: lte check-now: %s", ex)
        return web.json_response({"error": "lte_check_failed"}, status=502)
    if not r.get("ok"):
        return web.json_response(
            {"error": "lte_check_failed",
             "details": str(r.get("error") or "")}, status=502)
    await _audit(actor, "lte_check_now",
                 f"checked: {r['checked']}, switched: {r['switched']}, "
                 f"restored: {r['restored']}, panel_fail: {r['panel_fail']}")
    return web.json_response({"ok": True, "checked": r["checked"],
                              "switched": r["switched"],
                              "restored": r["restored"],
                              "panel_fail": r["panel_fail"]})


# ── Админские подписки ─────────────────────────────────────────────────────

async def admin_subs_list(request):
    """Админские подписки: вкладки, сортировка, поиск и счётчики — тот же
    экран, что handle_admin_subs_menu в ТГ (adminsub/handlers.py):
    list_subs / admin_counts / search_admin_subs из adminsub/storage.py."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from adminsub.storage import admin_counts, list_subs, search_admin_subs
    from core.database import _expire_to_iso, get_user_info
    try:
        page = max(1, int(request.query.get("page", "1")))
    except ValueError:
        return web.json_response({"error": "bad_page"}, status=400)
    scope = (request.query.get("scope") or "all").strip()
    if scope not in _ADMIN_SCOPES:
        scope = "all"
    sort = (request.query.get("sort") or "new").strip()
    if sort not in _ADMIN_SORTS:
        sort = "new"
    q = (request.query.get("q") or "").strip()
    if q:
        # Поиск — отдельным экраном, как в ТГ (apply_admin_search):
        # вкладки и страницы не применяются, найдено — до 20 строк.
        rows = await search_admin_subs(q)
        pages = 1
        page = 1
    else:
        rows, pages = await list_subs(page, scope, sort)
        page = min(page, pages)
    counts = await admin_counts()
    subs = []
    for r in rows:
        first_name, username = None, None
        if r[1]:
            info = await get_user_info(r[1])
            if info:
                first_name, username = info[1], info[2]
        subs.append({"id": r[0], "tg_id": r[1], "email": r[2],
                     "expire_date": _expire_to_iso(r[3]),
                     "total_gb": r[4], "created_at": str(r[5] or ""),
                     "first_name": first_name, "username": username})
    return web.json_response({"subs": subs, "page": page, "pages": pages,
                              "scope": scope, "sort": sort, "counts": counts})


async def admin_sub_card(request):
    """Живая карточка админской подписки — тот же набор, что у платной
    (sub_card) и в ТГ (handle_sub_view): состояние в панели, владелец,
    платежи, обе ссылки (sub + key)."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from adminsub.storage import get_sub
    try:
        sub_id = int(request.match_info["sub_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    row = await get_sub(sub_id)
    if not row:
        return web.json_response({"error": "not_found"}, status=404)
    from core.database import _expire_to_iso
    # Живое состояние из панели + владелец: get_sub_card в
    # paidsub/service.py (раньше карточка была голыми полями базы).
    panel, user, referrer = {}, None, None
    try:
        svc = _service()
        card = await svc.get_sub_card(sub_id, kind="admin")
        if card.get("ok"):
            panel = card.get("panel") or {}
            user = card.get("user")
            referrer = card.get("referrer")
    except Exception:
        logging.exception("админка: admin_sub_card #%s: панель недоступна",
                          sub_id)
    payments = {"items": [], "count": 0, "sum": 0}
    if row[1]:
        try:
            from core.database import user_payments
            prows, pcount, psum = await user_payments(row[1], 5)
            payments = {
                "items": [{"id": r[0], "provider": r[1] or "", "amount": r[2],
                           "status": r[3], "date": str(r[4] or "")[:16],
                           "promo": r[5] or ""} for r in prows],
                "count": pcount, "sum": psum,
            }
        except Exception:
            logging.exception("админка: admin_sub_card #%s: платежи "
                              "недоступны", sub_id)
    from config import (SUB_DISPLAY_DOMAIN, SUB_STORED_DOMAIN,
                        sub_url_for_display, sub_url_with_domain)
    raw_url = row[5] if len(row) > 5 else ""
    return web.json_response({"subscription": {
        "id": row[0], "tg_id": row[1], "email": row[2], "uuid": row[3],
        "sub_id": row[4], "sub_url": row[5],
        "expire_date": _expire_to_iso(row[6]),
        "limit_ip": row[7], "limit_hwid": row[8], "total_gb": row[9],
        "created_at": str(row[10] or ""),
        "lte_gb": row[11] if len(row) > 11 else None,
        "status": _admin_sub_status(row[6]),
        "times_renewed": None, "trial_period": None, "kind": "admin"},
        "panel": panel, "user": user, "referrer": referrer,
        "payments": payments,
        "display_url": sub_url_for_display(raw_url),
        "url_sub": sub_url_with_domain(raw_url, SUB_DISPLAY_DOMAIN),
        "url_key": sub_url_with_domain(raw_url, SUB_STORED_DOMAIN),
    })


async def admin_sub_create(request):
    """Создаёт админскую подписку: то же create_admin_sub(), что и
    do_create_sub() в ТГ — панель + база + уведомление юзеру."""
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    try:
        tg_id = int(body.get("tg_id") or 0)
    except (TypeError, ValueError):
        return web.json_response({"error": "bad_tg_id"}, status=400)
    if tg_id <= 0:
        return web.json_response({"error": "bad_tg_id"}, status=400)
    svc = _service()
    bot = get_bot()
    try:
        res = await svc.create_admin_sub(tg_id, bot=bot)
    except Exception as ex:
        logging.error("админка: admin-sub create %s: %s", tg_id, ex)
        return web.json_response({"error": "create_failed"}, status=502)
    if not res.get("ok"):
        if res.get("error") == "presets_not_ready":
            return web.json_response({"error": "presets_not_ready"},
                                     status=400)
        if res.get("error") == "user_not_found":
            return web.json_response({"error": "user_not_found"}, status=404)
        return web.json_response(
            {"error": "panel_failed",
             "details": str(res.get("error") or "")}, status=400)
    await _audit(actor, "admin_sub_create",
                 f"tg_id: {tg_id}, sub_id: {res['sub_id']}")
    return web.json_response({"ok": True, "subscription": {
        "id": res["sub_id"], "tg_id": tg_id, "email": res["email"],
        "expire": res["expire"], "sub_url": res["sub_url"]}})


# ── Рефералка ───────────────────────────────────────────────────────────────

async def referrals_get(request):
    """Экран рефералки: итоги и топ пригласивших
    (get_all_referral_stats + имена из users)."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from config import load_config
    from core.database import get_user_info
    from paidsub.storage import get_all_referral_stats
    cfg = load_config()
    stats = await get_all_referral_stats()
    top = []
    for ref_id, count in stats.get("top_referrers") or []:
        info = await get_user_info(ref_id)
        top.append({"tg_id": ref_id,
                    "first_name": info[1] if info else None,
                    "username": info[2] if info else None,
                    "count": int(count)})
    return web.json_response({
        "bonus": {"referral_bonus": cfg.get("referral_bonus"),
                  "referral_invited_bonus": cfg.get("referral_invited_bonus")},
        "total": int(stats.get("total") or 0),
        "rewarded": int(stats.get("rewarded") or 0),
        "total_bonus": int(stats.get("total_bonus") or 0),
        "top_referrers": top})


# ── Пресеты подписок ───────────────────────────────────────────────────────

async def subs_presets_get(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from config import load_config
    cfg = load_config()
    squads = []
    try:
        from services.remnawave import list_squads
        squads = await list_squads()
    except Exception:
        pass
    return web.json_response({"presets": {
        "paid_trial_period": cfg.get("paid_trial_period"),
        "paid_preset_hwid": cfg.get("paid_preset_hwid"),
        "paid_preset_traffic": cfg.get("paid_preset_traffic"),
        "paid_preset_lte": cfg.get("paid_preset_lte"),
        "paid_lte_squads": cfg.get("paid_lte_squads"),
        "paid_lte_fallback_squad": cfg.get("paid_lte_fallback_squad"),
        "rw_squads": cfg.get("rw_squads"),
    }, "squads": squads})


async def subs_presets_patch(request):
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    from config import atomic_update
    body = await _json_body(request)
    allowed = {"paid_trial_period", "paid_preset_hwid", "paid_preset_traffic",
               "paid_preset_lte", "paid_lte_squads",
               "paid_lte_fallback_squad", "rw_squads"}
    patch = {}
    for k, v in body.items():
        if k not in allowed:
            return web.json_response({"error": "forbidden_keys", "keys": [k]},
                                     status=403)
        if k in ("paid_trial_period", "paid_preset_hwid",
                 "paid_preset_traffic", "paid_preset_lte"):
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                return web.json_response({"error": "bad_value"}, status=400)
        patch[k] = v
    if patch:
        def _apply(cfg):
            cfg.update(patch)
        atomic_update(_apply)
    await _audit(actor, "subs_presets_update",
                 "keys: " + ", ".join(sorted(patch)))
    return web.json_response({"ok": True})


# ── Создание платной подписки ──────────────────────────────────────────────

_PRESET_KEYS = ("paid_trial_period", "paid_preset_hwid",
                "paid_preset_traffic")


def _presets_missing(cfg: dict) -> list:
    """Те же 3 ключа, что _paid_presets_ready в paidsub/handlers.py."""
    return [k for k in _PRESET_KEYS if cfg.get(k) is None]


async def subs_create_options(request):
    """Опции создания платной подписки: те же варианты, что в ТГ
    (paidsub/handlers.py handle_paid_create_sub): пробный период по
    пресетам + активные тарифы. Только чтение."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from config import load_config
    from core.database import list_tariffs
    from paidsub.time_parser import fmt_duration
    cfg = load_config()
    trial = cfg.get("paid_trial_period")
    tariffs = await list_tariffs(only_active=True)
    return web.json_response({
        "ready": not _presets_missing(cfg),
        "missing": _presets_missing(cfg),
        "trial": {"seconds": trial,
                  "label": fmt_duration(trial) if trial is not None else None},
        "tariffs": [{"id": t[0], "name": t[1], "period": t[2],
                     "price": t[3],
                     "label": fmt_duration(t[2])} for t in tariffs]})


async def subs_create(request):
    """Создать платную подписку напрямую: тот же смысл, что
    handle_paid_create_type + do_create_paid_sub в ТГ, с подтверждением,
    как остальные действия по подпискам в вебе.

    Тело: {tg_id, kind: "trial" | <id тарифа>}.
    Отличия от ТГ сознательные: период тарифа реально передаётся в
    create_paid_sub как period_seconds — сервис это поддерживает, а в
    ТГ create_period ставится в handle_paid_create_type, но нигде не
    читается (messages.py передаёт только trial), и выбор тарифа молча
    даёт длину пробного периода; уже есть платная подписка →
    409 already_has_sub, как в approve заявки, вместо молчаливого дубля
    в панели; реферальный бонус не начисляется — прямое создание в ТГ
    его тоже не делает (бонус только в approve заявки).
    """
    from aiohttp import web
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    body = await _json_body(request)
    try:
        tg_id = int(body.get("tg_id") or 0)
    except (TypeError, ValueError):
        return web.json_response({"error": "bad_id"}, status=400)
    if tg_id <= 0:
        return web.json_response({"error": "bad_id"}, status=400)
    kind = body.get("kind")
    trial = kind == "trial"
    tariff_id = None
    if not trial:
        # kind — только int (не bool) или строка цифр; float/bool/мусор —
        # bad_kind, а не молчаливое int() с усечением.
        if isinstance(kind, bool):
            return web.json_response({"error": "bad_kind"}, status=400)
        if isinstance(kind, int):
            tariff_id = kind
        elif isinstance(kind, str) and kind.isdigit():
            tariff_id = int(kind)
        else:
            return web.json_response({"error": "bad_kind"}, status=400)
        kind = tariff_id  # нормализованный kind — в токен подтверждения
    from config import load_config
    from paidsub.time_parser import fmt_duration
    cfg = load_config()
    missing = _presets_missing(cfg)
    if missing:
        return web.json_response({"error": "presets_not_ready",
                                  "missing": missing}, status=409)
    tariff = None
    if not trial:
        from core.database import get_tariff
        tariff = await get_tariff(tariff_id)
        if not tariff or not tariff[4]:
            return web.json_response({"error": "bad_tariff"}, status=400)
        label = (f"💳 Платная подписка · {fmt_duration(tariff[2])} · "
                 f"{tariff[3]} ₽")
        period_seconds = int(tariff[2])
    else:
        label = (f"🆓 Пробная подписка · "
                 f"{fmt_duration(cfg.get('paid_trial_period'))}")
        period_seconds = None
    token = body.get("confirm_token")
    if not token:
        tok = issue_confirm(actor, "paid_sub_create",
                            {"tg_id": tg_id, "kind": kind},
                            f"Создать подписку ({label}) для {tg_id}")
        return confirm_needed_response(tok, f"Создать подписку ({label}) "
                                            f"для {tg_id}")
    payload = take_confirm(actor, token, "paid_sub_create")
    if payload is None or payload.get("tg_id") != tg_id:
        return web.json_response({"error": "bad_confirm"}, status=403)
    # kind мог поменяться между подтверждением и применением — берём
    # тот, что в токене, и перепроверяем тариф и пресеты.
    kind = payload.get("kind")
    trial = kind == "trial"
    if not trial:
        try:
            tariff_id = int(kind)
        except (TypeError, ValueError):
            return web.json_response({"error": "bad_confirm"}, status=403)
        from core.database import get_tariff
        tariff = await get_tariff(tariff_id)
        if not tariff or not tariff[4]:
            return web.json_response({"error": "bad_tariff"}, status=400)
        period_seconds = int(tariff[2])
    else:
        period_seconds = None
    missing = _presets_missing(load_config())
    if missing:
        return web.json_response({"error": "presets_not_ready",
                                  "missing": missing}, status=409)
    from paidsub.storage import get_paid_sub_by_tg_id
    if await get_paid_sub_by_tg_id(tg_id):
        return web.json_response({"error": "already_has_sub"}, status=409)
    svc = _service()
    bot = get_bot()
    try:
        res = await svc.create_paid_sub(tg_id, trial=trial,
                                        period_seconds=period_seconds,
                                        bot=bot)
    except Exception as ex:
        logging.error("админка: paid sub create %s: %s", tg_id, ex)
        return web.json_response({"error": "create_failed"}, status=502)
    if not res.get("ok"):
        return web.json_response(
            {"error": "panel_failed",
             "details": str(res.get("error") or "")}, status=502)
    # Уведомление юзеру — тот же текст «Подписка готова!», что шлёт
    # do_create_paid_sub; ссылка — показная, через sub.drbl.tech.
    notified = False
    if bot is not None:
        from config import sub_url_for_display
        sub_link = sub_url_for_display(res["sub_url"])
        notified = await _notify_request_user(
            bot, tg_id,
            "🎉 <b>Подписка готова!</b>\n\n"
            f"<blockquote>📅 Действует до: <b>{res['expire'][:16]}</b></blockquote>\n\n"
            "🔑 <b>Ссылка для подключения</b>\n"
            f"<code>{sub_link}</code>\n\n"
            "<i>Нажмите на ссылку — она скопируется — и вставьте её в INCY.</i>")
    await _audit(actor, "paid_sub_create",
                 f"tg_id: {tg_id}, sub_id: {res['sub_id']}, "
                 f"{'trial' if trial else 'tariff ' + str(tariff_id)}")
    return web.json_response({"ok": True, "notified": notified,
                              "subscription": {"id": res["sub_id"],
                                               "email": res["email"],
                                               "expire": res["expire"]}})


# ── Регистрация ────────────────────────────────────────────────────────────

def register(app) -> None:
    """Маршруты монтируются относительно /api/admin (см. build_admin_app)."""
    app.router.add_get("/users", users_search)
    app.router.add_get("/users/recent", users_recent)
    app.router.add_get("/users/list", users_list)
    app.router.add_get("/users/export", users_export)
    app.router.add_get("/users/{tg_id}", user_profile)
    app.router.add_get("/users/{tg_id}/activity", user_activity)
    app.router.add_post("/users/{tg_id}/dm", user_dm)
    app.router.add_post("/users/{tg_id}/gift", user_gift)
    # Статические пути — ДО шаблонов {sub_id}, иначе aiohttp отдаст
    # /subs/presets и /subs/bulk/* в хендлеры подписок.
    app.router.add_get("/subs/presets", subs_presets_get)
    app.router.add_post("/subs/presets", subs_presets_patch)
    app.router.add_get("/subs/create-options", subs_create_options)
    app.router.add_post("/subs/create", subs_create)
    app.router.add_patch("/subs/presets", subs_presets_patch)
    app.router.add_get("/subs/bulk/scopes", bulk_scopes)
    app.router.add_post("/subs/bulk/{kind}", subs_bulk)
    app.router.add_post("/subs/lte/check-now", lte_check_now)
    app.router.add_get("/subs/requests", subs_requests_list)
    app.router.add_post("/subs/requests/{tg_id}/approve",
                        lambda req: _subs_request_action(req, "approve"))
    app.router.add_post("/subs/requests/{tg_id}/reject",
                        lambda req: _subs_request_action(req, "reject"))
    app.router.add_get("/subs", subs_list)
    app.router.add_get("/subs/export", subs_export)
    app.router.add_get("/admin-subs", admin_subs_list)
    app.router.add_post("/admin-subs", admin_sub_create)
    app.router.add_get("/admin-subs/{sub_id}", admin_sub_card)
    app.router.add_get("/admin-subs/{sub_id}/history", admin_sub_history)
    app.router.add_get("/admin-subs/{sub_id}/devices", admin_sub_devices)
    app.router.add_get("/admin-subs/{sub_id}/ips", admin_sub_ips)
    app.router.add_post("/admin-subs/{sub_id}/devices/delete",
                        admin_sub_device_delete)
    app.router.add_post("/admin-subs/{sub_id}/devices/clear",
                        admin_sub_devices_clear)
    app.router.add_get("/referrals", referrals_get)
    app.router.add_get("/subs/{sub_id}", sub_card)
    app.router.add_get("/subs/{sub_id}/history", sub_history)
    for action in ("toggle", "freeze", "delete", "reissue", "extend",
                   "expire", "hwid", "traffic", "lte", "trial"):
        app.router.add_post(
            f"/subs/{{sub_id}}/{action}",
            lambda req, a=action: _sub_action(req, a))
    app.router.add_get("/subs/{sub_id}/devices", sub_devices)
    app.router.add_get("/subs/{sub_id}/ips", sub_ips)
    app.router.add_post("/subs/{sub_id}/devices/delete", sub_device_delete)
    app.router.add_post("/subs/{sub_id}/devices/clear", sub_devices_clear)
