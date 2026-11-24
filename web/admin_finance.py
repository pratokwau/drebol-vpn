"""Веб-админка Drebol VPN — фаза 2: финансы и рассылка.

Маршруты добавляются в подприложение админки через register(app):
родитель вызывает её из build_admin_app() в web/admin_api.py.
Пути здесь — БЕЗ префикса /api/admin: подприложение монтируется
в web/webapi.py как app.add_subapp("/api/admin", build_admin_app()),
а фаза 1 регистрирует маршруты так же ("/auth/telegram" и т.д.).
С полным префиксом получился бы двойной /api/admin/api/admin/.

Всё переиспользует те же функции, что и ТГ-админка:
платежи и возвраты — handlers/payments.py + core/database.py,
сверка — handlers/reconcile.py, рассылка — handlers/broadcast.py,
тарифы/серверы — core/database.py, промокоды — paidsub/storage.py,
Platega — services/platega_api.py. Никаких секретов наружу:
platega_secret и прочие ключи — только запись, в ответах лишь маска.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

from web import admin_api as _admin

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

# ── Общие помощники ──────────────────────────────────────────────────────────

async def _body(request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _actor_or_401(request):
    """Актор или (None, ответ 401) — для читающих эндпоинтов."""
    from aiohttp import web
    try:
        return await _admin._require_actor(request), None
    except Exception:
        return None, web.json_response({"error": "no_session"}, status=401)


def _int_id(raw, name: str = "id"):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_period(value) -> bool:
    return isinstance(value, str) and bool(_PERIOD_RE.match(value))


def _valid_date(value) -> bool:
    if value is None or value == "":
        return True
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%d.%m.%Y")
    except ValueError:
        return False
    return True


def _payment_list_row(r) -> dict:
    return {"id": r[0], "tg_id": r[1], "provider": r[2], "amount": r[3],
            "status": r[4], "date": str(r[5] or "")[:16],
            "first_name": r[6] or "", "username": r[7] or "",
            "promo": r[8] or "", "period_seconds": r[9]}


def _payment_full_row(p, partial: int = 0, refunded_at=None) -> dict:
    return {"id": p[0], "tg_id": p[1], "provider": p[2],
            "external_id": p[3], "amount": p[4],
            "period_seconds": p[5], "promo": p[6] or "",
            "status": p[7], "pay_url": p[8] or "", "error": p[9] or "",
            "created": str(p[10] or "")[:16], "paid": str(p[11] or "")[:16],
            "first_name": p[12] or "", "username": p[13] or "",
            "partial_refunded": int(partial or 0),
            "refunded_at": str(refunded_at or "")[:16] if refunded_at else None}


def _tariff_row(t) -> dict:
    return {"id": t[0], "name": t[1], "period_seconds": t[2],
            "price": t[3], "active": bool(t[4]), "sort_order": t[5]}


def _server_row(s) -> dict:
    return {"id": s[0], "name": s[1], "price_rub": s[2],
            "pay_day": s[3], "active": bool(s[4])}


def _promo_list_row(r) -> dict:
    return {"id": r[0], "code": r[1], "percent": r[2],
            "expires_at": r[3], "active": bool(r[4]),
            "owner_tg_id": r[5], "max_uses": r[6], "kind": r[7],
            "days": r[8], "first_only": bool(r[9]), "uses": r[10]}


def _promo_row(p) -> dict:
    return {"id": p[0], "code": p[1], "percent": p[2],
            "expires_at": p[3], "active": bool(p[4]),
            "created_at": str(p[5] or "")[:16], "owner_tg_id": p[6],
            "max_uses": p[7], "kind": p[8], "days": p[9],
            "note": p[10] or "", "source": p[11] or "",
            "first_only": bool(p[12]) if len(p) > 12 else False}


def _parse_reward(body: dict):
    """(kind, value, error): награда промокода из тела запроса."""
    kind = body.get("kind")
    if kind is None:
        kind = "days" if body.get("days") else "percent"
    if kind not in ("percent", "days"):
        return None, None, "kind must be percent or days"
    value = body.get("value")
    if value is None:
        value = body.get("percent") if kind == "percent" else body.get("days")
    if not _is_int(value):
        return None, None, "value must be an int"
    if kind == "percent" and not 1 <= value <= 100:
        return None, None, "percent must be 1..100"
    if kind == "days" and not 1 <= value <= 365:
        return None, None, "days must be 1..365"
    return kind, value, None


def _parse_buttons_field(body: dict):
    """Кнопки рассылки: строка -> (spec, error)."""
    from handlers.broadcast import parse_buttons
    raw = body.get("buttons")
    if raw is None or raw == "":
        return None, None
    if not isinstance(raw, str):
        return None, "buttons must be a string"
    spec, error = parse_buttons(raw)
    if error:
        return None, error
    return spec, None


def _broadcast_payload(body: dict):
    """Проверяет тело рассылки. Возвращает (data, error_response)."""
    from aiohttp import web
    from handlers.broadcast import SEGMENTS
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return None, web.json_response({"error": "empty_text"}, status=400)
    if len(text) > 4096:
        return None, web.json_response({"error": "text_too_long"}, status=400)
    segment = body.get("segment") or "all"
    if segment not in SEGMENTS:
        return None, web.json_response({"error": "bad_segment"}, status=400)
    spec, error = _parse_buttons_field(body)
    if error:
        return None, web.json_response({"error": "bad_buttons",
                                        "details": error}, status=400)
    photo = body.get("photo")
    photo_id = photo if isinstance(photo, str) and photo else None
    return {"text": text, "segment": segment, "buttons": spec,
            "photo": photo_id}, None


# ── Платежи ──────────────────────────────────────────────────────────────────

# Отображение фильтра статуса в WHERE — то же, что в
# core.database.list_payments. Запрос живёт здесь, а не в core:
# core/database.py — вне web/, а прецедент локального SQL в вебе уже
# есть (обогащение в admin_users.py, проход 7).
_PAYMENT_STATUS_WHERE = {
    "paid": "p.status = 'paid'",
    "pending": "p.status = 'pending'",
    "failed": "p.status IN ('canceled','expired','error')",
    "refunds": "p.status IN ('refunded','refund_pending','chargebacked')",
    "all": "",
}

_PAYMENT_LIST_COLS = (
    "p.id, p.tg_id, p.provider, p.amount, p.status,"
    " datetime(COALESCE(p.paid_at, p.created_at), 'localtime') AS ts,"
    " u.first_name, u.username, p.promo_code, p.period_seconds"
)

_PAYMENTS_PER_PAGE = 25


def _payments_where(status: str, provider, q: str, text_ids=None):
    """(where_sql, params): общий фильтр списка оплат. q — TG ID или
    ID счёта (только цифры); text_ids — ID счетов, чьё имя/username
    содержит текстовый запрос (см. _search_payment_ids)."""
    clauses, params = [], []
    sw = _PAYMENT_STATUS_WHERE[status]
    if sw:
        clauses.append(sw)
    if provider:
        clauses.append("p.provider = ?")
        params.append(provider)
    if text_ids is not None:
        if text_ids:
            clauses.append(
                "p.id IN (" + ",".join("?" * len(text_ids)) + ")")
            params.extend(text_ids)
        else:
            clauses.append("1 = 0")
    elif q:
        clauses.append("(p.tg_id = ? OR p.id = ?)")
        params.extend([int(q), int(q)])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


async def _search_payment_ids(q: str) -> list:
    """ID счетов, у которых имя или username содержит q. Поиск — в
    Python с casefold, как search_paid_subs в ТГ: SQL LIKE в SQLite
    нечувствителен к регистру только для ASCII, и «иван» не нашёл бы
    «Иван». Запрос лёгкий — только три маленькие колонки."""
    from core.database import DB_PATH
    import aiosqlite
    needle = q.casefold()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT p.id, u.first_name, u.username FROM payments p "
                "LEFT JOIN users u ON u.id = p.tg_id") as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows
            if needle in (r[1] or "").casefold()
            or needle in (r[2] or "").casefold()]


async def _payments_search_params(q: str) -> tuple:
    """Нормализация поиска оплат: «@» — снять, цифры — TG ID или
    ID счёта, текст — ID счетов по имени/username (casefold, как
    search_paid_subs в ТГ). Общая для списка и экспорта."""
    q = (q or "").strip()
    if q.startswith("@"):
        q = q[1:].strip()
    numeric = q.isdigit() and len(q) <= 18
    text_ids = None
    if q and not numeric:
        text_ids = await _search_payment_ids(q)
    return (q if numeric else ""), text_ids


async def _list_payments_filtered(page: int, status: str, provider, q: str):
    """Страница оплат + счётчики: те же колонки и порядок, что
    core.database.list_payments, плюс фильтры по провайдеру и поиску.
    Возвращает dict: rows, total_pages, total, total_amount,
    providers (провайдеры со счётчиками в выборке без учёта фильтра
    по провайдеру) и all_providers (все провайдеры в таблице —
    для проверки значения provider)."""
    from core.database import DB_PATH
    import aiosqlite
    q_num, text_ids = await _payments_search_params(q)
    where, params = _payments_where(status, provider, q_num, text_ids)
    where_np, params_np = _payments_where(status, None, q_num, text_ids)
    offset = (page - 1) * _PAYMENTS_PER_PAGE
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(p.amount), 0) FROM payments p "
                f"LEFT JOIN users u ON u.id = p.tg_id {where}", params) as cur:
            total, total_amount = await cur.fetchone()
        async with db.execute(
                f"SELECT {_PAYMENT_LIST_COLS} FROM payments p "
                f"LEFT JOIN users u ON u.id = p.tg_id {where} "
                f"ORDER BY p.id DESC LIMIT ? OFFSET ?",
                params + [_PAYMENTS_PER_PAGE, offset]) as cur:
            rows = await cur.fetchall()
        async with db.execute(
                "SELECT p.provider, COUNT(*) FROM payments p "
                f"LEFT JOIN users u ON u.id = p.tg_id {where_np} "
                "GROUP BY p.provider ORDER BY 2 DESC, 1",
                params_np) as cur:
            providers = await cur.fetchall()
        async with db.execute(
                "SELECT DISTINCT provider FROM payments") as cur:
            all_providers = [r[0] for r in await cur.fetchall()]
    total_pages = max(1, (total + _PAYMENTS_PER_PAGE - 1) // _PAYMENTS_PER_PAGE)
    return {"rows": rows, "total_pages": total_pages, "total": total,
            "total_amount": total_amount, "providers": providers,
            "all_providers": all_providers}


async def _list_payments_all(status: str, provider, q: str):
    """Все оплаты выборки без пагинации (для экспорта): те же фильтры,
    что _list_payments_filtered. Возвращает dict: rows, total,
    all_providers."""
    from core.database import DB_PATH
    import aiosqlite
    q_num, text_ids = await _payments_search_params(q)
    where, params = _payments_where(status, provider, q_num, text_ids)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT COUNT(*) FROM payments p "
                f"LEFT JOIN users u ON u.id = p.tg_id {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
                f"SELECT {_PAYMENT_LIST_COLS} FROM payments p "
                f"LEFT JOIN users u ON u.id = p.tg_id {where} "
                "ORDER BY p.id DESC", params) as cur:
            rows = await cur.fetchall()
        async with db.execute(
                "SELECT DISTINCT provider FROM payments") as cur:
            all_providers = [r[0] for r in await cur.fetchall()]
    return {"rows": rows, "total": total, "all_providers": all_providers}


async def payments_export(request):
    """Экспорт оплат в CSV: те же статус/провайдер/поиск, что в списке
    (тот же _payments_where), без пагинации. Сверх EXPORT_MAX_ROWS —
    409 too_large с total, а не обрезанный молча файл."""
    from aiohttp import web
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    from datetime import date
    from handlers.control import EXPORT_MAX_ROWS
    status = request.query.get("status") or "all"
    if status not in _PAYMENT_STATUS_WHERE:
        return web.json_response({"error": "bad_status"}, status=400)
    provider = (request.query.get("provider") or "").strip()
    q = request.query.get("q") or ""
    res = await _list_payments_all(status, provider or None, q)
    if provider and provider not in res["all_providers"]:
        return web.json_response({"error": "bad_provider"}, status=400)
    if res["total"] > EXPORT_MAX_ROWS:
        return web.json_response(
            {"error": "too_large", "total": res["total"],
             "max": EXPORT_MAX_ROWS}, status=409)
    return _admin._csv_response(
        ["id", "date", "tg_id", "first_name", "username", "provider",
         "amount", "status", "promo_code", "period_days"],
        [[r[0], r[5], r[1], r[6] or "",
          ("@" + r[7]) if r[7] else "", r[2] or "", r[3], r[4],
          r[8] or "",
          (int(r[9] // 86400) if r[9] else "")] for r in res["rows"]],
        f"drebol-payments-{status}-{date.today().isoformat()}.csv")


async def payments_list(request):
    from aiohttp import web
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    # Без параметра — ВСЕ статусы: фронт шлёт пустую строку для «Все
    # статусы», а прежний дефолт "paid" молча прятал остальные счета
    # (оплата висела в карточке юзера, но в списке её не было).
    status = request.query.get("status") or "all"
    if status not in _PAYMENT_STATUS_WHERE:
        return web.json_response({"error": "bad_status"}, status=400)
    try:
        page = int(request.query.get("page") or 1)
    except ValueError:
        return web.json_response({"error": "bad_page"}, status=400)
    page = max(1, page)
    provider = (request.query.get("provider") or "").strip()
    q = request.query.get("q") or ""
    res = await _list_payments_filtered(page, status, provider or None, q)
    if provider and provider not in res["all_providers"]:
        return web.json_response({"error": "bad_provider"}, status=400)
    return web.json_response(
        {"payments": [_payment_list_row(r) for r in res["rows"]],
         "page": page, "total_pages": res["total_pages"],
         "status": status, "provider": provider, "q": q.strip(),
         "total": res["total"], "total_amount": res["total_amount"],
         "providers": [{"provider": p, "count": c}
                       for p, c in res["providers"]]})


async def payment_detail(request):
    from aiohttp import web
    from core.database import get_payment_full, get_payment_money
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    pid = _int_id(request.match_info.get("pid"))
    if pid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    p = await get_payment_full(pid)
    if not p:
        return web.json_response({"error": "no_payment"}, status=404)
    partial, refunded_at = await get_payment_money(pid)
    return web.json_response({"payment": _payment_full_row(p, partial, refunded_at)})


# Лейблы живого статуса — те же, что _PLATEGA_STATUS_LABEL
# в handlers/payprovider.py (handle_platega_payment).
_PLATEGA_STATUS_LABEL = {
    "paid": "✅ оплачен",
    "pending": "⏳ ожидает оплаты",
    "canceled": "❌ отменён",
    "chargebacked": "↩️ возврат",
    "partially_refunded": "↩️ частично возвращён",
}


async def payment_platega_check(request):
    """Живой статус счёта в Platega — паритет с ТГ handle_platega_payment:
    статус/сумма/оплачен/способ/заказ из API + начисление из журнала
    и сравнение со статусом в базе бота. Только чтение, аудита нет."""
    from aiohttp import web
    from core.database import get_payment_credit, get_payment_full
    import services.platega_api as pg
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    pid = _int_id(request.match_info.get("pid"))
    if pid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    p = await get_payment_full(pid)
    if not p:
        return web.json_response({"error": "no_payment"}, status=404)
    (_id, _tg, provider, ext_id, amount, _period, _promo,
     status, _url, _err, _created, _paid, _fn, _un) = p
    if provider != "platega" or not ext_id:
        return web.json_response({"error": "not_platega"}, status=409)
    r = await pg.get_status(ext_id)
    if not r.get("ok"):
        if r.get("not_found"):
            return web.json_response({"error": "platega_not_found"},
                                     status=404)
        return web.json_response({"error": "platega_error",
                                  "details": r.get("error")}, status=502)
    raw = r.get("raw") or {}
    method = pg.PAYMENT_METHODS.get(raw.get("paymentMethod"),
                                    raw.get("paymentMethod") or "")
    credit = await get_payment_credit(pid)
    live_status = r.get("status")
    return web.json_response({
        "payment_id": pid,
        "live": {"status": live_status,
                 "status_label": _PLATEGA_STATUS_LABEL.get(live_status,
                                                           live_status),
                 "platega_status": r.get("platega_status"),
                 "amount": r.get("amount"),
                 "paid": bool(r.get("paid")),
                 "method": method if isinstance(method, str) else str(method),
                 "payload": r.get("payload") or ""},
        "bot": {"status": status, "amount": amount, "external_id": ext_id},
        "credited": bool(credit),
        "match": live_status == status})


async def payment_refund(request):
    """Возврат платежа: двухшаговое подтверждение, потом возврат
    в Platega и finalize_refund(). Идемпотентно: повторный вызов
    по уже возвращённому счёту — no-op (claim_refund внутри
    finalize_refund тоже атомарен и второй раз ничего не делает)."""
    from aiohttp import web
    from core.database import (
        get_payment_full, set_payment_status, set_refund_revoke,
    )
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    pid = _int_id(request.match_info.get("pid"))
    if pid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    p = await get_payment_full(pid)
    if not p:
        return web.json_response({"error": "no_payment"}, status=404)
    (_id, _tg, provider, ext_id, amount, _period, _promo,
     status, _url, _err, _created, _paid, _fn, _un) = p
    if status in ("refunded", "chargebacked"):
        return web.json_response({"ok": True, "already": True,
                                  "payment_id": pid, "status": status})
    if provider != "platega" or status != "paid" or not ext_id:
        return web.json_response({"error": "not_refundable"}, status=409)
    body = await _body(request)
    revoke = body.get("revoke")
    if revoke is not None and not isinstance(revoke, bool):
        return web.json_response({"error": "revoke must be bool"}, status=400)
    token = body.get("confirm_token") or ""
    if not token:
        summary = (f"Вернуть платёж #{pid} — {amount} ₽ "
                   f"({'срок отозвать' if revoke else 'срок оставить' if revoke is False else 'срок — по настройке'})")
        token = _admin.issue_confirm(
            actor, "payment_refund",
            {"payment_id": pid, "revoke": revoke}, summary)
        return _admin.confirm_needed_response(token, summary)
    payload = _admin.take_confirm(actor, token, "payment_refund")
    if not payload or payload.get("payment_id") != pid:
        return web.json_response({"error": "bad_confirm"}, status=400)
    revoke = payload.get("revoke")
    import services.platega_api as pg
    r = await pg.refund(ext_id)
    if not r.get("ok"):
        return web.json_response({"error": "platega",
                                  "details": r.get("error")}, status=502)
    if revoke is not None:
        await set_refund_revoke(pid, 1 if revoke else 0)
    await set_payment_status(pid, "refund_pending")
    if r.get("accepted"):
        bot = _admin.get_bot()
        if bot is None:
            # Возврат запущен, а бота для доведения до конца нет —
            # счёт остаётся в refund_pending, итог придёт колбэком.
            await _admin._audit(actor, "payment_refund",
                                f"payment #{pid} {amount} ₽ accepted, no bot")
            return web.json_response({"ok": True, "payment_id": pid,
                                      "status": "refund_pending",
                                      "accepted": True,
                                      "pending_finalize": True})
        from handlers.payments import finalize_refund
        await finalize_refund(SimpleNamespace(bot=bot), pid, revoke=revoke)
        await _admin._audit(actor, "payment_refund",
                            f"payment #{pid} {amount} ₽ revoke={revoke}")
        return web.json_response({"ok": True, "payment_id": pid,
                                  "status": "refunded", "accepted": True})
    await _admin._audit(actor, "payment_refund",
                        f"payment #{pid} {amount} ₽ manual control")
    return web.json_response({"ok": True, "payment_id": pid,
                              "status": "refund_pending", "accepted": False})


# ── Финансы ──────────────────────────────────────────────────────────────────

async def finance_hub(request):
    from aiohttp import web
    from core.database import finance_summary, payments_summary, servers_with_status
    from handlers.finance import current_period
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    period = request.query.get("period") or current_period()
    if not _valid_period(period):
        return web.json_response({"error": "bad_period"}, status=400)
    summary = await finance_summary(period)
    return web.json_response({"period": period, "summary": summary,
                              "payments": await payments_summary(),
                              "servers": await servers_with_status(period)})


# ── Сверка ───────────────────────────────────────────────────────────────────

def _issue_dict(row, issue) -> dict:
    return {"payment_id": row[0], "tg_id": row[1],
            "external_id": row[2], "amount": row[3], "status": row[4],
            "partial_refunded": row[5], "kind": issue.get("kind"),
            "text": issue.get("text"), "fix": issue.get("fix"),
            "impact": issue.get("impact") or 0}


async def reconcile_run(request):
    from aiohttp import web
    from handlers.reconcile import run_reconciliation
    import services.platega_api as pg
    actor, err = await _actor_or_401(request)
    if err is not None:
        return err
    if not pg.is_configured():
        return web.json_response({"error": "platega_not_configured"},
                                 status=503)
    res = await run_reconciliation()
    await _admin._audit(actor, "reconcile_run",
                        f"checked {res['checked']}, issues {len(res['issues'])}")
    return web.json_response({
        "checked": res["checked"],
        "issues": [_issue_dict(row, iss) for row, iss in res["issues"]],
        "impact": res["impact"],
        "fixable": [_issue_dict(row, iss) for row, iss in res["fixable"]],
    })


async def reconcile_fix(request):
    """Исправление правит ТОЛЬКО денежные поля (status,
    partial_refunded) — срок подписки не трогается никогда.
    Исправления присылает клиент (из ответа /reconcile/run);
    первый вызов возвращает confirm_token, второй применяет."""
    from aiohttp import web
    from core.database import claim_refund, set_partial_refunded
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    fixes = body.get("fixes")
    if not isinstance(fixes, list) or not fixes:
        return web.json_response({"error": "no_fixes"}, status=400)
    clean = []
    for fix in fixes:
        if not isinstance(fix, dict):
            return web.json_response({"error": "bad_fix"}, status=400)
        pid = _int_id(fix.get("payment_id"))
        kind = fix.get("kind")
        if pid is None or kind not in ("full", "partial"):
            return web.json_response({"error": "bad_fix"}, status=400)
        if kind == "partial":
            amount = fix.get("amount")
            if not _is_int(amount) or amount < 0:
                return web.json_response({"error": "bad_fix"}, status=400)
            clean.append({"payment_id": pid, "kind": kind, "amount": amount})
        else:
            clean.append({"payment_id": pid, "kind": kind})
    token = body.get("confirm_token") or ""
    if not token:
        summary = f"Исправить расхождения сверки: {len(clean)} шт."
        token = _admin.issue_confirm(actor, "reconcile_fix",
                                     {"fixes": clean}, summary)
        return _admin.confirm_needed_response(token, summary)
    payload = _admin.take_confirm(actor, token, "reconcile_fix")
    if not payload:
        return web.json_response({"error": "bad_confirm"}, status=400)
    done, already = [], []
    for fix in payload.get("fixes", []):
        pid = fix["payment_id"]
        if fix["kind"] == "full":
            if await claim_refund(pid):
                done.append({"payment_id": pid, "kind": "full"})
            else:
                already.append({"payment_id": pid, "kind": "full"})
        else:
            await set_partial_refunded(pid, int(fix["amount"]))
            done.append({"payment_id": pid, "kind": "partial",
                         "amount": int(fix["amount"])})
    await _admin._audit(actor, "reconcile_fix",
                        "payments: " + ", ".join(str(d["payment_id"]) for d in done))
    return web.json_response({"ok": True, "fixed": done, "already": already})


# ── Тарифы ───────────────────────────────────────────────────────────────────

async def tariffs_list(request):
    from aiohttp import web
    from core.database import list_tariffs
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    rows = await list_tariffs()
    return web.json_response({"tariffs": [_tariff_row(t) for t in rows]})


async def tariff_create(request):
    from aiohttp import web
    from core.database import add_tariff, get_tariff
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    name = body.get("name")
    period = body.get("period_seconds")
    price = body.get("price")
    if (not isinstance(name, str) or not name.strip() or len(name) > 64
            or not _is_int(period) or period <= 0
            or not _is_int(price) or price < 0):
        return web.json_response({"error": "bad_tariff"}, status=400)
    tid = await add_tariff(name.strip(), period, price)
    await _admin._audit(actor, "tariff_create",
                        f"tariff #{tid} {name.strip()} {price} ₽")
    row = await get_tariff(tid)
    return web.json_response({"ok": True, "tariff": _tariff_row(row)})


async def tariff_detail(request):
    from aiohttp import web
    from core.database import get_tariff
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    tid = _int_id(request.match_info.get("tid"))
    if tid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    row = await get_tariff(tid)
    if not row:
        return web.json_response({"error": "no_tariff"}, status=404)
    return web.json_response({"tariff": _tariff_row(row)})


async def tariff_patch(request):
    from aiohttp import web
    from core.database import get_tariff, update_tariff_field
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    tid = _int_id(request.match_info.get("tid"))
    if tid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    if not await get_tariff(tid):
        return web.json_response({"error": "no_tariff"}, status=404)
    body = await _body(request)
    allowed = {"name", "period_seconds", "price", "active", "sort_order"}
    changed = []
    for field, value in body.items():
        if field not in allowed:
            return web.json_response({"error": "bad_field", "field": field},
                                     status=400)
        if field == "name":
            if not isinstance(value, str) or not value.strip() or len(value) > 64:
                return web.json_response({"error": "bad_value"}, status=400)
            value = value.strip()
        elif field == "active":
            if not isinstance(value, bool):
                return web.json_response({"error": "bad_value"}, status=400)
            value = 1 if value else 0
        elif field in ("period_seconds", "price", "sort_order"):
            if not _is_int(value) or value < 0 or (
                    field == "period_seconds" and value <= 0):
                return web.json_response({"error": "bad_value"}, status=400)
        await update_tariff_field(tid, field, value)
        changed.append(field)
    if not changed:
        return web.json_response({"error": "no_fields"}, status=400)
    await _admin._audit(actor, "tariff_update",
                        f"tariff #{tid}: {', '.join(changed)}")
    row = await get_tariff(tid)
    return web.json_response({"ok": True, "tariff": _tariff_row(row)})


async def tariff_delete(request):
    from aiohttp import web
    from core.database import delete_tariff, get_tariff
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    tid = _int_id(request.match_info.get("tid"))
    if tid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    if not await get_tariff(tid):
        return web.json_response({"error": "no_tariff"}, status=404)
    await delete_tariff(tid)
    await _admin._audit(actor, "tariff_delete", f"tariff #{tid}")
    return web.json_response({"ok": True})


# ── Промокоды ────────────────────────────────────────────────────────────────

async def promos_list(request):
    from aiohttp import web
    from paidsub.storage import list_promos_page
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    tab = request.query.get("tab") or "all"
    if tab not in ("all", "common", "personal", "dead"):
        return web.json_response({"error": "bad_tab"}, status=400)
    try:
        page = max(1, int(request.query.get("page") or 1))
    except ValueError:
        return web.json_response({"error": "bad_page"}, status=400)
    rows, pages, total = await list_promos_page(tab, page, 10)
    return web.json_response({"promos": [_promo_list_row(r) for r in rows],
                              "page": page, "pages": pages, "total": total,
                              "tab": tab})


async def promo_create(request):
    from aiohttp import web
    from paidsub.storage import create_promo, get_promo
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    code = body.get("code")
    if (not isinstance(code, str) or not code.strip()
            or len(code.strip()) > 32 or " " in code.strip()):
        return web.json_response({"error": "bad_code"}, status=400)
    code = code.strip().upper()
    kind, value, rerr = _parse_reward(body)
    if rerr:
        return web.json_response({"error": rerr}, status=400)
    max_uses = body.get("max_uses", 0)
    if not _is_int(max_uses) or max_uses < 0:
        return web.json_response({"error": "bad_max_uses"}, status=400)
    expires_at = body.get("expires_at")
    if expires_at == "":
        expires_at = None
    if not _valid_date(expires_at):
        return web.json_response({"error": "bad_expires_at"}, status=400)
    first_only = body.get("first_only", False)
    if not isinstance(first_only, bool):
        return web.json_response({"error": "bad_first_only"}, status=400)
    owner = body.get("owner_tg_id")
    if owner is not None and not _is_int(owner):
        return web.json_response({"error": "bad_owner"}, status=400)
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        return web.json_response({"error": "bad_note"}, status=400)
    if await get_promo(code):
        return web.json_response({"error": "code_exists"}, status=409)
    ok = await create_promo(
        code, value if kind == "percent" else 0, expires_at,
        owner_tg_id=owner, max_uses=max_uses, kind=kind,
        days=value if kind == "days" else 0, note=note, source="manual",
        first_only=1 if first_only else 0)
    if not ok:
        return web.json_response({"error": "create_failed"}, status=409)
    await _admin._audit(actor, "promo_create", f"code {code} {kind} {value}")
    row = await get_promo(code)
    return web.json_response({"ok": True, "promo": _promo_row(row)})


async def promo_detail(request):
    from aiohttp import web
    from paidsub.storage import (
        get_promo, promo_income, promo_use_count, promo_users,
    )
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    code = (request.match_info.get("code") or "").upper()
    row = await get_promo(code)
    if not row:
        return web.json_response({"error": "no_promo"}, status=404)
    pays, income = await promo_income(code)
    users = await promo_users(code, 25)
    return web.json_response({
        "promo": _promo_row(row),
        "uses": await promo_use_count(code),
        "pays": pays, "income": income,
        "users": [{"tg_id": u[0], "first_name": u[1] or "",
                   "username": u[2] or "", "used_at": str(u[3] or "")[:16],
                   "paid": u[4]} for u in users],
    })


async def promo_toggle(request):
    from aiohttp import web
    from paidsub.storage import get_promo, get_promo_by_id, toggle_promo
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    code = (request.match_info.get("code") or "").upper()
    row = await get_promo(code)
    if not row:
        return web.json_response({"error": "no_promo"}, status=404)
    await toggle_promo(row[0])
    await _admin._audit(actor, "promo_toggle", f"code {code}")
    return web.json_response({"ok": True,
                              "promo": _promo_row(await get_promo_by_id(row[0]))})


async def promo_patch(request):
    from aiohttp import web
    from paidsub.storage import get_promo, get_promo_by_id, promo_set
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    code = (request.match_info.get("code") or "").upper()
    row = await get_promo(code)
    if not row:
        return web.json_response({"error": "no_promo"}, status=404)
    body = await _body(request)
    allowed = {"expires_at", "max_uses", "first_only", "note"}
    changed = []
    for field, value in body.items():
        if field not in allowed:
            return web.json_response({"error": "bad_field", "field": field},
                                     status=400)
        if field == "expires_at":
            if value == "":
                value = None
            if not _valid_date(value):
                return web.json_response({"error": "bad_expires_at"}, status=400)
        elif field == "max_uses":
            if not _is_int(value) or value < 0:
                return web.json_response({"error": "bad_value"}, status=400)
        elif field == "first_only":
            if not isinstance(value, bool):
                return web.json_response({"error": "bad_value"}, status=400)
            value = 1 if value else 0
        elif field == "note":
            if value is not None and not isinstance(value, str):
                return web.json_response({"error": "bad_value"}, status=400)
        await promo_set(row[0], field, value)
        changed.append(field)
    if not changed:
        return web.json_response({"error": "no_fields"}, status=400)
    await _admin._audit(actor, "promo_update",
                        f"code {code}: {', '.join(changed)}")
    return web.json_response({"ok": True,
                              "promo": _promo_row(await get_promo_by_id(row[0]))})


async def promo_delete(request):
    from aiohttp import web
    from paidsub.storage import delete_promo, get_promo
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    code = (request.match_info.get("code") or "").upper()
    row = await get_promo(code)
    if not row:
        return web.json_response({"error": "no_promo"}, status=404)
    body = await _body(request)
    token = body.get("confirm_token") or ""
    if not token:
        summary = f"Удалить промокод {code}?"
        token = _admin.issue_confirm(actor, "promo_delete",
                                     {"code": code}, summary)
        return _admin.confirm_needed_response(token, summary)
    payload = _admin.take_confirm(actor, token, "promo_delete")
    if not payload or payload.get("code") != code:
        return web.json_response({"error": "bad_confirm"}, status=400)
    await delete_promo(row[0])
    await _admin._audit(actor, "promo_delete", f"code {code}")
    return web.json_response({"ok": True})


async def promo_batch(request):
    from aiohttp import web
    from paidsub.storage import create_promo, unique_promo_code
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    count = body.get("count")
    if not _is_int(count) or not 1 <= count <= 50:
        return web.json_response({"error": "count must be 1..50"}, status=400)
    kind, value, rerr = _parse_reward(body)
    if rerr:
        return web.json_response({"error": rerr}, status=400)
    expires = (datetime.now() + timedelta(days=14)).strftime("%d.%m.%Y")
    made = []
    for _ in range(count):
        code = await unique_promo_code("AKC")
        ok = await create_promo(
            code, value if kind == "percent" else 0, expires,
            max_uses=1, kind=kind, days=value if kind == "days" else 0,
            source="batch", note=f"Партия {expires}")
        if ok:
            made.append(code)
    await _admin._audit(actor, "promo_batch",
                        f"{len(made)} codes {kind} {value}")
    return web.json_response({"ok": True, "codes": made, "count": len(made),
                              "expires_at": expires})


async def promo_find(request):
    from aiohttp import web
    from paidsub.storage import find_promos
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    q = request.query.get("q") or ""
    if not q.strip():
        return web.json_response({"error": "empty_query"}, status=400)
    rows = await find_promos(q.strip(), 20)
    return web.json_response({"promos": [_promo_list_row(r) for r in rows],
                              "q": q.strip()})


# ── Выдача промокодов ────────────────────────────────────────────────────────

# Паритет с ТГ-админкой (features/promos.py handle_promo_give_* и
# handle_promo_seg_*): личный код человеку и раздача кодов сегменту.
# Награда — те же пресеты PRESETS и те же границы, что _value_from_text
# (percent 1–100, days 1–365); код живёт VALID_DAYS дней, одно применение,
# привязан к владельцу; отправка — тот же give_to_user, пропуск админа
# и ЧС — тот же _skip_ids, пауза между отправками — SEND_PAUSE.


async def promo_give_meta(request):
    """Пресеты награды и сегменты со счётчиками — для экрана выдачи."""
    from aiohttp import web
    from core.database import get_users_by_segment
    from features.promos import PRESETS, SEGMENTS, VALID_DAYS, _skip_ids
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    segments = []
    for key, label in SEGMENTS.items():
        ids = await get_users_by_segment(key)
        skipped = await _skip_ids(ids)
        segments.append({"key": key, "label": label,
                         "recipients": len(ids) - len(skipped),
                         "skipped": len(skipped)})
    return web.json_response({
        "presets": [{"kind": k, "value": v} for k, v in PRESETS],
        "valid_days": VALID_DAYS, "segments": segments})


async def _resolve_give_target(raw):
    """target из тела → (tg_id, user_row|None, error). TG ID числом —
    как в ТГ: человека может не быть в базе, код всё равно выдаётся
    (доставка покажет delivered=False); @username/имя — только точное
    совпадение, иначе user_not_found."""
    from core.database import get_user_info, search_users
    if _is_int(raw):
        return raw, await get_user_info(raw), None
    if isinstance(raw, str):
        text = raw.strip().lstrip("@")
        if text.isdigit():
            tg_id = int(text)
            return tg_id, await get_user_info(tg_id), None
        if not text:
            return None, None, "empty_target"
        rows = await search_users(text, 12)
        needle = text.lower()
        for row in rows:
            if (row[2] or "").lower() == needle:
                return row[0], (row[0], row[1], row[2]), None
        return None, None, "user_not_found"
    return None, None, "bad_target"


async def promo_give(request):
    """Выдать личный промокод человеку — двухшаговое подтверждение."""
    from aiohttp import web
    from features.promos import VALID_DAYS, give_to_user, reward_label, reward_text
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    kind, value, rerr = _parse_reward(body)
    if rerr:
        return web.json_response({"error": rerr}, status=400)
    tg_id, user, terr = await _resolve_give_target(body.get("target"))
    if terr:
        status = 404 if terr == "user_not_found" else 400
        return web.json_response({"error": terr}, status=status)
    token = body.get("confirm_token")
    if not token:
        from core.database import format_client
        from paidsub.storage import get_paid_sub_by_tg_id
        who = format_client(user[1] if user else None,
                            user[2] if user else None, tg_id, html=False)
        sub = await get_paid_sub_by_tg_id(tg_id)
        if sub:
            status = {"active": "активна", "expired": "истекла"}.get(sub[11], sub[11])
            sub_line = f"Подписка: {status}, до {sub[6]}"
        else:
            sub_line = "Подписки нет — подарочные дни начислить будет некуда"
        summary = (f"Выдать промокод {who}?\nНаграда: {reward_text(kind, value)}\n"
                   f"{sub_line}\nКод действует {VALID_DAYS} дней, одно применение, "
                   "только у этого человека. Бот сразу отправит ему код сообщением.")
        payload = {"tg_id": tg_id, "kind": kind, "value": value}
        return _admin.confirm_needed_response(
            _admin.issue_confirm(actor, "promo_give", payload, summary), summary)
    payload = _admin.take_confirm(actor, token, "promo_give")
    if not payload:
        return web.json_response({"error": "bad_confirm"}, status=400)
    bot = _admin.get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    res = await give_to_user(bot, payload["tg_id"], payload["kind"], payload["value"])
    if not res.get("ok"):
        return web.json_response({"error": "give_failed",
                                  "details": str(res.get("error") or "")}, status=502)
    try:
        from core.database import format_client, get_user_info
        from core.log_channel import send_log
        u = await get_user_info(payload["tg_id"])
        who = format_client(u[1] if u else None, u[2] if u else None,
                            payload["tg_id"])
        await send_log(bot, f"🎁 Выдан промокод {res['code']} "
                            f"({reward_label(payload['kind'], payload['value'])}) · {who}")
    except Exception as ex:
        logging.error("админка: promo_give send_log: %s", ex)
    await _admin._audit(actor, "promo_give",
                        f"code {res['code']} → {payload['tg_id']} "
                        f"{reward_label(payload['kind'], payload['value'])}, "
                        f"delivered {res['delivered']}")
    return web.json_response({"ok": True, "code": res["code"],
                              "delivered": res["delivered"],
                              "tg_id": payload["tg_id"],
                              "kind": payload["kind"], "value": payload["value"]})


async def promo_segment(request):
    """Раздать личные промокоды сегменту — двухшаговое подтверждение."""
    from aiohttp import web
    from features.promos import (
        SEGMENTS, SEND_PAUSE, VALID_DAYS, _skip_ids, give_to_user,
        reward_label, reward_text,
    )
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    segment = body.get("segment") or "all"
    if segment not in SEGMENTS:
        return web.json_response({"error": "bad_segment"}, status=400)
    kind, value, rerr = _parse_reward(body)
    if rerr:
        return web.json_response({"error": rerr}, status=400)
    token = body.get("confirm_token")
    if not token:
        from core.database import get_users_by_segment
        ids = await get_users_by_segment(segment)
        skipped = await _skip_ids(ids)
        summary = (f"Раздать промокоды: {SEGMENTS[segment]}?\n"
                   f"Награда: {reward_text(kind, value)}\n"
                   f"Получат код: {len(ids) - len(skipped)}"
                   + (f"\nПропустим (бан, ЧС): {len(skipped)}" if skipped else "")
                   + f"\nКоды действуют {VALID_DAYS} дней, каждый на одно применение.")
        payload = {"segment": segment, "kind": kind, "value": value}
        return _admin.confirm_needed_response(
            _admin.issue_confirm(actor, "promo_seg", payload, summary), summary)
    payload = _admin.take_confirm(actor, token, "promo_seg")
    if not payload:
        return web.json_response({"error": "bad_confirm"}, status=400)
    bot = _admin.get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    from core.database import get_users_by_segment
    ids = await get_users_by_segment(payload["segment"])
    skip = await _skip_ids(ids)
    targets = [i for i in ids if i not in skip]
    sent = failed = 0
    for tg_id in targets:
        res = await give_to_user(bot, tg_id, payload["kind"], payload["value"],
                                 source="segment",
                                 note=f"Раздача: {SEGMENTS[payload['segment']]}")
        if res.get("ok") and res.get("delivered"):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(SEND_PAUSE)
    try:
        from core.log_channel import send_log
        await send_log(bot, f"📤 Раздача промокодов ({SEGMENTS[payload['segment']]}, "
                            f"{reward_label(payload['kind'], payload['value'])}): "
                            f"доставлено {sent}, не дошло {failed}")
    except Exception as ex:
        logging.error("админка: promo_seg send_log: %s", ex)
    await _admin._audit(actor, "promo_seg",
                        f"segment {payload['segment']}: sent {sent}, "
                        f"failed {failed}, skipped {len(skip)}")
    return web.json_response({"ok": True, "segment": payload["segment"],
                              "sent": sent, "failed": failed,
                              "skipped": len(skip)})


async def promo_income(request):
    """Что принесли промокоды — паритет с ТГ (features/promos.py
    handle_promo_income + шапка handle_promo_menu).

    Та же сводка раздела (promo_stats), плюс по каждому коду: награда,
    применений, оплат и сумма (promo_income_all, топ-30 по сумме)
    и число мёртвых кодов без применений для чистки.
    """
    from aiohttp import web
    from features.promos import reward_label
    from paidsub.storage import promo_dead_ids, promo_income_all, promo_stats
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    stats = await promo_stats()
    rows = await promo_income_all()
    items = []
    total_pays = total_sum = 0
    for code, kind, percent, days, uses, pays, amount in rows:
        total_pays += pays or 0
        total_sum += amount or 0
        items.append({"code": code,
                      "reward": reward_label(kind or "percent",
                                             days if kind == "days" else percent),
                      "uses": uses or 0, "pays": pays or 0,
                      "amount": amount or 0})
    return web.json_response({
        "stats": stats, "items": items,
        "total_pays": total_pays, "total_sum": total_sum,
        "dead_count": len(await promo_dead_ids()),
    })


async def promo_clean(request):
    """Убрать мёртвые промокоды — паритет с ТГ (handle_promo_clean/_do).

    Мёртвые — выключенные и просроченные коды, которыми ни разу
    не воспользовались (promo_dead_ids); коды с применениями остаются.
    Двухшаговое подтверждение, как у удаления промокода.
    """
    from aiohttp import web
    from paidsub.storage import promo_clean_dead, promo_dead_ids
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    token = body.get("confirm_token") or ""
    if not token:
        ids = await promo_dead_ids()
        if not ids:
            return web.json_response({"error": "dead_empty"}, status=409)
        summary = (f"Убрать мёртвые коды?\n\nПод нож пойдут {len(ids)} кодов: "
                   "выключенные и просроченные, которыми ни разу "
                   "не воспользовались.\n\nКоды с применениями останутся — "
                   "по ним считается статистика.")
        payload = {"dead": len(ids)}
        return _admin.confirm_needed_response(
            _admin.issue_confirm(actor, "promo_clean", payload, summary),
            summary)
    payload = _admin.take_confirm(actor, token, "promo_clean")
    if not payload:
        return web.json_response({"error": "bad_confirm"}, status=400)
    gone = await promo_clean_dead()
    await _admin._audit(actor, "promo_clean",
                        f"removed {gone} (requested {payload.get('dead')})")
    return web.json_response({"ok": True, "removed": gone})


# ── Серверы (расходы) ────────────────────────────────────────────────────────

async def servers_list(request):
    from aiohttp import web
    from core.database import servers_with_status
    from handlers.finance import current_period
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    period = request.query.get("period") or current_period()
    if not _valid_period(period):
        return web.json_response({"error": "bad_period"}, status=400)
    return web.json_response({"period": period,
                              "servers": await servers_with_status(period)})


async def server_create(request):
    from aiohttp import web
    from core.database import add_server, get_server
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    name = body.get("name")
    price = body.get("price_rub")
    day = body.get("pay_day")
    if (not isinstance(name, str) or not name.strip() or len(name) > 64
            or not _is_int(price) or price <= 0
            or not _is_int(day) or not 1 <= day <= 31):
        return web.json_response({"error": "bad_server"}, status=400)
    sid = await add_server(name.strip(), price, day)
    await _admin._audit(actor, "server_create",
                        f"server #{sid} {name.strip()}")
    return web.json_response({"ok": True, "server": _server_row(await get_server(sid))})


async def server_detail(request):
    from aiohttp import web
    from core.database import get_server, get_server_payment
    from handlers.finance import current_period
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    sid = _int_id(request.match_info.get("sid"))
    if sid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    row = await get_server(sid)
    if not row:
        return web.json_response({"error": "no_server"}, status=404)
    period = request.query.get("period") or current_period()
    if not _valid_period(period):
        return web.json_response({"error": "bad_period"}, status=400)
    out = _server_row(row)
    out["period"] = period
    out["status"] = await get_server_payment(sid, period)
    return web.json_response({"server": out})


async def server_patch(request):
    from aiohttp import web
    from core.database import get_server, update_server_field
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    sid = _int_id(request.match_info.get("sid"))
    if sid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    if not await get_server(sid):
        return web.json_response({"error": "no_server"}, status=404)
    body = await _body(request)
    allowed = {"name", "price_rub", "pay_day"}
    changed = []
    for field, value in body.items():
        if field not in allowed:
            return web.json_response({"error": "bad_field", "field": field},
                                     status=400)
        if field == "name":
            if not isinstance(value, str) or not value.strip() or len(value) > 64:
                return web.json_response({"error": "bad_value"}, status=400)
            value = value.strip()
        elif field == "price_rub":
            if not _is_int(value) or value <= 0:
                return web.json_response({"error": "bad_value"}, status=400)
        elif field == "pay_day":
            if not _is_int(value) or not 1 <= value <= 31:
                return web.json_response({"error": "bad_value"}, status=400)
        await update_server_field(sid, field, value)
        changed.append(field)
    if not changed:
        return web.json_response({"error": "no_fields"}, status=400)
    await _admin._audit(actor, "server_update",
                        f"server #{sid}: {', '.join(changed)}")
    row = await get_server(sid)
    return web.json_response({"ok": True, "server": _server_row(row)})


async def server_delete(request):
    from aiohttp import web
    from core.database import delete_server, get_server
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    sid = _int_id(request.match_info.get("sid"))
    if sid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    if not await get_server(sid):
        return web.json_response({"error": "no_server"}, status=404)
    await delete_server(sid)
    await _admin._audit(actor, "server_delete", f"server #{sid}")
    return web.json_response({"ok": True})


async def server_mark(request):
    from aiohttp import web
    from core.database import get_server, set_server_payment
    from handlers.finance import current_period
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    sid = _int_id(request.match_info.get("sid"))
    if sid is None:
        return web.json_response({"error": "bad_id"}, status=400)
    if not await get_server(sid):
        return web.json_response({"error": "no_server"}, status=404)
    body = await _body(request)
    status = body.get("status")
    if status not in ("paid", "unpaid"):
        return web.json_response({"error": "bad_status"}, status=400)
    period = body.get("period") or current_period()
    if not _valid_period(period):
        return web.json_response({"error": "bad_period"}, status=400)
    marked_by = int(actor["tg_id"]) if actor["kind"] == "mark" else 0
    await set_server_payment(sid, period, status, marked_by=marked_by)
    await _admin._audit(actor, "server_mark",
                        f"server #{sid} {period} {status}")
    return web.json_response({"ok": True, "server_id": sid,
                              "period": period, "status": status})


# ── Рассылка ─────────────────────────────────────────────────────────────────

# Лимит Bot API на фото — 10 МБ. Больше Telegram всё равно не примет.
MAX_BROADCAST_PHOTO_BYTES = 10 * 1024 * 1024


async def _upload_photo(request, audit_action):
    """Загрузка фото: multipart/form-data, поле "photo".

    Фото заливается ботом самому себе (ADMIN_ID) — Telegram отдаёт
    file_id, который UI потом передаёт в preview/send как body.photo.
    Сам файл нигде не хранится: после получения file_id байты
    выбрасываются. audit_action — имя действия для журнала
    (broadcast_photo_upload / channel_photo_upload)."""
    from aiohttp import web
    from config import ADMIN_ID
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    try:
        reader = await request.multipart()
    except Exception:
        return web.json_response({"error": "bad_multipart"}, status=400)
    field = None
    try:
        async for part in reader:
            if part.name == "photo":
                field = part
                break
    except Exception:
        return web.json_response({"error": "bad_multipart"}, status=400)
    if field is None:
        return web.json_response({"error": "no_photo"}, status=400)
    ctype = (field.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if not ctype.startswith("image/"):
        return web.json_response({"error": "bad_photo_type"}, status=400)
    # Читаем чанками: read_chunk() не упирается в client_max_size
    # сервера (1 МБ по умолчанию), лимит 10 МБ проверяем сами.
    data = bytearray()
    try:
        while True:
            chunk = await field.read_chunk(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_BROADCAST_PHOTO_BYTES:
                return web.json_response({"error": "photo_too_large"},
                                         status=400)
    except Exception:
        return web.json_response({"error": "bad_multipart"}, status=400)
    if not data:
        return web.json_response({"error": "no_photo"}, status=400)
    bot = _admin.get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    try:
        msg = await bot.send_photo(chat_id=ADMIN_ID, photo=bytes(data))
    except Exception as ex:
        return web.json_response({"error": "telegram_error",
                                  "details": str(ex)[:200]}, status=502)
    sizes = getattr(msg, "photo", None) or []
    largest = sizes[-1] if sizes else None
    file_id = getattr(largest, "file_id", None) if largest else None
    if not file_id:
        return web.json_response({"error": "telegram_error",
                                  "details": "no photo in reply"}, status=502)
    # В журнал — только размер и первые 8 символов file_id:
    # полный file_id в логах не нужен, а по префиксу фото находится.
    await _admin._audit(actor, audit_action,
                        f"photo {len(data)} bytes, file_id {file_id[:8]}…")
    return web.json_response({"ok": True, "photo_file_id": file_id,
                              "width": getattr(largest, "width", None),
                              "height": getattr(largest, "height", None)})


async def broadcast_upload(request):
    """Загрузка фото для рассылки — см. _upload_photo."""
    return await _upload_photo(request, "broadcast_photo_upload")


async def broadcast_preview(request):
    """Предпросмотр: отрендеренный текст + число получателей.
    Ничего не отправляет."""
    from aiohttp import web
    from core.database import get_users_by_segment
    from handlers.broadcast import SEGMENTS
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    body = await _body(request)
    data, berr = _broadcast_payload(body)
    if berr is not None:
        return berr
    recipients = await get_users_by_segment(data["segment"])
    return web.json_response({
        "text": data["text"], "segment": data["segment"],
        "segment_label": SEGMENTS[data["segment"]],
        "recipients": len(recipients),
        "buttons": data["buttons"],
        "photo": bool(data["photo"]),
        "photo_file_id": data["photo"],
        "split_photo": bool(data["photo"]) and len(data["text"]) > 1024,
    })


async def broadcast_send(request):
    """Отправка рассылки: двухшаговое подтверждение, потом
    do_broadcast() тем же ботом, что и у ТГ-админки."""
    from aiohttp import web
    from handlers.broadcast import SEGMENTS, build_markup, do_broadcast
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    token = body.get("confirm_token") or ""
    if not token:
        data, berr = _broadcast_payload(body)
        if berr is not None:
            return berr
        from core.database import get_users_by_segment
        count = len(await get_users_by_segment(data["segment"]))
        summary = (f"Рассылка «{SEGMENTS[data['segment']]}»: "
                   f"{count} получателей")
        token = _admin.issue_confirm(actor, "broadcast_send", data, summary)
        return _admin.confirm_needed_response(token, summary)
    payload = _admin.take_confirm(actor, token, "broadcast_send")
    if not payload:
        return web.json_response({"error": "bad_confirm"}, status=400)
    bot = _admin.get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    ok, fail = await do_broadcast(
        bot, payload["text"], payload["segment"],
        build_markup(payload.get("buttons")), payload.get("photo"))
    await _admin._audit(actor, "broadcast_send",
                        f"segment {payload['segment']}: sent {ok}, fail {fail}")
    return web.json_response({"ok": True, "segment": payload["segment"],
                              "sent": ok, "failed": fail})


# ── Пост в ТГ-канал ──────────────────────────────────────────────────────────

# Паритет с ТГ-админкой (handlers/channel_post.py): тот же состав поста
# (текст + подпись channel_signature, 1 фото подписью / альбом,
# кнопки из меню /start диплинками ch_*) и та же отправка через
# handlers.channel_post._deliver. Отличия веба: черновик живёт во фронте
# (а не в user_data), а живой предпросмотр уходит в Telegram только
# Марку — у Muse-аккаунта нет tg_id, ему отдаётся сухой рендер.


def _channel_post_payload(body: dict):
    """Проверяет тело поста в канал. Возвращает (data, error_response)."""
    from aiohttp import web
    from handlers.channel_post import MENU_BUTTONS
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return None, web.json_response({"error": "empty_text"}, status=400)
    if len(text) > 4096:
        return None, web.json_response({"error": "text_too_long"}, status=400)
    photos = body.get("photos") or []
    if not isinstance(photos, list) or not all(
            isinstance(p, str) and p for p in photos):
        return None, web.json_response({"error": "bad_photos"}, status=400)
    if len(photos) > 10:
        return None, web.json_response({"error": "too_many_photos"},
                                       status=400)
    buttons = body.get("buttons") or []
    if not isinstance(buttons, list) or not all(
            isinstance(b, str) and b in MENU_BUTTONS for b in buttons):
        return None, web.json_response({"error": "bad_buttons"}, status=400)
    use_sign = body.get("use_sign", True)
    if not isinstance(use_sign, bool):
        return None, web.json_response({"error": "bad_use_sign"}, status=400)
    return {"text": text, "photos": list(photos),
            "buttons": list(dict.fromkeys(buttons)),
            "use_sign": use_sign}, None


def _channel_ctx(data: dict):
    """user_data-контекст для handlers.channel_post._deliver:
    та же форма, что у ТГ-флоу (ключи chpost_*)."""
    return SimpleNamespace(user_data={
        "chpost_text": data["text"],
        "chpost_photos": list(data["photos"]),
        "chpost_sel": list(data["buttons"]),
        "chpost_use_sign": data["use_sign"],
    })


async def channel_get(request):
    """Канал, подпись и кнопки меню — для экрана поста."""
    from aiohttp import web
    from config import load_config
    from handlers.channel_post import (
        MENU_BUTTONS, MENU_LAYOUT, channel_target, get_signature,
    )
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    cfg = load_config()
    sign = get_signature()
    return web.json_response({
        "channel": channel_target(cfg),
        "channel_url": cfg.get("channel_url") or "",
        "signature": sign,
        "signature_plain": re.sub(r"<[^>]+>", "", sign).strip(),
        "buttons": [{"key": k, "label": MENU_BUTTONS[k]}
                    for row in MENU_LAYOUT for k in row],
        "layout": MENU_LAYOUT,
    })


async def channel_signature_set(request):
    """Задать или убрать подпись к постам (пустая строка — убрать).
    Тот же ключ channel_signature, что и в ТГ-админке."""
    from aiohttp import web
    from config import atomic_update
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    sign = body.get("signature")
    if sign is None:
        sign = ""
    if not isinstance(sign, str):
        return web.json_response({"error": "bad_signature"}, status=400)
    if len(sign) > 4096:
        return web.json_response({"error": "signature_too_long"}, status=400)
    if sign.strip():
        atomic_update(lambda cfg: cfg.__setitem__("channel_signature", sign))
    else:
        atomic_update(lambda cfg: cfg.pop("channel_signature", None))
    await _admin._audit(actor, "channel_signature",
                        "set" if sign.strip() else "clear")
    return web.json_response({"ok": True,
                              "signature": sign if sign.strip() else ""})


async def channel_post_upload(request):
    """Загрузка фото для поста в канал — см. _upload_photo.
    Фронт зовёт по разу на файл и собирает file_id в черновик."""
    return await _upload_photo(request, "channel_photo_upload")


async def channel_post_preview(request):
    """Предпросмотр: сухой рендер (финальный текст с подписью,
    кнопки, предупреждения про альбом и длинный текст) и, если
    актёр — Mark, живая доставка того же поста ему в Telegram
    тем же _deliver, что уйдёт в канал. Ошибка живой доставки
    не роняет ответ: сухой рендер всё равно возвращается,
    а preview_error объясняет, что не так (чаще всего — битая
    HTML-разметка)."""
    from aiohttp import web
    from handlers.broadcast import CAPTION_LIMIT
    from handlers.channel_post import _final_text, get_signature
    actor, err = await _actor_or_401(request)
    if err is not None:
        return err
    body = await _body(request)
    data, berr = _channel_post_payload(body)
    if berr is not None:
        return berr
    ctx = _channel_ctx(data)
    final = _final_text(ctx)
    if len(final) > 4096:
        return web.json_response({"error": "text_too_long"}, status=400)
    sign = get_signature()
    out = {"text": final, "photos": len(data["photos"]),
           "buttons": data["buttons"],
           "album": len(data["photos"]) > 1,
           "caption_split": bool(data["photos"]) and len(final) > CAPTION_LIMIT,
           "signature_on": bool(sign) and data["use_sign"],
           "preview_sent": False, "preview_error": None}
    if actor["kind"] == "mark" and actor.get("tg_id"):
        bot = _admin.get_bot()
        if bot is None:
            out["preview_error"] = "no_bot"
        else:
            try:
                from handlers.channel_post import _deliver
                await _deliver(bot, actor["tg_id"], ctx)
                out["preview_sent"] = True
            except Exception as ex:
                out["preview_error"] = str(ex)[:200]
    return web.json_response(out)


async def channel_post_publish(request):
    """Публикация в канал: двухшаговое подтверждение, потом
    _deliver тем же ботом, что и у ТГ-админки, и запись в лог-канал.
    При ошибке Telegram черновик не теряется: форма остаётся во
    фронте, публикацию можно повторить (новый confirm_token)."""
    from aiohttp import web
    from handlers.channel_post import _final_text, channel_target
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    token = body.get("confirm_token") or ""
    if not token:
        data, berr = _channel_post_payload(body)
        if berr is not None:
            return berr
        final = _final_text(_channel_ctx(data))
        if len(final) > 4096:
            return web.json_response({"error": "text_too_long"}, status=400)
        target = channel_target()
        if not target:
            return web.json_response({"error": "no_channel"}, status=409)
        summary = (f"Пост в канал {target}: текст {len(final)} симв., "
                   f"фото: {len(data['photos'])}, "
                   f"кнопок: {len(data['buttons'])}")
        if len(data["photos"]) > 1 and data["buttons"]:
            summary += " (альбом — кнопки не попадут в канал)"
        token = _admin.issue_confirm(actor, "channel_post_send", data,
                                     summary)
        return _admin.confirm_needed_response(token, summary)
    payload = _admin.take_confirm(actor, token, "channel_post_send")
    if not payload:
        return web.json_response({"error": "bad_confirm"}, status=400)
    bot = _admin.get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    target = channel_target()
    if not target:
        return web.json_response({"error": "no_channel"}, status=409)
    try:
        from handlers.channel_post import _deliver
        await _deliver(bot, target, _channel_ctx(payload))
    except Exception as ex:
        return web.json_response({"error": "telegram_error",
                                  "details": str(ex)[:200]}, status=502)
    from core.log_channel import send_log
    await send_log(bot, f"📣 Опубликован пост в канал {target}")
    await _admin._audit(actor, "channel_post_send",
                        f"channel {target}: photos {len(payload['photos'])}, "
                        f"buttons {len(payload['buttons'])}")
    return web.json_response({"ok": True, "channel": str(target)})


# ── Напоминания и возврат (удержание) ─────────────────────────────────────────

# Те же ключи и та же семантика, что в ТГ-админке: напоминания —
# handlers/admin.py handle_remind_settings, возврат — features/winback.py.
_REMIND_KEYS = ("remind_enabled", "remind_first", "remind_second",
                "remind_third", "remind_trials", "remind_quiet_from",
                "remind_quiet_to")
_WINBACK_KEYS = ("winback_enabled", "winback_days", "winback_percent",
                 "winback_days2", "winback_percent2", "winback_life_days",
                 "winback_paid_only")
_RETENTION_KEYS = _REMIND_KEYS + _WINBACK_KEYS
# Напоминание дальше года до конца подписки бессмысленно; ТГ такой
# границы не ставит, но и срок длиннее года туда никто не вводит.
_REMIND_MAX_SECONDS = 366 * 86400


def _parse_remind_seconds(value):
    """Срок напоминания: int секунд, строка «3 дня»/«12 часов» (тот же
    parse_duration, что в ТГ) или 0/«выкл» — выключено. Возвращает
    секунды или None, если не разобрать."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _REMIND_MAX_SECONDS else None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("0", "выкл", "нет", "off", ""):
            return 0
        from paidsub.time_parser import parse_duration
        seconds = parse_duration(text)
        if seconds is None or not 0 <= seconds <= _REMIND_MAX_SECONDS:
            return None
        return seconds
    return None


def _parse_quiet_hour(value):
    """Тихий час: int 0–23, «HH:MM» (как раньше принимал веб) или
    пустое/None — выключено. Возвращает (ok, hour|None)."""
    if value is None or value == "":
        return True, None
    if isinstance(value, bool):
        return False, None
    if isinstance(value, int):
        return (0 <= value <= 23), (value if 0 <= value <= 23 else None)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() and 0 <= int(text) <= 23:
            return True, int(text)
        from handlers.morning import parse_time
        parsed = parse_time(text)
        if parsed is not None:
            return True, parsed[0]
    return False, None


def _quiet_hour_stored(value):
    """Час из config как есть: int от ТГ, «HH:MM» от старого веба,
    мусор — None (экран его покажет как «выключено»)."""
    ok, hour = _parse_quiet_hour(value)
    return hour if ok else None


def _retention_payload(actor):
    """Текущие настройки + статистика — то же, что показывают экраны ТГ."""
    from config import load_config
    from core.database import remind_stats, winback_stats
    from features.winback import settings as _winback_settings
    cfg = load_config()
    remind = {
        "enabled": bool(cfg.get("remind_enabled", True)),
        "first": int(cfg.get("remind_first", 3 * 86400) or 0),
        "second": int(cfg.get("remind_second", 86400) or 0),
        "third": int(cfg.get("remind_third", 0) or 0),
        "trials": bool(cfg.get("remind_trials", True)),
        "quiet_from": _quiet_hour_stored(cfg.get("remind_quiet_from")),
        "quiet_to": _quiet_hour_stored(cfg.get("remind_quiet_to")),
    }
    return {
        "remind": remind,
        "winback": _winback_settings(),
        "is_mark": actor["kind"] == "mark",
    }


async def retention_get(request):
    """Настройки напоминаний и возврата + итоги за 30 дней."""
    from aiohttp import web
    from core.database import remind_stats, winback_stats
    actor, err = await _actor_or_401(request)
    if err is not None:
        return err
    out = _retention_payload(actor)
    out["remind_stats"] = await remind_stats(30)
    out["winback_stats"] = await winback_stats()
    return web.json_response(out)


async def retention_save(request):
    """Сохранить настройки напоминаний и/или возврата.

    Границы — как ввод в ТГ (handlers/messages.py): дни winback ≥ 1,
    скидки 1–100, вторая волна 0 — выключена, срок промокода ≥ 1;
    напоминания — секунды или «3 дня»/«12 часов», 0 — выключено;
    тихие часы — оба часа или оба выключены. Частичное сохранение:
    карточка шлёт только свои ключи."""
    from aiohttp import web
    from config import atomic_update, load_config
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    if not body:
        return web.json_response({"error": "no_fields"}, status=400)
    clean, errors = {}, []
    for key, value in body.items():
        if key not in _RETENTION_KEYS:
            errors.append(f"unknown key: {key}")
            continue
        if key in ("remind_enabled", "remind_trials", "winback_enabled",
                   "winback_paid_only"):
            if not isinstance(value, bool):
                errors.append(f"{key} must be bool")
            else:
                clean[key] = value
        elif key in ("remind_first", "remind_second", "remind_third"):
            seconds = _parse_remind_seconds(value)
            if seconds is None:
                errors.append(f"{key} must be seconds or a duration "
                              f"like '3 дня' (0 — off)")
            else:
                clean[key] = seconds
        elif key in ("remind_quiet_from", "remind_quiet_to"):
            ok, hour = _parse_quiet_hour(value)
            if not ok:
                errors.append(f"{key} must be an hour 0-23 or empty")
            else:
                clean[key] = hour
        elif key in ("winback_days", "winback_life_days"):
            if not _is_int(value) or value < 1:
                errors.append(f"{key} must be an int >= 1")
            else:
                clean[key] = value
        elif key == "winback_days2":
            if not _is_int(value) or value < 0:
                errors.append("winback_days2 must be an int >= 0 "
                              "(0 — second wave off)")
            else:
                clean[key] = value
        elif key in ("winback_percent", "winback_percent2"):
            if not _is_int(value) or not 1 <= value <= 100:
                errors.append(f"{key} must be an int 1-100")
            else:
                clean[key] = value
    if errors:
        return web.json_response({"error": "bad_value", "details": errors},
                                 status=400)
    # Тихие часы — только парой: один час без второго бот не понимает
    # (in_quiet_hours требует оба). Считаем итоговую пару: новые
    # значения поверх сохранённых.
    cfg = load_config()
    q_from = clean.get("remind_quiet_from",
                       _quiet_hour_stored(cfg.get("remind_quiet_from")))
    q_to = clean.get("remind_quiet_to",
                     _quiet_hour_stored(cfg.get("remind_quiet_to")))
    if (q_from is None) != (q_to is None):
        return web.json_response(
            {"error": "bad_value",
             "details": ["quiet hours need both from and to, or neither"]},
            status=400)
    if clean:
        def _apply(c):
            c.update(clean)
        atomic_update(_apply)
    await _admin._audit(actor, "retention_update",
                        "keys: " + ", ".join(sorted(clean)))
    from core.database import remind_stats, winback_stats
    out = _retention_payload(actor)
    out["remind_stats"] = await remind_stats(30)
    out["winback_stats"] = await winback_stats()
    return web.json_response({"ok": True, **out})


async def retention_remind_test(request):
    """Пример напоминания Марку в Telegram — тот же текст и та же
    кнопка, что в ТГ (handle_remind_test). Только Mark: у Muse нет
    tg_id, а письмо адресовано конкретному человеку."""
    from aiohttp import web
    from config import load_config
    from paidsub.time_parser import fmt_duration_precise
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    if actor["kind"] != "mark" or not actor.get("tg_id"):
        return web.json_response({"error": "mark_only"}, status=403)
    bot = _admin.get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    cfg = load_config()
    left = int(cfg.get("remind_first", 3 * 86400) or 86400)
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        await bot.send_message(
            chat_id=actor["tg_id"],
            text=("⏳ <b>Подписка скоро закончится</b>\n\n"
                  f"<blockquote>Осталось: <b>{fmt_duration_precise(left)}</b></blockquote>\n\n"
                  "<i>Продлите сейчас — оставшиеся дни не сгорят, а прибавятся.</i>\n\n"
                  "— — —\n<i>Это пример, так его увидит клиент.</i>"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Продлить подписку",
                                      callback_data="renew_sub")]]),
        )
    except Exception as ex:
        return web.json_response({"error": "telegram_error",
                                  "details": str(ex)[:200]}, status=502)
    await _admin._audit(actor, "remind_test", "")
    return web.json_response({"ok": True})


async def retention_winback_test(request):
    """Пример письма возврата Марку — та же _send_wave первой волны,
    что в ТГ (handle_winback_test): личный промокод BACK<tg_id> и
    текст письма. Только Mark. Волна в winback_sent НЕ отмечается —
    тест не подавляет настоящие письма клиентам."""
    from aiohttp import web
    from features.winback import _send_wave
    from features.winback import settings as _winback_settings
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    if actor["kind"] != "mark" or not actor.get("tg_id"):
        return web.json_response({"error": "mark_only"}, status=403)
    bot = _admin.get_bot()
    if bot is None:
        return web.json_response({"error": "no_bot"}, status=503)
    s = _winback_settings()
    try:
        code = await _send_wave(bot, actor["tg_id"], 1,
                                s["percent"], s["life_days"])
    except Exception as ex:
        return web.json_response({"error": "telegram_error",
                                  "details": str(ex)[:200]}, status=502)
    await _admin._audit(actor, "winback_test", f"code {code}")
    return web.json_response({"ok": True, "code": code})


# ── Platega ──────────────────────────────────────────────────────────────────

async def platega_get(request):
    """Баланс и проверка подключения. Секреты — никогда:
    только маска Merchant ID и флаги «задан / не задан»."""
    from aiohttp import web
    from config import load_config
    from handlers.payprovider import _mask
    import services.platega_api as pg
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    cfg = load_config()
    configured = pg.is_configured()
    out = {"configured": configured,
           "merchant": _mask(cfg.get("platega_merchant_id")),
           "merchant_set": bool(cfg.get("platega_merchant_id")),
           "secret_set": bool(cfg.get("platega_secret"))}
    if configured:
        out["test"] = await pg.test_connection()
        out["balance"] = await pg.get_balance()
    return web.json_response(out)


async def platega_patch(request):
    """Запись Merchant ID / API ключа (write-only). Значения
    принимаются и сохраняются, но никогда не возвращаются
    и не пишутся в журнал."""
    from aiohttp import web
    from config import atomic_update, load_config
    from handlers.payprovider import _mask
    actor, err = await _admin._require_mutation(request)
    if err is not None:
        return err
    body = await _body(request)
    merchant = body.get("platega_merchant_id")
    secret = body.get("platega_secret")
    if merchant is None and secret is None:
        return web.json_response({"error": "no_fields"}, status=400)
    if merchant is not None and (
            not isinstance(merchant, str) or not merchant.strip()
            or len(merchant) > 200 or len(merchant.strip()) < 8):
        return web.json_response({"error": "bad_merchant"}, status=400)
    if secret is not None and (
            not isinstance(secret, str) or not secret.strip()
            or len(secret) > 200):
        return web.json_response({"error": "bad_secret"}, status=400)
    changed = []
    if merchant is not None:
        changed.append("platega_merchant_id")
    if secret is not None:
        changed.append("platega_secret")

    def _apply(cfg):
        if merchant is not None:
            cfg["platega_merchant_id"] = merchant.strip()
        if secret is not None:
            cfg["platega_secret"] = secret.strip()

    atomic_update(_apply)
    await _admin._audit(actor, "platega_update",
                        "fields: " + ", ".join(changed))
    cfg = load_config()
    return web.json_response({"ok": True,
                              "merchant": _mask(cfg.get("platega_merchant_id")),
                              "merchant_set": bool(cfg.get("platega_merchant_id")),
                              "secret_set": bool(cfg.get("platega_secret"))})


async def platega_settings(request):
    """Справка «Настройки Platega» — паритет с ТГ handle_platega_settings:
    те же строки и URL, только чтение. Секреты — никогда: Merchant ID
    только маской, API ключ не возвращается вообще. База URL — адрес
    сайта из site_url(), фолбэк — литерал из ТГ."""
    from aiohttp import web
    from config import load_config
    from handlers.payprovider import _mask
    import web.site_deploy as site
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    cfg = load_config()
    base = site.site_url() or "https://vpn.drbl.tech"
    return web.json_response({
        "merchant": _mask(cfg.get("platega_merchant_id")),
        "methods": "СБП, карта, крипта — выбирает плательщик на форме",
        "success_url": base + "/pay/success/",
        "fail_url": base + "/pay/fail/",
        "back_url": base + "/pay/back/",
        "callback_url": base + "/api/webhooks/platega",
        "logo_url": base + "/logo.png",
        "cabinet_url": "https://app.platega.io/",
        "note": ("Эти настройки живут только в кабинете Platega — API их "
                 "не отдаёт, поэтому бот показывает, как должно быть "
                 "настроено. Меняется всё только в кабинете. Бот сам "
                 "подставляет адреса /pay/* в каждый счёт, но впиши "
                 "Callback URL в кабинете — без него оплаты подтверждаются "
                 "только опросом раз в минуту."),
    })


# ── Регистрация маршрутов ────────────────────────────────────────────────────

def register(app):
    """Добавляет маршруты фазы 2 в подприложение админки.
    Пути — относительные, без /api/admin: префикс даёт add_subapp()
    в web/webapi.py (как и маршруты фазы 1 в build_admin_app)."""
    app.router.add_get("/payments", payments_list)
    app.router.add_get("/payments/export", payments_export)
    app.router.add_get("/payments/{pid}", payment_detail)
    app.router.add_get("/payments/{pid}/platega", payment_platega_check)
    app.router.add_post("/payments/{pid}/refund", payment_refund)
    app.router.add_get("/finance", finance_hub)
    app.router.add_post("/reconcile/run", reconcile_run)
    app.router.add_post("/reconcile/fix", reconcile_fix)
    app.router.add_get("/tariffs", tariffs_list)
    app.router.add_post("/tariffs", tariff_create)
    app.router.add_get("/tariffs/{tid}", tariff_detail)
    app.router.add_patch("/tariffs/{tid}", tariff_patch)
    app.router.add_delete("/tariffs/{tid}", tariff_delete)
    # Статические пути промокодов — до динамического /promos/{code},
    # иначе "find"/"batch" воспримутся как код.
    app.router.add_get("/promos", promos_list)
    app.router.add_post("/promos", promo_create)
    app.router.add_get("/promos/find", promo_find)
    app.router.add_post("/promos/batch", promo_batch)
    app.router.add_get("/promos/give", promo_give_meta)
    app.router.add_post("/promos/give", promo_give)
    app.router.add_post("/promos/segment", promo_segment)
    app.router.add_get("/promos/income", promo_income)
    app.router.add_post("/promos/clean", promo_clean)
    app.router.add_get("/promos/{code}", promo_detail)
    app.router.add_post("/promos/{code}/toggle", promo_toggle)
    app.router.add_patch("/promos/{code}", promo_patch)
    app.router.add_delete("/promos/{code}", promo_delete)
    app.router.add_get("/servers", servers_list)
    app.router.add_post("/servers", server_create)
    app.router.add_get("/servers/{sid}", server_detail)
    app.router.add_patch("/servers/{sid}", server_patch)
    app.router.add_delete("/servers/{sid}", server_delete)
    app.router.add_post("/servers/{sid}/mark", server_mark)
    app.router.add_post("/broadcast/upload", broadcast_upload)
    app.router.add_post("/broadcast/preview", broadcast_preview)
    app.router.add_post("/broadcast/send", broadcast_send)
    app.router.add_get("/channel", channel_get)
    app.router.add_post("/channel/signature", channel_signature_set)
    app.router.add_post("/channel/post/upload", channel_post_upload)
    app.router.add_post("/channel/post/preview", channel_post_preview)
    app.router.add_post("/channel/post/publish", channel_post_publish)
    app.router.add_get("/retention", retention_get)
    app.router.add_post("/retention/save", retention_save)
    app.router.add_post("/retention/remind/test", retention_remind_test)
    app.router.add_post("/retention/winback/test", retention_winback_test)
    app.router.add_get("/platega", platega_get)
    app.router.add_get("/platega/settings", platega_settings)
    app.router.add_patch("/platega", platega_patch)
    logging.info("админка: маршруты фазы 2 (финансы, рассылка) зарегистрированы")
