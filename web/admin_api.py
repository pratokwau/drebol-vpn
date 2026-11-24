"""Веб-админка Drebol VPN — фаза 1: вход, дашборд, безопасные настройки.

Тот же процесс, тот же config.json и тот же bot.db, что и у Telegram-бота:
веб — второй фронт-энд, а не вторая копия. Все действия пишут в те же
таблицы и вызывают те же функции, что и ТГ-админка.

Вход:
• Mark — через Telegram (Login Widget / Mini App initData), tg_id == ADMIN_ID.
• Muse — почта + пароль (таблица admin_accounts, scrypt). Капча Turnstile
  для этого входа ОТКЛЮЧЕНА — Mark явно согласился 2026-11-15; взамен
  блокировка 5 неверных попыток / 15 минут на пару (аккаунт, IP), хранится
  в базе, все входы пишутся в журнал. Вход в кабинет по паролю капчу
  требует как раньше — его не трогаем.

Сессия — только HttpOnly; Secure (на https); SameSite=Strict кука
`drebol_admin`. Токен никогда не принимается из ?token= и из
Authorization — только из куки. Каждая меняющая операция требует
CSRF-токен (double-submit кука + заголовок X-CSRF-Token) и Origin /
Referer ровно https://vpn.drbl.tech. CORS для админки — только этот
origin, никогда *.
"""

from __future__ import annotations

import logging
import secrets

ADMIN_ORIGIN = "https://vpn.drbl.tech"
SESSION_COOKIE = "drebol_admin"
CSRF_COOKIE = "drebol_admin_csrf"
SESSION_DAYS = 7
SETUP_TOKEN_MINUTES = 15

# Ключи, которые веб-админка никогда не возвращает и не принимает:
# секреты — только запись через ТГ-админку, в вебе они write-only.
SECRET_KEYS = {
    "rw_token", "platega_secret", "support_bot_token", "site_pass",
    "turnstile_secret_key", "platega_merchant_id",
}

# Фаза 1: только безопасные, читаемые на лету настройки.
# morning_sync и netcheck — словари, остальные — скаляры.
SETTINGS_ALLOWLIST = {
    "channel_url", "force_subscribe", "sub_link_domain",
    "privacy_url", "terms_url", "refund_url", "rules_url", "consent_url",
    "paid_trial_period", "paid_preset_hwid", "paid_preset_traffic",
    "paid_preset_lte",
    "referral_bonus", "referral_invited_bonus",
    "remind_enabled", "remind_first", "remind_second", "remind_third",
    "remind_trials", "remind_quiet_from", "remind_quiet_to",
    "winback_enabled", "winback_paid_only", "winback_days",
    "winback_percent", "winback_days2", "winback_percent2",
    "winback_life_days",
    "maintenance_enabled", "maintenance_text", "features_off",
    "morning_sync", "netcheck",
    "device_price", "device_max_extra",
}
_BOOL_KEYS = {
    "force_subscribe", "remind_enabled", "remind_trials",
    "winback_enabled", "winback_paid_only", "maintenance_enabled",
}
_INT_KEYS = {
    "paid_trial_period", "paid_preset_hwid", "paid_preset_traffic",
    "paid_preset_lte", "referral_bonus", "referral_invited_bonus",
    "remind_first", "remind_second", "remind_third",
    "winback_days", "winback_percent", "winback_days2",
    "winback_percent2", "winback_life_days",
    "device_price", "device_max_extra",
}
_URL_KEYS = {
    "channel_url", "privacy_url", "terms_url", "refund_url",
    "rules_url", "consent_url",
}
_STR_KEYS = {"maintenance_text", "remind_quiet_from", "remind_quiet_to"}
# Тумблеры утренней сводки — те же ключи, что в handlers/morning.py
# DEFAULTS (handle_morning_toggle): tags и device_watch — тоже здесь.
# panel_sync сюда не входит: синхронизация с панелью только вручную,
# get_morning_cfg этот ключ выбрасывает, запись была бы тихим no-op.
_MORNING_BOOL = {
    "enabled", "reconcile", "netcheck", "alerts", "support_topics",
    "blacklist_sync", "site_sync", "server_reminder",
    "healthcheck", "backup", "tags", "device_watch",
}
_NETCHECK_KEYS = {"domains", "operators", "netcheck_days", "netcheck_last_run"}

_application = None

# Двухшаговое подтверждение разрушительных действий (DESIGN §4.4):
# первый POST возвращает confirm_token, второй выполняет действие.
# Токены — только в памяти одного процесса, живут 10 минут, одноразовые.
import time as _time

_CONFIRMS: dict = {}
CONFIRM_TTL_SECONDS = 600


def issue_confirm(actor: dict, action: str, payload: dict,
                  summary: str = "") -> str:
    token = secrets.token_urlsafe(24)
    _CONFIRMS[token] = {
        "actor_kind": actor["kind"],
        "actor_id": actor.get("tg_id") or actor.get("account_id"),
        "action": action, "payload": payload,
        "summary": summary, "expires": _time.time() + CONFIRM_TTL_SECONDS,
    }
    return token


def take_confirm(actor: dict, token: str, action: str):
    """Возвращает payload, если токен живой, того же актора и того же
    действия; иначе None. Токен одноразовый — забирается всегда."""
    rec = _CONFIRMS.pop(token, None)
    if not rec:
        return None
    if rec["action"] != action or rec["actor_kind"] != actor["kind"]:
        return None
    if rec["actor_id"] != (actor.get("tg_id") or actor.get("account_id")):
        return None
    if rec["expires"] < _time.time():
        return None
    return rec["payload"]


def confirm_needed_response(token: str, summary: str):
    from aiohttp import web
    return web.json_response(
        {"ok": False, "need_confirm": True, "confirm_token": token,
         "summary": summary})


def get_bot():
    """Telegram Bot из Application — для DM и рассылки. None в тестах
    без Application (эндпоинты тогда отвечают 503 no_bot)."""
    if _application is not None and hasattr(_application, "bot"):
        return _application.bot
    return None


def require_mark(actor: dict):
    """Mark-only: True — актор Mark, иначе False (Muse → 403)."""
    return actor["kind"] == "mark"


def set_application(application) -> None:
    """Telegram Application бота — для пересборки утренней задачи после
    смены времени/включения. Ставится из webapi.start_server()."""
    global _application
    _application = application


def _reschedule_morning() -> bool:
    if _application is not None:
        try:
            from handlers.morning import schedule_morning_sync
            schedule_morning_sync(_application)
        except Exception as ex:
            logging.error("админка: reschedule morning: %s", ex)
            return False
        return True
    return False


# ── Валидация настроек ───────────────────────────────────────────────────────

def _is_time(text) -> bool:
    from handlers.morning import parse_time
    return parse_time(str(text or "")) is not None


def validate_settings_patch(patch: dict):
    """Проверяет PATCH настроек фазы 1.

    Возвращает (clean, rejected, errors): clean — готовые к записи
    значения; rejected — ключи, которые веб вообще не принимает
    (секреты и неизвестные — 403, ничего не применяется);
    errors — неверные значения (400)."""
    if not isinstance(patch, dict):
        return {}, [], ["patch must be an object"]
    clean, rejected, errors = {}, [], []
    for key, value in patch.items():
        if key in SECRET_KEYS or key not in SETTINGS_ALLOWLIST:
            rejected.append(key)
            continue
        if key == "morning_sync":
            if not isinstance(value, dict):
                errors.append("morning_sync must be an object")
                continue
            sub = {}
            for k, v in value.items():
                if k == "time":
                    if not isinstance(v, str) or not _is_time(v):
                        errors.append("morning_sync.time must be HH:MM")
                    else:
                        from handlers.morning import parse_time
                        h, m = parse_time(v)
                        sub["time"] = f"{h:02d}:{m:02d}"
                elif k == "netcheck_days":
                    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                        errors.append("morning_sync.netcheck_days must be int >= 1")
                    else:
                        sub[k] = v
                elif k == "netcheck_last_run":
                    sub[k] = v if v is None or isinstance(v, str) else str(v)
                elif k in _MORNING_BOOL:
                    if not isinstance(v, bool):
                        errors.append(f"morning_sync.{k} must be bool")
                    else:
                        sub[k] = v
                else:
                    rejected.append(f"morning_sync.{k}")
            clean[key] = sub
            continue
        if key == "netcheck":
            if not isinstance(value, dict):
                errors.append("netcheck must be an object")
                continue
            sub = {}
            for k, v in value.items():
                if k not in _NETCHECK_KEYS:
                    rejected.append(f"netcheck.{k}")
                elif k in ("domains", "operators"):
                    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                        errors.append(f"netcheck.{k} must be a list of strings")
                    else:
                        sub[k] = list(v)
                elif k == "netcheck_days":
                    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                        errors.append("netcheck.netcheck_days must be int >= 1")
                    else:
                        sub[k] = v
                elif k == "netcheck_last_run":
                    # Дата последнего запуска — строка «YYYY-MM-DD» или
                    # null; мусор приводим к строке, как в morning_sync.
                    sub[k] = v if v is None or isinstance(v, str) else str(v)
                else:
                    sub[k] = v
            clean[key] = sub
            continue
        if key in _BOOL_KEYS:
            if not isinstance(value, bool):
                errors.append(f"{key} must be bool")
            else:
                clean[key] = value
        elif key in _INT_KEYS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"{key} must be int >= 0")
            else:
                clean[key] = value
        elif key in _URL_KEYS:
            if not isinstance(value, str) or (value and not value.startswith(("http://", "https://"))):
                errors.append(f"{key} must be an http(s) URL or empty")
            else:
                clean[key] = value
        elif key == "sub_link_domain":
            if value not in ("sub", "key"):
                errors.append('sub_link_domain must be "sub" or "key"')
            else:
                clean[key] = value
        elif key == "features_off":
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                errors.append("features_off must be a list of strings")
            else:
                clean[key] = list(value)
        elif key in _STR_KEYS:
            if key.startswith("remind_quiet_"):
                # Тихие часы хранятся целыми часами 0–23 — так пишет ТГ
                # (handlers/messages.py) и так их читают in_quiet_hours
                # и экран ТГ (int() от значения). Строка «23:00» и
                # пустая строка роняли бы их с ValueError, поэтому
                # принимаем int-час, «HH:MM» (нормализуем в час) и
                # пустое/None — выключено.
                if value is None or value == "":
                    clean[key] = None
                elif isinstance(value, bool):
                    errors.append(f"{key} must be an hour 0-23, HH:MM or empty")
                elif isinstance(value, int):
                    if not 0 <= value <= 23:
                        errors.append(f"{key} must be an hour 0-23, HH:MM or empty")
                    else:
                        clean[key] = value
                elif isinstance(value, str) and _is_time(value):
                    from handlers.morning import parse_time
                    clean[key] = parse_time(value)[0]
                else:
                    errors.append(f"{key} must be an hour 0-23, HH:MM or empty")
            elif not isinstance(value, str):
                errors.append(f"{key} must be a string")
            else:
                clean[key] = value
        else:
            clean[key] = value
    return clean, rejected, errors


# ── Сессии, CSRF, Origin ─────────────────────────────────────────────────────

def _client_ip(request) -> str:
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.remote or "?"))


def _secure_flag(request) -> bool:
    if request.scheme == "https":
        return True
    return request.headers.get("X-Forwarded-Proto", "") == "https"


def _set_session_cookies(response, request, token: str) -> None:
    secure = _secure_flag(request)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400,
        path="/api/admin/", httponly=True, secure=secure, samesite="Strict")
    # CSRF-кука ДОЛЖНА быть видна странице /admin/ (JS читает её из
    # document.cookie и шлёт в X-CSRF-Token). Path=/api/admin/ страницу
    # /admin/ не покрывает — браузер такую куку на /admin/ не отдаёт,
    # и все мутации падали с bad_csrf (2026-11-15, создание аккаунта Muse).
    # Поэтому CSRF — Path=/, а старую куку с /api/admin/ гасим, чтобы
    # браузер не слал две одноимённые куки с разными значениями.
    response.del_cookie(CSRF_COOKIE, path="/api/admin/")
    response.set_cookie(
        CSRF_COOKIE, secrets.token_urlsafe(32), max_age=SESSION_DAYS * 86400,
        path="/", httponly=False, secure=secure, samesite="Strict")


def _clear_session_cookies(response) -> None:
    response.del_cookie(SESSION_COOKIE, path="/api/admin/")
    response.del_cookie(CSRF_COOKIE, path="/")
    response.del_cookie(CSRF_COOKIE, path="/api/admin/")


async def _actor(request):
    """Кто пришёл: {"kind": "mark", "tg_id": ...} или
    {"kind": "muse", "account_id": ..., "email": ...}. None — нет сессии.
    Токен читается ТОЛЬКО из куки: ?token= и Authorization не принимаются."""
    from core.database import admin_account_by_id, admin_session_user
    token = request.cookies.get(SESSION_COOKIE) or ""
    sess = await admin_session_user(token)
    if not sess:
        return None
    if sess["account_id"] == 0 and sess["tg_id"]:
        from config import ADMIN_ID
        if int(sess["tg_id"]) == int(ADMIN_ID):
            return {"kind": "mark", "tg_id": int(sess["tg_id"])}
        return None
    if sess["account_id"] > 0:
        row = await admin_account_by_id(sess["account_id"])
        if not row or row[6]:
            return None
        return {"kind": "muse", "account_id": int(row[0]), "email": row[1]}
    return None


def _actor_tg_id(actor: dict) -> int:
    return int(actor["tg_id"]) if actor["kind"] == "mark" else 0


async def _audit(actor: dict, action: str, details: str = "") -> None:
    from core.database import log_activity
    # Пароли, токены и хеши сюда не попадают никогда — только кто и что.
    await log_activity(_actor_tg_id(actor), f"admin:{action}",
                       details, is_admin=True)


def _check_origin(request) -> bool:
    """Меняющий запрос — только с нашего сайта. Origin приоритетен;
    без Origin проверяем Referer; без обоих — разрешаем (curl/тесты)."""
    origin = request.headers.get("Origin", "")
    if origin:
        return origin == ADMIN_ORIGIN
    referer = request.headers.get("Referer", "")
    if referer:
        return referer.startswith(ADMIN_ORIGIN + "/")
    return True


def _check_csrf(request) -> bool:
    token = request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not token or not cookie:
        return False
    import hmac
    return hmac.compare_digest(token, cookie)


def _forbidden(request, error: str, status: int = 403):
    from aiohttp import web
    return web.json_response({"error": error}, status=status)


def _csv_response(header: list, rows: list, fname: str):
    """CSV-файл: запятая как в экспорте логов (handlers/control.py
    _export_rows_to_csv), UTF-8, Content-Disposition с именем файла.
    None — пустая ячейка; поля с запятой/кавычками csv экранирует сам."""
    import csv
    import io
    from aiohttp import web
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for row in rows:
        w.writerow([("" if v is None else v) for v in row])
    return web.Response(text=buf.getvalue(), content_type="text/csv",
                        charset="utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{fname}"'})


# ── Обработчики ──────────────────────────────────────────────────────────────

async def _require_actor(request):
    from aiohttp import web
    actor = await _actor(request)
    if not actor:
        raise web.HTTPUnauthorized(reason="no_session")
    return actor


async def _require_mutation(request):
    """Меняющий запрос: сессия + Origin + CSRF. Возвращает (actor, error)."""
    actor = await _actor(request)
    if not actor:
        return None, _forbidden(request, "no_session", 401)
    if not _check_origin(request):
        return None, _forbidden(request, "bad_origin")
    if not _check_csrf(request):
        return None, _forbidden(request, "bad_csrf")
    return actor, None


async def auth_telegram(request):
    from aiohttp import web
    from core.database import admin_session_new
    from web.webapi import check_webapp, check_widget
    try:
        body = await request.json()
    except Exception:
        body = {}
    source = "webapp" if body.get("initData") else "widget"
    who = (check_webapp(body.get("initData")) if source == "webapp"
           else check_widget(body.get("user") or body))
    if not who:
        return web.json_response({"error": "bad_signature"}, status=401)
    from config import ADMIN_ID
    if int(who["id"]) != int(ADMIN_ID):
        await _audit({"kind": "mark", "tg_id": int(who["id"])},
                     "login_failed", "telegram: not admin")
        return web.json_response({"error": "not_admin"}, status=403)
    token = await admin_session_new(0, int(who["id"]), _client_ip(request),
                                    request.headers.get("User-Agent", ""))
    resp = web.json_response({"ok": True, "actor": "mark"})
    _set_session_cookies(resp, request, token)
    await _audit({"kind": "mark", "tg_id": int(who["id"])},
                 "login", "telegram")
    return resp


async def auth_password(request):
    """Вход Muse по почте и паролю. Без Turnstile — по решению Mark
    2026-11-15; взамен блокировка 5/15 мин на пару (аккаунт, IP)."""
    from aiohttp import web
    from core.database import (
        admin_account_by_email, admin_account_touch_login,
        admin_login_fail_clear, admin_login_fail_hit, admin_login_locked,
        admin_session_new,
    )
    from web.webapi import _valid_email, check_secret
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = _valid_email(body.get("email"))
    password = str(body.get("password") or "")
    if not email or not password:
        return web.json_response({"error": "bad_request"}, status=400)
    ip = _client_ip(request)
    row = await admin_account_by_email(email)
    # Аккаунта нет — тот же ответ, что и неверный пароль, и та же
    # блокировка по «аккаунту 0», чтобы нельзя было перебирать почты.
    account_id = int(row[0]) if row else 0
    if await admin_login_locked(account_id, ip):
        return web.json_response({"error": "too_many"}, status=429)
    if (not row or row[6] or not row[2]
            or not check_secret(password, row[2])):
        await admin_login_fail_hit(account_id, ip)
        await _audit({"kind": "muse", "email": email},
                     "login_failed", "password")
        return web.json_response({"error": "bad_login"}, status=401)
    await admin_login_fail_clear(account_id, ip)
    await admin_account_touch_login(account_id)
    token = await admin_session_new(account_id, None, ip,
                                    request.headers.get("User-Agent", ""))
    resp = web.json_response({"ok": True, "actor": "muse", "email": row[1]})
    _set_session_cookies(resp, request, token)
    await _audit({"kind": "muse", "email": row[1]}, "login", "password")
    return resp


async def auth_setup(request):
    """Установка пароля по одноразовой ссылке Mark'а: токен — хеш,
    15 минут, одно использование. Пароль 8–128 символов."""
    from aiohttp import web
    from core.database import (
        admin_account_by_id, admin_account_set_password,
        admin_session_new, admin_setup_token_live, admin_setup_token_use,
    )
    from web.webapi import check_secret, hash_secret
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = str(body.get("token") or "")
    password = str(body.get("password") or "")
    if not token or len(password) < 8 or len(password) > 128:
        return web.json_response({"error": "bad_request"}, status=400)
    # Живые токены перебираем по всем аккаунтам: их единицы, а хеш
    # scrypt не даёт искать по значению напрямую.
    async def _find_account():
        from core.database import admin_account_list
        for acc in await admin_account_list():
            for token_hash, _exp in await admin_setup_token_live(acc[0]):
                if check_secret(token, token_hash):
                    return acc[0], token_hash
        return None, None
    account_id, token_hash = await _find_account()
    if not account_id:
        return web.json_response({"error": "bad_token"}, status=401)
    await admin_setup_token_use(token_hash)
    await admin_account_set_password(account_id, hash_secret(password))
    row = await admin_account_by_id(account_id)
    ip = _client_ip(request)
    sess = await admin_session_new(account_id, None, ip,
                                   request.headers.get("User-Agent", ""))
    resp = web.json_response({"ok": True, "actor": "muse", "email": row[1]})
    _set_session_cookies(resp, request, sess)
    await _audit({"kind": "muse", "email": row[1]},
                 "setup", "password set via setup token")
    return resp


async def logout(request):
    from aiohttp import web
    from core.database import admin_session_drop
    token = request.cookies.get(SESSION_COOKIE) or ""
    if token:
        await admin_session_drop(token)
    resp = web.json_response({"ok": True})
    _clear_session_cookies(resp)
    return resp


async def me(request):
    from aiohttp import web
    try:
        actor = await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    if actor["kind"] == "mark":
        return web.json_response({"ok": True, "actor": "mark",
                                  "tg_id": actor["tg_id"]})
    return web.json_response({"ok": True, "actor": "muse",
                              "email": actor["email"],
                              "account_id": actor["account_id"]})


async def dashboard(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import get_dashboard_stats, payments_summary
    from services.panel import count_panel_clients
    stats = await get_dashboard_stats()
    try:
        panel = await count_panel_clients()
    except Exception as ex:
        panel = {"success": False, "error": f"{type(ex).__name__}: {ex}"}
    # Деньги — нетто, как в сверке с Platega: только оплаченные счета,
    # частичные возвраты вычтены, полные возвраты не считаются.
    money = await payments_summary()
    return web.json_response({"stats": stats, "panel": panel,
                              "money": money})


async def dashboard_series(request):
    """Ряды для графиков: выручка и новые юзеры по дням (≤30 дней),
    подписки по статусу и по сроку тарифа."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import dashboard_series as _series
    try:
        days = int(request.query.get("days") or 30)
    except ValueError:
        return web.json_response({"error": "bad_days"}, status=400)
    # Период графиков — только 7/30 дней, как переключатель
    # «📅 За 7/30 дн.» в ТГ (handle_payment_stats).
    if days not in (7, 30):
        return web.json_response({"error": "bad_days"}, status=400)
    return web.json_response(await _series(days))


async def dashboard_paid(request):
    """Платные подписки для дашборда: последние оплаченные счета
    первыми, 25 на страницу."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import dashboard_paid_subs
    try:
        page = int(request.query.get("page") or 1)
    except ValueError:
        return web.json_response({"error": "bad_page"}, status=400)
    rows, total_pages = await dashboard_paid_subs(page)
    return web.json_response({
        "items": [{
            "sub_id": r[0], "tg_id": r[1],
            "name": (r[2] or "").strip() or None,
            "username": r[3] or None,
            "amount": int(r[4]), "period_seconds": r[5],
            "paid_at": r[6], "expire_date": r[7], "status": r[8],
        } for r in rows],
        "page": max(1, page), "total_pages": total_pages})


async def dashboard_expiring(request):
    """Активные подписки, истекающие в ближайшие 3 дня."""
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    from core.database import dashboard_expiring as _expiring
    rows = await _expiring()
    return web.json_response({
        "items": [{
            "sub_id": r[0], "tg_id": r[1],
            "name": (r[2] or "").strip() or None,
            "username": r[3] or None,
            "expire_date": r[4], "status": r[5],
        } for r in rows]})


def _settings_snapshot() -> dict:
    from config import load_config
    from handlers.morning import get_morning_cfg
    cfg = load_config()
    out = {k: cfg.get(k) for k in SETTINGS_ALLOWLIST
           if k not in ("morning_sync", "netcheck")}
    out["morning_sync"] = get_morning_cfg()
    out["netcheck"] = cfg.get("netcheck") or {}
    return out


async def settings_get(request):
    from aiohttp import web
    try:
        await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    return web.json_response({"settings": _settings_snapshot()})


async def settings_patch(request):
    from aiohttp import web
    from config import atomic_update
    from handlers.morning import save_morning_cfg
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    patch = body.get("settings") if isinstance(body, dict) else None
    if not isinstance(patch, dict):
        return web.json_response({"error": "bad_request"}, status=400)
    clean, rejected, errors = validate_settings_patch(patch)
    if rejected:
        return web.json_response(
            {"error": "forbidden_keys", "keys": sorted(set(rejected))},
            status=403)
    if errors:
        return web.json_response({"error": "bad_value", "details": errors},
                                 status=400)
    morning = clean.pop("morning_sync", None)
    rescheduled = None
    if clean:
        def _apply(cfg):
            cfg.update(clean)
        atomic_update(_apply)
    if morning is not None:
        save_morning_cfg(morning)
        rescheduled = _reschedule_morning()
    await _audit(actor, "settings_update",
                 "keys: " + ", ".join(sorted(clean.keys())
                                      + (["morning_sync"] if morning is not None else [])))
    return web.json_response({"ok": True, "settings": _settings_snapshot(),
                              "morning_rescheduled": rescheduled})


async def muse_account_create(request):
    """Mark создаёт аккаунт Muse: только почта. В ответ — одноразовая
    ссылка на установку пароля; она показывается один раз и нигде не
    хранится в открытом виде."""
    from aiohttp import web
    from core.database import (
        admin_account_by_email, admin_account_create, admin_setup_token_new,
    )
    from web.webapi import _valid_email, hash_secret
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    if actor["kind"] != "mark":
        return web.json_response({"error": "mark_only"}, status=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = _valid_email(body.get("email"))
    if not email:
        return web.json_response({"error": "bad_email"}, status=400)
    existing = await admin_account_by_email(email)
    if existing:
        return web.json_response({"error": "email_taken"}, status=409)
    account_id = await admin_account_create(email, actor["tg_id"])
    if not account_id:
        return web.json_response({"error": "email_taken"}, status=409)
    token = secrets.token_urlsafe(32)
    await admin_setup_token_new(account_id, hash_secret(token),
                                SETUP_TOKEN_MINUTES)
    await _audit(actor, "muse_account_create", f"email: {email}")
    return web.json_response({
        "ok": True, "account_id": account_id, "email": email,
        "setup_token": token,
        # Путь — /admin/?token=, а НЕ /admin/setup?token=: страница
        # /admin/ статическая (deploy заливает index.html), маршрута
        # /admin/setup у nginx нет — такая ссылка отдавала 404
        # (2026-11-15, первая ссылка для аккаунта Muse).
        "setup_url": f"{ADMIN_ORIGIN}/admin/?token={token}",
        "expires_minutes": SETUP_TOKEN_MINUTES,
    })


async def muse_account_create_direct(request):
    """Mark задаёт аккаунт Muse напрямую: почта + пароль.

    Второй вариант рядом с одноразовой ссылкой: Mark сам придумывает
    пароль на сайте и передаёт его Muse после создания. Пароль и его
    хеш никогда не возвращаются в ответе и не пишутся в журнал.
    Создаёт новый аккаунт или обновляет пароль существующего."""
    from aiohttp import web
    from core.database import (
        admin_account_by_email, admin_account_create,
        admin_account_set_password, admin_sessions_drop_account,
    )
    from web.webapi import _valid_email, hash_secret
    actor, err = await _require_mutation(request)
    if err is not None:
        return err
    if actor["kind"] != "mark":
        return web.json_response({"error": "mark_only"}, status=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = _valid_email(body.get("email"))
    password = str(body.get("password") or "")
    confirm = str(body.get("password_confirm") or "")
    if not email:
        return web.json_response({"error": "bad_email"}, status=400)
    if len(password) < 8 or len(password) > 128:
        return web.json_response({"error": "bad_password"}, status=400)
    if password != confirm:
        return web.json_response({"error": "password_mismatch"}, status=400)
    existing = await admin_account_by_email(email)
    if existing:
        account_id = int(existing[0])
    else:
        account_id = await admin_account_create(email, actor["tg_id"])
        if not account_id:
            return web.json_response({"error": "email_taken"}, status=409)
    await admin_account_set_password(account_id, hash_secret(password))
    await admin_sessions_drop_account(account_id)
    await _audit(actor, "muse_account_direct", f"email: {email}")
    return web.json_response({"ok": True, "account_id": account_id,
                              "email": email})


async def muse_account_list(request):
    from aiohttp import web
    from core.database import admin_account_list
    try:
        actor = await _require_actor(request)
    except Exception:
        return web.json_response({"error": "no_session"}, status=401)
    if actor["kind"] != "mark":
        return web.json_response({"error": "mark_only"}, status=403)
    rows = await admin_account_list()
    return web.json_response({"accounts": [
        {"id": r[0], "email": r[1], "role": r[2], "created_by_tg_id": r[3],
         "created_at": str(r[4]), "last_login_at": str(r[5] or ""),
         "disabled": bool(r[6])} for r in rows]})


# ── Приложение ───────────────────────────────────────────────────────────────

def build_admin_app():
    from aiohttp import web

    @web.middleware
    async def admin_middleware(request, handler):
        origin = request.headers.get("Origin", "")
        if request.method == "OPTIONS":
            if origin and origin != ADMIN_ORIGIN:
                return web.json_response({"error": "bad_origin"}, status=403)
            resp = web.Response(status=204)
            if origin == ADMIN_ORIGIN:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                resp.headers["Access-Control-Allow-Headers"] = (
                    "Content-Type, X-CSRF-Token")
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH"
            return resp
        try:
            resp = await handler(request)
        except web.HTTPException as ex:
            resp = ex
        except Exception as ex:
            logging.error("админка: %s: %s", type(ex).__name__, ex)
            resp = web.json_response({"error": "server"}, status=500)
        if origin:
            if origin == ADMIN_ORIGIN:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                resp.headers["Vary"] = "Origin"
            # чужой Origin — заголовков не ставим вовсе: браузер ответ не прочитает,
            # а * здесь не появляется никогда.
        return resp

    app = web.Application(middlewares=[admin_middleware])
    app.router.add_post("/auth/telegram", auth_telegram)
    app.router.add_post("/auth/password", auth_password)
    app.router.add_post("/auth/setup", auth_setup)
    app.router.add_post("/logout", logout)
    app.router.add_get("/me", me)
    app.router.add_get("/dashboard", dashboard)
    app.router.add_get("/dashboard/series", dashboard_series)
    app.router.add_get("/dashboard/paid", dashboard_paid)
    app.router.add_get("/dashboard/expiring", dashboard_expiring)
    app.router.add_get("/settings", settings_get)
    app.router.add_patch("/settings", settings_patch)
    app.router.add_post("/muse-account", muse_account_create)
    app.router.add_post("/muse-account/direct", muse_account_create_direct)
    app.router.add_get("/muse-account", muse_account_list)
    # Фаза 2: юзеры и подписки (web/admin_users.py), финансы и
    # рассылка (web/admin_finance.py); инфраструктура регистрируется
    # в webapi.build_app() из web/admin_infra.py.
    from web.admin_users import register as _register_users
    _register_users(app)
    from web.admin_finance import register as _register_finance
    _register_finance(app)
    # Консоль серверов и токен-вход Muse (web/admin_console.py).
    from web.admin_console import register as _register_console
    _register_console(app)
    return app
