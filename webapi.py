"""Личный кабинет: маленькое API для сайта и мини-приложения.

Бот поднимает у себя http-сервер и отдаёт по нему данные подписки. Внутрь
пускают двумя дверями, и обе подписаны токеном бота:

• Telegram Login Widget на сайте — параметры с hash (HMAC-SHA256, ключ —
  SHA256 от токена бота);
• Mini App внутри телеграма — строка initData (ключ — HMAC от «WebAppData»).

После проверки заводится сессия: случайный токен, который браузер хранит у
себя и шлёт в заголовке. Никаких паролей, куки и чужих данных: по токену
видно только одного человека — того, кто вошёл.

Кабинет только показывает. Менять что-либо через него нельзя: все действия
остались в боте, где их видно в журнале.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import time
from datetime import datetime
from urllib.parse import parse_qsl

SESSION_DAYS = 7
# Сколько ждём подпись Telegram: дольше — риск, что данные перехватили и переиграли
AUTH_MAX_AGE = 24 * 3600
# Простая защита от перебора: столько запросов с адреса в минуту
RATE_LIMIT = 60

_rate: dict = {}
_runner = None


# ── Настройки ────────────────────────────────────────────────────────────────

def settings() -> dict:
    from config import load_config
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("webapi_enabled", False)),
        "port": int(cfg.get("webapi_port", 8088) or 8088),
        "bind": str(cfg.get("webapi_bind", "0.0.0.0") or "0.0.0.0"),
    }


# ── Проверка подписи Telegram ────────────────────────────────────────────────

def _bot_token() -> str:
    from config import BOT_TOKEN
    return BOT_TOKEN or ""


def check_widget(data: dict) -> dict | None:
    """Данные кнопки «Войти через Telegram». Возвращает профиль или None."""
    got = dict(data or {})
    their_hash = str(got.pop("hash", ""))
    if not their_hash or not got.get("id"):
        return None
    check = "\n".join(f"{k}={got[k]}" for k in sorted(got) if got[k] is not None)
    secret = hashlib.sha256(_bot_token().encode()).digest()
    mine = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mine, their_hash):
        return None
    try:
        if time.time() - int(got.get("auth_date", 0)) > AUTH_MAX_AGE:
            return None
    except (TypeError, ValueError):
        return None
    return {"id": int(got["id"]), "first_name": got.get("first_name") or "",
            "username": got.get("username") or ""}


def check_webapp(init_data: str) -> dict | None:
    """Строка initData мини-приложения. Возвращает профиль или None."""
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    their_hash = pairs.pop("hash", "")
    if not their_hash:
        return None
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", _bot_token().encode(), hashlib.sha256).digest()
    mine = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mine, their_hash):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", 0)) > AUTH_MAX_AGE:
            return None
        user = json.loads(pairs.get("user") or "{}")
    except (TypeError, ValueError):
        return None
    if not user.get("id"):
        return None
    return {"id": int(user["id"]), "first_name": user.get("first_name") or "",
            "username": user.get("username") or ""}


# ── Данные кабинета ──────────────────────────────────────────────────────────

def _fmt_bytes(value) -> str:
    b = float(value or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if b < 1024:
            return f"{int(b)} {unit}" if unit == "Б" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.2f} ТБ"


async def profile(tg_id: int) -> dict:
    """Всё, что кабинет показывает человеку о нём самом."""
    from blacklist import entry as bl_entry, public_reason
    from database import get_user_info, is_banned, user_payments
    from paidsub.storage import base_hwid, get_paid_sub_by_tg_id, parse_sub_date
    from paidsub.time_parser import fmt_duration_precise

    u = await get_user_info(tg_id)
    out = {
        "user": {"id": tg_id, "name": (u[1] if u else "") or "", "username": (u[2] if u else "") or ""},
        "blocked": None, "subscription": None, "devices": [], "payments": [],
    }
    if await is_banned(tg_id):
        out["blocked"] = {"kind": "ban", "reason": "Доступ к сервису закрыт"}
        return out
    ble = await bl_entry(tg_id)
    if ble:
        out["blocked"] = {"kind": "blacklist", "reason": public_reason(ble["reason"])}
        return out

    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return out

    email, sub_url, limit_hwid = row[2], row[5], row[8]
    status = row[11] if len(row) > 11 else "active"
    renewed = row[12] if len(row) > 12 else 0
    extra = row[18] if len(row) > 18 else 0
    end = parse_sub_date(row[6])
    left = int((end - datetime.now()).total_seconds()) if end else 0

    from panel import get_client_hwids, get_client_info, get_client_traffic
    info = await get_client_info(email)
    enabled = info.get("enabled", True) if info.get("success") else True
    traffic = await get_client_traffic(email)
    used = int(traffic.get("up", 0) or 0) + int(traffic.get("down", 0) or 0)

    out["subscription"] = {
        "status": status,
        "enabled": bool(enabled),
        "plan": "paid" if renewed else "trial",
        "until": row[6],
        "left": max(0, left),
        "left_text": fmt_duration_precise(max(0, left)) if left > 0 else "",
        "url": sub_url,
        "devices_limit": int(limit_hwid or 0),
        "devices_own": base_hwid(limit_hwid, extra),
        "devices_extra": int(extra or 0),
        "traffic_limit_gb": int(row[9] or 0),
        "traffic_used": used,
        "traffic_used_text": _fmt_bytes(used),
        "renewed": int(renewed or 0),
    }

    hw = await get_client_hwids(email)
    if hw.get("ok"):
        for d in hw.get("items", [])[:20]:
            out["devices"].append({
                "model": d.get("deviceModel") or d.get("platform") or "Устройство",
                "platform": d.get("platform") or "",
                "seen": str(d.get("lastSeen") or "")[:16].replace("T", " "),
            })
    rows, pays_count, pays_sum = await user_payments(tg_id, 10)
    out["payments"] = [{"amount": r[2], "status": r[3], "date": str(r[4] or "")[:16]}
                       for r in rows]
    out["payments_total"] = {"count": pays_count, "sum": pays_sum}
    return out


# ── Сервер ───────────────────────────────────────────────────────────────────

def _too_often(ip: str) -> bool:
    now = int(time.time() // 60)
    key = (ip, now)
    for old in [k for k in _rate if k[1] != now]:
        _rate.pop(old, None)
    _rate[key] = _rate.get(key, 0) + 1
    return _rate[key] > RATE_LIMIT


def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def build_app():
    from aiohttp import web

    async def guard(request, handler):
        if request.method == "OPTIONS":
            return _cors(web.Response(status=204))
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
            or (request.remote or "?")
        if _too_often(ip):
            return _cors(web.json_response({"error": "too_many"}, status=429))
        try:
            return _cors(await handler(request))
        except web.HTTPException:
            raise
        except Exception as ex:
            logging.error("кабинет: %s: %s", type(ex).__name__, ex)
            return _cors(web.json_response({"error": "server"}, status=500))

    async def health(_request):
        return web.json_response({"ok": True})

    async def auth(request):
        from database import web_session_new
        try:
            body = await request.json()
        except Exception:
            body = {}
        source = "webapp" if body.get("initData") else "widget"
        who = (check_webapp(body.get("initData"))
               if source == "webapp" else check_widget(body.get("user") or body))
        if not who:
            return web.json_response({"error": "bad_signature"}, status=401)
        from database import upsert_user
        await upsert_user(who["id"], who["first_name"], who["username"])
        token = await web_session_new(who["id"], source, SESSION_DAYS)
        return web.json_response({"token": token, "days": SESSION_DAYS})

    async def me(request):
        from database import web_session_user
        token = (request.headers.get("Authorization", "").replace("Bearer ", "").strip()
                 or request.query.get("token", ""))
        tg_id = await web_session_user(token)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        return web.json_response(await profile(tg_id))

    async def logout(request):
        from database import web_session_drop
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        await web_session_drop(token)
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[web.middleware(guard)])
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/auth", auth)
    app.router.add_get("/api/me", me)
    app.router.add_post("/api/logout", logout)
    return app


async def start_server() -> dict:
    """Поднимает API, если он включён в настройках."""
    global _runner
    s = settings()
    if not s["enabled"]:
        return {"ok": False, "error": "выключен"}
    if _runner is not None:
        return {"ok": True, "already": True}
    from aiohttp import web
    try:
        runner = web.AppRunner(build_app(), access_log=None)
        await runner.setup()
        site_ = web.TCPSite(runner, s["bind"], s["port"])
        await site_.start()
        _runner = runner
        logging.info("кабинет: слушаю %s:%s", s["bind"], s["port"])
        return {"ok": True, "port": s["port"]}
    except Exception as ex:
        logging.error("кабинет не поднялся: %s: %s", type(ex).__name__, ex)
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


async def stop_server():
    global _runner
    if _runner is not None:
        await _runner.cleanup()
        _runner = None


def is_running() -> bool:
    return _runner is not None


async def sessions_tick(context):
    """Раз в сутки убирает просроченные сессии."""
    from database import web_sessions_purge
    await web_sessions_purge()


# ── Настройки кабинета (админка) ─────────────────────────────────────────────

async def handle_cabinet_menu(query, context=None, note: str = ""):
    """Что нужно кабинету, что уже готово и куда нажимать дальше."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from config import load_config
    from database import web_sessions_stats
    import site_deploy as site
    if context:
        context.user_data.pop("state", None)
    cfg = load_config()
    s = settings()
    public = cfg.get("webapi_public") or ""
    stats = await web_sessions_stats()

    ready = [
        ("🌐 Сайт развёрнут", bool(site.creds()["domain"] and cfg.get("site_deployed_at"))),
        ("🔌 API включён", s["enabled"]),
        ("🛰 API работает", is_running()),
        ("🔗 Адрес API задан", bool(public)),
        ("🪪 Кабинет опубликован", site.cabinet_ready()),
    ]
    lines = ["🪪 <b>Личный кабинет</b>", ""]
    if note:
        lines += [note, ""]
    lines.append("<blockquote>" + "\n".join(
        ("✅ " if ok else "⬜️ ") + name for name, ok in ready) + "</blockquote>")
    lines.append(
        "<blockquote>"
        f"🔌 Порт: <b>{s['port']}</b>  ·  слушаем: <b>{s['bind']}</b>\n"
        f"🔗 Адрес API: <b>{html.escape(public) if public else 'не задан'}</b>\n"
        f"👥 Живых сессий: <b>{stats['live']}</b>  ·  людей: <b>{stats['people']}</b>  ·  "
        f"входов сегодня: <b>{stats['today']}</b>"
        "</blockquote>")
    link = site.cabinet_link()
    if link:
        lines.append(f"<blockquote>🪪 Кабинет: {html.escape(link)}</blockquote>")
    upstream = cfg.get("webapi_upstream") or ""
    if upstream:
        lines.append(f"<blockquote>🔀 Сайт шлёт <code>/api/</code> на "
                     f"<b>{html.escape(upstream)}</b></blockquote>")
    lines.append(
        "\n<i>Кабинет только показывает: срок, ссылку подписки, устройства и платежи. "
        "Менять что-либо можно только в боте.\n\n"
        "Порядок такой: «🔀 Через сайт» (адрес бота вида <code>1.2.3.4:8088</code>) → "
        "«🟢 Включить API» → развернуть сайт заново. И скажи @BotFather команду "
        "/setdomain с доменом сайта — без неё кнопка входа не появится.</i>")

    kb = [[InlineKeyboardButton("🔴 Выключить API" if s["enabled"] else "🟢 Включить API",
                                callback_data="cab_toggle")],
          [InlineKeyboardButton("🔀 Через сайт", callback_data="cab_upstream"),
           InlineKeyboardButton("🔗 Адрес API", callback_data="cab_public"),
           InlineKeyboardButton("🔌 Порт", callback_data="cab_port")]]
    if link:
        kb.append([InlineKeyboardButton("🪪 Открыть кабинет", url=link)])
    kb.append([InlineKeyboardButton("🌐 К сайту", callback_data="site_menu"),
               InlineKeyboardButton("◀️ В админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_cabinet_toggle(query, context):
    from config import load_config, save_config
    cfg = load_config()
    turn_on = not cfg.get("webapi_enabled", False)
    cfg["webapi_enabled"] = turn_on
    save_config(cfg)
    if turn_on:
        res = await start_server()
        note = ("<i>🟢 API поднят.</i>" if res.get("ok")
                else f"<i>⚠️ Не поднялся: {html.escape(str(res.get('error')))}</i>")
    else:
        await stop_server()
        note = "<i>🔴 API выключен — кабинет перестал отвечать.</i>"
    await handle_cabinet_menu(query, context, note=note)


async def handle_cabinet_ask(query, context, what: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_CABINET_PORT, AWAITING_CABINET_PUBLIC, AWAITING_CABINET_UPSTREAM
    if what == "upstream":
        context.user_data["state"] = AWAITING_CABINET_UPSTREAM
        text = ("🔀 <b>Кабинет через сайт</b>\n\n"
                "<blockquote>Пришли адрес бота, каким его видит сервер сайта:\n"
                "<code>1.2.3.4:8088</code>\n\n"
                "Сайт будет пересылать <code>/api/</code> туда, и отдельный "
                "поддомен с сертификатом не понадобится.</blockquote>\n\n"
                "<i>Порт бота должен быть открыт для адреса сайта. "
                "Пришли <code>-</code>, чтобы убрать пересылку.</i>")
        await query.edit_message_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="cab_menu")]]))
        return
    if what == "port":
        context.user_data["state"] = AWAITING_CABINET_PORT
        text = ("🔌 <b>Порт API</b>\n\n"
                "<blockquote>Пришли число — на этом порту бот будет отвечать "
                "кабинету. По умолчанию 8088.</blockquote>")
    else:
        context.user_data["state"] = AWAITING_CABINET_PUBLIC
        text = ("🔗 <b>Адрес API</b>\n\n"
                "<blockquote>Пришли адрес, по которому API виден снаружи:\n"
                "<code>https://api.drbl.tech</code>\n\n"
                "Это может быть поддомен с сертификатом или тот же сайт, если "
                "прокинуть на нём путь <code>/api/</code> к боту.</blockquote>\n\n"
                "<i>Без https браузер не пустит запросы со страницы кабинета.</i>")
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="cab_menu")]]))


async def handle_cabinet_input(update, context, state: str, text: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from config import load_config, save_config
    from states import AWAITING_CABINET_PORT, AWAITING_CABINET_UPSTREAM
    import site_deploy as site
    msg = update.message
    back = InlineKeyboardMarkup([[InlineKeyboardButton("🪪 К кабинету", callback_data="cab_menu")]])
    cfg = load_config()
    if state == AWAITING_CABINET_PORT:
        if not text.strip().isdigit() or not (1024 <= int(text.strip()) <= 65535):
            await msg.reply_text("❌ <b>Нужен порт от 1024 до 65535</b>", parse_mode="HTML",
                                 reply_markup=back)
            return
        cfg["webapi_port"] = int(text.strip())
        save_config(cfg)
        context.user_data.pop("state", None)
        await stop_server()
        res = await start_server()
        tail = "" if res.get("ok") else f"\n\n⚠️ <i>{html.escape(str(res.get('error')))}</i>"
        await msg.reply_text(f"✅ <b>Порт: {cfg['webapi_port']}</b>{tail}",
                             parse_mode="HTML", reply_markup=back)
        return

    if state == AWAITING_CABINET_UPSTREAM:
        target = text.strip()
        if target == "-":
            cfg["webapi_upstream"] = ""
            save_config(cfg)
            context.user_data.pop("state", None)
            await msg.reply_text("✅ <b>Пересылка убрана</b>\n\n"
                                 "<i>Разверни сайт заново, чтобы он забыл про неё.</i>",
                                 parse_mode="HTML", reply_markup=back)
            return
        host, _, port = target.partition(":")
        if not host or not port.isdigit():
            await msg.reply_text("❌ <b>Нужен адрес вида <code>1.2.3.4:8088</code></b>",
                                 parse_mode="HTML", reply_markup=back)
            return
        cfg["webapi_upstream"] = target
        # раз сайт сам отдаёт /api/, кабинету достаточно адреса сайта
        if site.creds()["domain"]:
            cfg["webapi_public"] = site.site_url()
        save_config(cfg)
        context.user_data.pop("state", None)
        await msg.reply_text(
            f"✅ <b>Сайт будет слать /api/ на {html.escape(target)}</b>\n\n"
            f"<i>Адрес API: {html.escape(cfg.get('webapi_public') or 'задай вручную')}.\n"
            "Теперь разверни сайт заново.</i>", parse_mode="HTML", reply_markup=back)
        return

    url = text.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    if url and " " in url:
        await msg.reply_text("❌ <b>Адрес без пробелов</b>\n\n"
                             "<i>Например <code>https://api.drbl.tech</code></i>",
                             parse_mode="HTML", reply_markup=back)
        return
    cfg["webapi_public"] = "" if text.strip() == "-" else url
    save_config(cfg)
    context.user_data.pop("state", None)
    saved = cfg["webapi_public"]
    await msg.reply_text(
        (f"✅ <b>Адрес API: {html.escape(saved)}</b>\n\n"
         "<i>Теперь разверни сайт заново — страница кабинета уедет с новым адресом.</i>")
        if saved else "✅ <b>Адрес API убран</b>",
        parse_mode="HTML", reply_markup=back)
