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

async def payments_list(request):
    from aiohttp import web
    from core.database import list_payments
    _, err = await _actor_or_401(request)
    if err is not None:
        return err
    status = request.query.get("status") or "paid"
    if status not in ("paid", "pending", "failed", "refunds", "all"):
        return web.json_response({"error": "bad_status"}, status=400)
    try:
        page = int(request.query.get("page") or 1)
    except ValueError:
        return web.json_response({"error": "bad_page"}, status=400)
    page = max(1, page)
    rows, total_pages = await list_payments(page, status)
    return web.json_response({"payments": [_payment_list_row(r) for r in rows],
                              "page": page, "total_pages": total_pages,
                              "status": status})


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


# ── Регистрация маршрутов ────────────────────────────────────────────────────

def register(app):
    """Добавляет маршруты фазы 2 в подприложение админки.
    Пути — относительные, без /api/admin: префикс даёт add_subapp()
    в web/webapi.py (как и маршруты фазы 1 в build_admin_app)."""
    app.router.add_get("/payments", payments_list)
    app.router.add_get("/payments/{pid}", payment_detail)
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
    app.router.add_post("/broadcast/preview", broadcast_preview)
    app.router.add_post("/broadcast/send", broadcast_send)
    app.router.add_get("/platega", platega_get)
    app.router.add_patch("/platega", platega_patch)
    logging.info("админка: маршруты фазы 2 (финансы, рассылка) зарегистрированы")
