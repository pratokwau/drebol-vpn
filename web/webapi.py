"""Личный кабинет: маленькое API для сайта и мини-приложения.

Бот поднимает у себя http-сервер и отдаёт по нему данные подписки. Внутрь
пускают двумя дверями, и обе подписаны токеном бота:

• Telegram Login Widget на сайте — параметры с hash (HMAC-SHA256, ключ —
  SHA256 от токена бота);
• Mini App внутри телеграма — строка initData (ключ — HMAC от «WebAppData»).

После проверки заводится сессия: случайный токен, который браузер хранит у
себя и шлёт в заголовке. Никаких паролей, куки и чужих данных: по токену
видно только одного человека — того, кто вошёл.

Кабинет показывает срок, трафик, LTE, устройства, платежи и рефералку.
Действия — те же, что уже есть в боте для самого человека: отключить
своё устройство, перевыпустить свой ключ, продлить подписку, оформить
первую подписку (пробный период или покупка) и подарить подписку другу.
Продление, покупка и подарок идут через тот же счёт Platega,
что и в боте, а подтверждение — колбэком Platega на /api/webhooks/platega,
опрос статусов фоновой задачей бота — страховка. После оплаты Platega
возвращает человека по редиректу из счёта (страницы /pay/* на сайте).
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
_bot = None  # Telegram-бот: отправляет коды сброса пароля в чат

# Вход по почте: столько неверных попыток с одной почты за 15 минут
PW_MAX_FAILS = 5
PW_FAIL_WINDOW = 15 * 60
RESET_CODE_MINUTES = 15
_pw_fail: dict = {}


# ── Настройки ────────────────────────────────────────────────────────────────

def settings() -> dict:
    from config import load_config
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("webapi_enabled", False)),
        "port": int(cfg.get("webapi_port", 8088) or 8088),
        # Веб-админка (фаза 1): слушаем только localhost, наружу — только
        # через nginx сайта. Старое значение по умолчанию 0.0.0.0 — находка
        # аудита K5; явный webapi_bind в config.json по-прежнему уважается.
        "bind": str(cfg.get("webapi_bind", "127.0.0.1") or "127.0.0.1"),
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


# ── Вход по почте и паролю ───────────────────────────────────────────────────

def _valid_email(email: str) -> str:
    """Почта как логин: строчные, без пробелов, с @ и доменом. Иначе ""."""
    import re
    email = (email or "").strip().lower()
    if len(email) > 254 or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return ""
    return email


def hash_secret(secret: str) -> str:
    """Хеш пароля или кода сброса: scrypt из стандартной библиотеки."""
    import secrets
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(secret.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$n=16384$r=8$p=1${salt.hex()}${dk.hex()}"


def check_secret(secret: str, stored: str) -> bool:
    try:
        parts = (stored or "").split("$")
        params = dict(kv.split("=") for kv in parts[1:4])
        salt = bytes.fromhex(parts[4])
        want = bytes.fromhex(parts[5])
        dk = hashlib.scrypt(secret.encode(), salt=salt,
                            n=int(params["n"]), r=int(params["r"]),
                            p=int(params["p"]), dklen=len(want))
        return hmac.compare_digest(dk, want)
    except Exception:
        return False


def _pw_locked(key: str) -> bool:
    """Ключ (почта или forgot:почта) временно закрыт после неверных попыток."""
    now = time.time()
    fails, first = _pw_fail.get(key, (0, now))
    if now - first > PW_FAIL_WINDOW:
        _pw_fail.pop(key, None)
        return False
    return fails >= PW_MAX_FAILS


def _pw_fail_hit(key: str):
    now = time.time()
    fails, first = _pw_fail.get(key, (0, now))
    if now - first > PW_FAIL_WINDOW:
        fails, first = 0, now
    _pw_fail[key] = (fails + 1, first)


def _pw_fail_clear(key: str):
    _pw_fail.pop(key, None)


async def _turnstile_ok(token: str, ip: str) -> bool:
    """Проверяет капчу у Cloudflare. Нет ключа — вход по паролю выключен."""
    from config import turnstile_keys
    _, secret = turnstile_keys()
    if not secret or not token:
        return False
    try:
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": secret, "response": token, "remoteip": ip},
            ) as r:
                data = await r.json()
        return bool(data.get("success"))
    except Exception as ex:
        logging.error("кабинет: turnstile: %s: %s", type(ex).__name__, ex)
        return False


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
    from features.blacklist import entry as bl_entry, public_reason
    from core.database import get_user_info, user_payments
    from paidsub.storage import base_hwid, get_paid_sub_by_tg_id, parse_sub_date
    from paidsub.time_parser import fmt_duration_precise

    u = await get_user_info(tg_id)
    out = {
        "user": {"id": tg_id, "name": (u[1] if u else "") or "", "username": (u[2] if u else "") or ""},
        "blocked": None, "subscription": None, "devices": [], "payments": [],
        "referral": None, "lte": None,
    }
    # Вход по почте и паролю: кабинет по этому флагу показывает раздел
    # «Профиль» и красную точку, пока почта или пароль не заданы.
    from core.database import get_login_info
    login_email, has_password = await get_login_info(tg_id)
    out["login"] = {"email": login_email or "", "has_password": bool(has_password)}
    # Ссылка на бота поддержки — чтобы из кабинета было куда обратиться
    try:
        from handlers.support import support_bot_url
        out["support_url"] = support_bot_url()
    except Exception:
        out["support_url"] = ""
    # Рефералка не зависит от подписки: её видно и без неё
    try:
        from paidsub.storage import get_referral_list, get_referral_stats
        from paidsub.time_parser import fmt_duration
        rs = await get_referral_stats(tg_id)
        out["referral"] = {
            "invited": int(rs["total"] or 0),
            "rewarded": int(rs["rewarded"] or 0),
            "bonus_text": fmt_duration(rs["total_bonus"]) if rs["total_bonus"] else "",
        }
        # Список приглашённых: кто пришёл и кому уже начислен бонус.
        lst = await get_referral_list(tg_id)
        items = []
        for r in lst[:20]:
            ui = await get_user_info(r[0])
            items.append({
                "name": (ui[1] if ui else "") or "Без имени",
                "username": (ui[2] if ui else "") or "",
                "rewarded": bool(r[1]),
                "bonus_text": fmt_duration(r[2]) if r[2] else "",
                "date": str(r[3] or "")[:16],
            })
        out["referral"]["list"] = items
        out["referral"]["list_total"] = len(lst)
        # Правила бонусов — как шапка handle_referral в боте.
        from config import load_config as _lc
        _cfg = _lc()
        out["referral"]["bonus"] = fmt_duration(_cfg.get("referral_bonus")) if _cfg.get("referral_bonus") else ""
        out["referral"]["invited_bonus"] = fmt_duration(_cfg.get("referral_invited_bonus")) if _cfg.get("referral_invited_bonus") else ""
    except Exception:
        pass
    ble = await bl_entry(tg_id)
    if ble:
        out["blocked"] = {"kind": "blacklist", "reason": public_reason(ble["reason"])}
        return out

    # Админская подписка — как экран «🪪 Админская подписка» в боте
    # (handle_my_sub): срок, трафик, живой статус из панели, ссылка.
    # Независима от платной: показывается и когда платной нет.
    admin_row = None
    try:
        from adminsub.storage import get_sub_by_tg_id
        admin_row = await get_sub_by_tg_id(tg_id)
    except Exception:
        admin_row = None
    if admin_row:
        from config import sub_url_for_display
        from services.panel import get_client_info
        a_total = admin_row[9] or 0
        a_enabled = None
        try:
            a_info = await get_client_info(admin_row[2])
            if a_info.get("success"):
                a_enabled = bool(a_info.get("enabled", True))
        except Exception:
            a_enabled = None
        out["admin_subscription"] = {
            "until": str(admin_row[6] or ""),
            "traffic_text": f"{a_total} ГБ" if a_total > 0 else "безлимит",
            "enabled": a_enabled,
            "url": sub_url_for_display(admin_row[5] or ""),
        }

    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return out

    email, sub_url, limit_hwid = row[2], row[5], row[8]
    status = row[11] if len(row) > 11 else "active"
    renewed = row[12] if len(row) > 12 else 0
    extra = row[18] if len(row) > 18 else 0
    end = parse_sub_date(row[6])
    left = int((end - datetime.now()).total_seconds()) if end else 0

    from config import sub_url_for_display
    from services.panel import get_client_hwids, get_client_info, get_client_traffic
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
        "url": sub_url_for_display(sub_url),
        "created_at": str(row[10] or "")[:16],
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
                "id": str(d.get("id") or ""),
                "model": d.get("deviceModel") or d.get("platform") or "Устройство",
                "platform": d.get("platform") or "",
                "seen": str(d.get("lastSeen") or "")[:16].replace("T", " "),
            })
    # Докупка мест: страница показывает сценарий, только когда он реален —
    # цена задана, лимит конечен и потолок докупа ещё не выбран.
    try:
        from config import load_config as _lc
        _cfg = _lc()
        _price = int(_cfg.get("device_price", 0) or 0)
        _max_extra = int(_cfg.get("device_max_extra") or 5)
        _left = max(0, _max_extra - int(extra or 0))
        if _price > 0 and limit_hwid and base_hwid(limit_hwid, extra) and _left > 0:
            out["subscription"]["devices_buy"] = {"price": _price, "left": _left}
    except Exception:
        pass

    rows, pays_count, pays_sum = await user_payments(tg_id, 10)
    # строки user_payments: id, provider, amount, status, date, promo_code —
    # провайдера и промокод тоже отдаём: из них складывается карточка платежа
    out["payments"] = [{"id": r[0], "provider": r[1] or "", "amount": r[2],
                        "status": r[3], "date": str(r[4] or "")[:16],
                        "promo": r[5] or ""} for r in rows]
    out["payments_total"] = {"count": pays_count, "sum": pays_sum}
    return out


# ── Продление ────────────────────────────────────────────────────────────────

async def _renew_quote(tg_id: int, tariff: tuple) -> dict:
    """Цена и состав счёта за продление — ровно как кнопка оплаты в боте:
    тариф, плюс уже купленные места (если места вообще продаются), минус
    висящий промокод из бота, если он есть и ещё действует. Скидка, как
    и в боте, считается только от тарифа, а не от мест."""
    from config import load_config
    from paidsub.handlers import apply_discount, validate_promo
    from paidsub.time_parser import fmt_duration
    from paidsub.storage import base_hwid, get_paid_sub_by_tg_id, get_pending_promo
    row = await get_paid_sub_by_tg_id(tg_id)
    cfg = load_config()
    dev_price = int(cfg.get("device_price", 0) or 0)
    dev_max = int(cfg.get("device_max_extra", 0) or 0)
    limit_now = int(row[8] or 0) if row else 0
    bought = int(row[18] or 0) if row and len(row) > 18 else 0
    if not base_hwid(limit_now, bought):
        dev_price = 0
    devices = max(0, min(bought, dev_max if dev_price else 0))
    base_price = int(tariff[3])
    promo_code = None
    promo_percent = 0
    pending = await get_pending_promo(tg_id)
    if pending:
        promo, _err = await validate_promo(pending, tg_id)
        if promo:
            promo_code = promo[1]
            promo_percent = int(promo[2])
            base_price = apply_discount(base_price, promo[2])
    return {"price": base_price + devices * dev_price,
            "seconds": int(tariff[2]), "name": fmt_duration(int(tariff[2])),
            "kind": "period_dev" if dev_price else "period", "extra": devices,
            "dev_price": dev_price, "promo_code": promo_code,
            "promo_percent": promo_percent}


async def _gift_quote(tg_id: int, tariff: tuple) -> dict:
    """Цена подарка — как в боте (handle_pay_invoice с gift_tg_id):
    тариф минус висящий промокод дарителя, без устройств: подарок —
    только срок, места друг докупит себе сам."""
    from paidsub.handlers import apply_discount, validate_promo
    from paidsub.time_parser import fmt_duration
    from paidsub.storage import get_pending_promo
    base_price = int(tariff[3])
    promo_code = None
    promo_percent = 0
    pending = await get_pending_promo(tg_id)
    if pending:
        promo, _err = await validate_promo(pending, tg_id)
        if promo:
            promo_code = promo[1]
            promo_percent = int(promo[2])
            base_price = apply_discount(base_price, promo[2])
    return {"price": base_price, "seconds": int(tariff[2]),
            "name": fmt_duration(int(tariff[2])),
            "promo_code": promo_code, "promo_percent": promo_percent}


async def _resolve_gift_recipient(giver_tg_id: int, target) -> dict:
    """Получатель подарка — те же правила, что apply_gift_user в ТГ:
    цифры — TG ID как есть (имя из базы, если человек известен —
    так на экране подтверждения видно, кому даришь), @ник — через бота,
    а если бота нет под рукой — по базе (find_user_by_username,
    без учёта регистра).
    Возвращает {"tg_id", "display", "has_sub", "sub_until"}.
    ValueError: bad_target / self_gift / blocked / user_not_found / no_bot.
    Срок действующей подписки друга — expire_date (индекс 6 выборки
    get_paid_sub_by_tg_id); в ТГ здесь же по ошибке берётся индекс 3
    (uuid) — в кабинете показывается настоящий срок."""
    from core.database import find_user_by_username, get_user_info
    from features.blacklist import is_blacklisted
    from paidsub.storage import get_paid_sub_by_tg_id
    raw = str(target or "").strip().lstrip("@")
    tg_id = None
    display = None
    if not raw:
        raise ValueError("bad_target")
    if raw.isdigit():
        tg_id = int(raw)
        display = f"id{tg_id}"
        u = await get_user_info(tg_id)
        if u and u[2]:
            display = f"@{u[2]}"
        elif u and u[1]:
            display = u[1]
    else:
        chat = None
        if _bot is not None:
            try:
                chat = await _bot.get_chat("@" + raw)
            except Exception:
                chat = None
        if chat is not None:
            tg_id = chat.id
            display = (f"@{chat.username}" if getattr(chat, "username", None)
                       else (chat.first_name or f"id{tg_id}"))
        else:
            u = await find_user_by_username(raw)
            if u is None:
                if _bot is None:
                    raise ValueError("no_bot")
                raise ValueError("user_not_found")
            tg_id = int(u[0])
            display = (f"@{u[2]}" if u[2] else (u[1] or f"id{tg_id}"))
    if tg_id == giver_tg_id:
        raise ValueError("self_gift")
    if await is_blacklisted(tg_id):
        raise ValueError("blocked")
    row = await get_paid_sub_by_tg_id(tg_id)
    return {"tg_id": tg_id, "display": display,
            "has_sub": bool(row),
            "sub_until": str(row[6])[:16] if row and row[6] else None}


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


# Ссылки магазинов для раздела «Инфо» — те же, что в боте на экране
# «Как подключиться» (handlers/user.py handle_how_to).
_INFO_APPS = {
    "incy": {
        "ios": "https://apps.apple.com/ru/app/incy/id6756943388",
        "android": "https://play.google.com/store/apps/details?id=llc.itdev.incy&pli=1",
        "windows": "https://github.com/INCY-DEV/incy-platforms/releases/latest/download/incy-windows-setup.exe",
        "macos": "https://apps.apple.com/ru/app/incy/id6756943388",
    },
    "happ": {
        "ios": "https://apps.apple.com/us/app/happ-proxy-utility/id6504287215",
        "android": "https://play.google.com/store/apps/details?id=com.happproxy",
        "windows": "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe",
        "macos": "https://apps.apple.com/us/app/happ-proxy-utility/id6504287215",
    },
}


def build_app():
    from aiohttp import web

    async def guard(request, handler):
        # Админка — свои CORS-правила (только https://vpn.drbl.tech,
        # никогда *): _cors() кабинета сюда не применяется.
        is_admin = request.path.startswith("/api/admin")
        if request.method == "OPTIONS" and not is_admin:
            return _cors(web.Response(status=204))
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
            or (request.remote or "?")
        if _too_often(ip):
            if is_admin:
                return web.json_response({"error": "too_many"}, status=429)
            return _cors(web.json_response({"error": "too_many"}, status=429))
        try:
            if is_admin:
                return await handler(request)
            return _cors(await handler(request))
        except web.HTTPException:
            raise
        except Exception as ex:
            logging.error("кабинет: %s: %s", type(ex).__name__, ex)
            if is_admin:
                return web.json_response({"error": "server"}, status=500)
            return _cors(web.json_response({"error": "server"}, status=500))

    async def health(_request):
        return web.json_response({"ok": True})

    async def auth(request):
        from core.database import web_session_new
        try:
            body = await request.json()
        except Exception:
            body = {}
        source = "webapp" if body.get("initData") else "widget"
        who = (check_webapp(body.get("initData"))
               if source == "webapp" else check_widget(body.get("user") or body))
        if not who:
            return web.json_response({"error": "bad_signature"}, status=401)
        from core.database import upsert_user
        await upsert_user(who["id"], who["first_name"], who["username"])
        token = await web_session_new(who["id"], source, SESSION_DAYS)
        return web.json_response({"token": token, "days": SESSION_DAYS})

    async def session_user(request):
        """tg_id по токену сессии — или None, если сессии нет."""
        from core.database import web_session_user
        token = (request.headers.get("Authorization", "").replace("Bearer ", "").strip()
                 or request.query.get("token", ""))
        return await web_session_user(token)

    async def me(request):
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        return web.json_response(await profile(tg_id))

    async def qr(request):
        """QR-код ссылки подписки (PNG) — как кнопка QR в боте.
        Генерируем на сервере тем же qrcode, что и бот: ссылка
        подписки не уходит в сторонние QR-сервисы."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        data = await profile(tg_id)
        url = ((data.get("subscription") or {}).get("url") or "")
        if not url:
            return web.json_response({"error": "no_subscription"}, status=404)
        import asyncio
        from io import BytesIO

        def _make() -> bytes:
            import qrcode
            buf = BytesIO()
            qrcode.make(url).save(buf, format="PNG")
            return buf.getvalue()

        png = await asyncio.to_thread(_make)
        return web.Response(body=png, content_type="image/png",
                            headers={"Cache-Control": "no-store"})

    async def logout(request):
        from core.database import web_session_drop
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        await web_session_drop(token)
        return web.json_response({"ok": True})

    async def auth_password(request):
        """Вход по почте и паролю + капча. Выдаёт ту же сессию, что и Telegram."""
        from config import turnstile_keys
        from core.database import get_user_by_login_email, web_session_new
        try:
            body = await request.json()
        except Exception:
            body = {}
        email = _valid_email(body.get("email"))
        password = str(body.get("password") or "")
        if not email or not password:
            return web.json_response({"error": "bad_request"}, status=400)
        if not turnstile_keys()[1]:
            return web.json_response({"error": "captcha_not_configured"}, status=503)
        if _pw_locked(email):
            return web.json_response({"error": "too_many"}, status=429)
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
            or (request.remote or "?")
        if not await _turnstile_ok(str(body.get("captcha") or ""), ip):
            return web.json_response({"error": "captcha"}, status=403)
        row = await get_user_by_login_email(email)
        if not row or not row[1] or not check_secret(password, row[1]):
            _pw_fail_hit(email)
            try:
                from core.database import log_activity
                # tg_id известен, только если почта есть в базе; иначе 0.
                # Почту, пароль и хеш не пишем никогда.
                await log_activity(row[0] if row else 0, "ev:cabinet_login_failed",
                                   "вход в кабинет по паролю")
            except Exception:
                pass
            return web.json_response({"error": "bad_login"}, status=401)
        _pw_fail_clear(email)
        try:
            from core.database import log_activity
            await log_activity(row[0], "ev:cabinet_login", "вход в кабинет по паролю")
        except Exception:
            pass
        token = await web_session_new(row[0], "password", SESSION_DAYS)
        return web.json_response({"token": token, "days": SESSION_DAYS})

    async def auth_forgot(request):
        """Код сброса пароля: приходит человеку в Telegram. Почту не выдаём:
        ответ одинаковый, есть такая почта или нет."""
        from config import turnstile_keys
        from core.database import get_user_by_login_email, password_reset_new
        try:
            body = await request.json()
        except Exception:
            body = {}
        email = _valid_email(body.get("email"))
        if not email:
            return web.json_response({"error": "bad_request"}, status=400)
        if not turnstile_keys()[1]:
            return web.json_response({"error": "captcha_not_configured"}, status=503)
        key = "forgot:" + email
        if _pw_locked(key):
            return web.json_response({"error": "too_many"}, status=429)
        _pw_fail_hit(key)
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
            or (request.remote or "?")
        if not await _turnstile_ok(str(body.get("captcha") or ""), ip):
            return web.json_response({"error": "captcha"}, status=403)
        row = await get_user_by_login_email(email)
        if row and _bot is not None:
            import secrets
            code = f"{secrets.randbelow(900000) + 100000}"
            await password_reset_new(row[0], hash_secret(code), RESET_CODE_MINUTES)
            try:
                await _bot.send_message(
                    chat_id=row[0],
                    text=f"🔑 <b>Код для сброса пароля в кабинете Drebol VPN: {code}</b>\n\n"
                         f"Действует {RESET_CODE_MINUTES} минут. "
                         "Если это были не вы — просто не вводите его.",
                    parse_mode="HTML")
            except Exception as ex:
                logging.error("кабинет: не удалось отправить код сброса: %s", ex)
        return web.json_response({"ok": True})

    async def auth_reset(request):
        """Новый пароль по коду из Telegram. Старые сессии закрываются."""
        from core.database import (get_user_by_login_email, password_reset_get,
                                   password_reset_use, set_password_hash,
                                   web_sessions_drop_user)
        try:
            body = await request.json()
        except Exception:
            body = {}
        email = _valid_email(body.get("email"))
        code = str(body.get("code") or "").strip()
        password = str(body.get("password") or "")
        if not email or not code or len(password) < 8 or len(password) > 128:
            return web.json_response({"error": "bad_request"}, status=400)
        row = await get_user_by_login_email(email)
        if not row:
            return web.json_response({"error": "bad_code"}, status=401)
        reset = await password_reset_get(row[0])
        if not reset or not check_secret(code, reset[1]):
            return web.json_response({"error": "bad_code"}, status=401)
        await password_reset_use(reset[0])
        await set_password_hash(row[0], hash_secret(password))
        await web_sessions_drop_user(row[0])
        return web.json_response({"ok": True})

    async def profile_email(request):
        """Сменить почту для входа. Сессия уже доказывает, кто ты:
        через Telegram или по паролю."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        email = _valid_email(body.get("email"))
        if not email:
            return web.json_response({"error": "bad_email"}, status=400)
        from core.database import get_user_by_login_email, set_login_email
        other = await get_user_by_login_email(email)
        if other and other[0] != tg_id:
            return web.json_response({"error": "email_taken"}, status=409)
        if not await set_login_email(tg_id, email):
            return web.json_response({"error": "email_taken"}, status=409)
        return web.json_response({"ok": True, "email": email})

    async def profile_password(request):
        """Задать или сменить пароль. Если пароль уже есть — нужен текущий.
        Чужие сессии после смены закрываются, своя остаётся."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        current = str(body.get("current") or "")
        password = str(body.get("password") or "")
        if len(password) < 8 or len(password) > 128:
            return web.json_response({"error": "bad_password"}, status=400)
        from core.database import (get_login_info, get_password_hash,
                                   set_password_hash, web_sessions_drop_user)
        _, has_password = await get_login_info(tg_id)
        if has_password:
            stored = await get_password_hash(tg_id)
            if not stored or not check_secret(current, stored):
                return web.json_response({"error": "bad_current"}, status=401)
        await set_password_hash(tg_id, hash_secret(password))
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        await web_sessions_drop_user(tg_id, keep_token=token)
        return web.json_response({"ok": True})

    async def device_delete(request):
        """Человек отключает своё устройство — то же, что кнопка в боте."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        ref = str(body.get("hwid") or "")
        if not ref:
            return web.json_response({"error": "no_device"}, status=400)
        from paidsub.storage import add_history, get_paid_sub_by_tg_id
        from services.panel import delete_client_hwid, get_client_hwids, resolve_hwid
        row = await get_paid_sub_by_tg_id(tg_id)
        if not row:
            return web.json_response({"error": "no_sub"}, status=404)
        hwid_id = await resolve_hwid(row[2], ref)
        if hwid_id is None:
            return web.json_response({"error": "already_gone"}, status=404)
        model = ""
        hw = await get_client_hwids(row[2])
        if hw.get("ok"):
            for d in hw.get("items", []):
                if str(d.get("id")) == str(hwid_id):
                    model = d.get("deviceModel") or d.get("platform") or ""
        res = await delete_client_hwid(row[2], hwid_id)
        if not res.get("success"):
            return web.json_response({"error": "panel"}, status=502)
        await add_history(tg_id, "device_removed",
                          f"Устройство отключено из кабинета: {model or hwid_id}")
        return web.json_response({"ok": True})

    async def reissue(request):
        """Перевыпуск ключа — та же операция, что кнопка «Новый ключ» в боте.

        Старая ссылка перестаёт работать на всех устройствах, поэтому
        фронт спрашивает подтверждение до запроса.
        """
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from paidsub.storage import add_history, get_paid_sub_by_tg_id, update_paid_sub_field
        from services.panel import get_client_info, reissue_subscription
        row = await get_paid_sub_by_tg_id(tg_id)
        if not row:
            return web.json_response({"error": "no_sub"}, status=404)
        status = row[11] if len(row) > 11 else "active"
        info = await get_client_info(row[2])
        enabled = info.get("enabled", True) if info.get("success") else True
        if status not in ("active", "renewal") or not enabled:
            return web.json_response({"error": "not_available"}, status=409)
        res = await reissue_subscription(row[2])
        if not res.get("success"):
            return web.json_response({"error": "panel"}, status=502)
        await update_paid_sub_field(row[0], "uuid", res["new_uuid"])
        await update_paid_sub_field(row[0], "sub_id", res["sub_id"])
        await update_paid_sub_field(row[0], "sub_url", res["sub_url"])
        await add_history(tg_id, "key_reissued", "Ключ перевыпущен из кабинета")
        from config import sub_url_for_display
        return web.json_response(
            {"ok": True, "url": sub_url_for_display(res["sub_url"])})

    async def renew_options(request):
        """Тарифы с посчитанными для этого человека ценами, висящий
        промокод из бота и неоплаченный счёт, если такой уже есть."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        from core.database import get_active_payment, list_tariffs
        from paidsub.storage import get_paid_sub_by_tg_id
        from paidsub.time_parser import fmt_duration
        row = await get_paid_sub_by_tg_id(tg_id)
        if not row:
            return web.json_response({"error": "no_sub"}, status=404)
        tariffs = await list_tariffs(only_active=True)
        if not tariffs:
            return web.json_response({"error": "no_tariffs"}, status=409)
        out = []
        quote0 = None
        for t in tariffs:
            q = await _renew_quote(tg_id, t)
            if quote0 is None:
                quote0 = q
            out.append({"id": t[0], "name": fmt_duration(q["seconds"]),
                        "period": fmt_duration(q["seconds"]),
                        "price": q["price"]})
        pending = await get_active_payment(tg_id, "platega")
        return web.json_response({
            "tariffs": out,
            "devices": {"count": quote0["extra"], "price": quote0["dev_price"]},
            "promo": ({"code": quote0["promo_code"],
                       "percent": quote0["promo_percent"]}
                      if quote0["promo_code"] else None),
            "pending": ({"id": pending[0], "amount": pending[4],
                         "url": pending[8], "period": pending[5]}
                        if pending and pending[8] else None),
        })

    async def payments_more(request):
        """История платежей шире первых десяти из профиля: страница
        догружает её кнопкой «Показать ещё» растущим лимитом."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            limit = int(request.query.get("limit", "10"))
        except Exception:
            limit = 10
        limit = max(10, min(100, limit))
        from core.database import user_payments
        rows, cnt, total = await user_payments(tg_id, limit)
        return web.json_response({
            "payments": [{"id": r[0], "provider": r[1] or "", "amount": r[2],
                          "status": r[3], "date": str(r[4] or "")[:16],
                          "promo": r[5] or ""} for r in rows],
            "payments_total": {"count": cnt, "sum": total},
        })

    async def info(request):
        """Раздел «Инфо» в кабинете — то же, что экран «ℹ️ Инфо» в боте
        (handlers/user.py: handle_info/handle_how_to/handle_about/
        handle_prices): как подключиться, о сервисе, цены. Только чтение;
        подписка не нужна — цены и инструкции нужны и до оформления."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from config import load_config
        from core.database import list_tariffs
        from paidsub.time_parser import fmt_duration
        from web.site_deploy import doc_url
        cfg = load_config()
        trial = int(cfg.get("paid_trial_period") or 0)
        tariffs = await list_tariffs(only_active=True)
        out_tariffs = []
        base = None
        for _id, _name, period, price, _a, _s in tariffs:
            per_month = (int(price) / (int(period) / 2592000)
                         if period else None)
            if base is None and per_month:
                base = per_month
            saving = None
            if base and per_month and per_month < base * 0.97:
                saving = round((1 - per_month / base) * 100)
            out_tariffs.append({
                "id": _id, "period": fmt_duration(period),
                "price": int(price),
                "per_month": round(per_month) if per_month else None,
                "saving_pct": saving,
            })
        try:
            from handlers.support import support_bot_url
            support_url = support_bot_url()
        except Exception:
            support_url = ""
        return web.json_response({
            "trial": ({"seconds": trial, "text": fmt_duration(trial)}
                      if trial else None),
            "tariffs": out_tariffs,
            "fallback_price": int(cfg.get("paid_price") or 0) or None,
            "devices": int(cfg.get("paid_preset_hwid") or 0),
            "device_price": int(cfg.get("device_price") or 0),
            "traffic_gb": int(cfg.get("paid_preset_traffic") or 0),
            "apps": _INFO_APPS,
            "docs": {"privacy": doc_url("privacy"),
                     "terms": doc_url("terms")},
            "support_url": support_url,
            "channel_url": cfg.get("channel_url") or "",
        })

    async def promo_apply(request):
        """Ввод промокода в кабинете — та же валидация, что в боте.
        Код сохраняется как pending: скидку подхватит _renew_quote,
        а при оплате промокод отметится использованным, как в боте."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        try:
            body = await request.json()
        except Exception:
            body = {}
        code = str(body.get("code") or "").strip()
        if not code or len(code) > 64:
            return web.json_response({"error": "bad_code"}, status=400)
        from paidsub.handlers import validate_promo
        from paidsub.storage import get_paid_sub_by_tg_id, update_paid_sub_field
        row = await get_paid_sub_by_tg_id(tg_id)
        if not row:
            return web.json_response({"error": "no_sub"}, status=404)
        promo, err = await validate_promo(code, tg_id)
        if not promo:
            return web.json_response(
                {"error": "promo_invalid", "message": err or ""}, status=422)
        await update_paid_sub_field(row[0], "pending_promo", promo[1])
        return web.json_response(
            {"ok": True, "code": promo[1], "percent": int(promo[2])})

    async def promo_remove(request):
        """Снять висящий промокод, чтобы продление считалось без скидки."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from paidsub.storage import get_paid_sub_by_tg_id, update_paid_sub_field
        row = await get_paid_sub_by_tg_id(tg_id)
        if row:
            await update_paid_sub_field(row[0], "pending_promo", None)
        return web.json_response({"ok": True})

    async def renew(request):
        """Создаёт счёт за продление — тот же счёт Platega, что и в боте.
        Повторное нажатие на тот же тариф не плодит счета: возвращается
        уже созданная ссылка. Подтверждение — вебхуком, опрос — страховка."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            tariff_id = int(body.get("tariff_id") or 0)
        except (TypeError, ValueError):
            tariff_id = 0
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        from core.database import (add_payment, get_active_payment, get_tariff,
                              get_user_info, set_payment_external_id,
                              set_payment_status)
        from paidsub.storage import get_paid_sub_by_tg_id
        import services.platega_api as pg
        row = await get_paid_sub_by_tg_id(tg_id)
        if not row:
            return web.json_response({"error": "no_sub"}, status=404)
        tariff = await get_tariff(tariff_id) if tariff_id else None
        if not tariff or not tariff[4]:
            return web.json_response({"error": "bad_tariff"}, status=400)
        if not pg.is_configured():
            return web.json_response({"error": "pay_unavailable"}, status=503)
        q = await _renew_quote(tg_id, tariff)
        existing = await get_active_payment(tg_id, "platega")
        if (existing and existing[4] == q["price"]
                and existing[5] == q["seconds"] and existing[8]
                and (len(existing) < 12 or existing[11] == q["extra"])):
            return web.json_response({"payment_id": existing[0],
                                      "url": existing[8],
                                      "amount": existing[4], "reused": True})
        user = await get_user_info(tg_id)
        # После оплаты клиент попадает на страницу «спасибо» на сайте,
        # а через 5 секунд — в Telegram-бота. Редиректы задаются прямо
        # в счёте. Нет домена — возвращаемся в кабинет, как раньше.
        from web.site_deploy import pay_redirect_urls
        urls = pay_redirect_urls()
        cabinet_url = ""
        try:
            from web import site_deploy as site
            cabinet_url = (site.cabinet_link() or "") + "/payments"
        except Exception:
            cabinet_url = ""
        # строку создаём ДО запроса к платёжке: её id едет в payload,
        # а по payload колбэк находит счёт обратно
        pid = await add_payment(
            tg_id, "platega", None, q["price"], q["seconds"],
            "", promo_code=q["promo_code"], kind=q["kind"],
            extra=q["extra"])
        res = await pg.create_payment(
            amount=q["price"],
            description=f"Подписка Drebol VPN · {q['name']} · {tg_id}",
            tg_id=tg_id, username=user[2] if user else None,
            order_id=f"drebol-{pid}",
            success_url=urls.get("success") or cabinet_url or None,
            fail_url=urls.get("fail") or cabinet_url or None,
            back_url=urls.get("back") or cabinet_url or None)
        if not res.get("ok"):
            logging.error("кабинет: счёт Platega не создан для %s: %s",
                          tg_id, res.get("error"))
            await set_payment_status(pid, "error", res.get("error"))
            return web.json_response({"error": "pay_failed"}, status=502)
        await set_payment_external_id(pid, res["payment_id"], res["url"])
        return web.json_response({"payment_id": pid, "url": res["url"],
                                  "amount": q["price"]})

    # ── Получение первой подписки ────────────────────────────────────────

    async def buy_options(request):
        """Тарифы и пробный период для человека без подписки — то же,
        что экран «🎁 Получить подписку» в боте (handle_request_sub +
        handle_renew_sub/handle_pay_invoice с row=None): пробный — по
        пресетам, покупка — тарифы с ценой из _renew_quote (устройств
        у нового юзера нет — devices=0, как в боте)."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        from config import load_config
        from core.database import get_active_payment, list_tariffs
        from paidsub.handlers import _paid_presets_ready
        from paidsub.storage import (get_paid_sub_by_tg_id,
                                     get_pending_request)
        from paidsub.time_parser import fmt_duration
        if await get_paid_sub_by_tg_id(tg_id):
            return web.json_response({"error": "has_sub"}, status=409)
        cfg = load_config()
        tariffs = await list_tariffs(only_active=True)
        if not tariffs:
            return web.json_response({"error": "no_tariffs"}, status=409)
        trial_sec = int(cfg.get("paid_trial_period") or 0)
        quotes = []
        best = None
        for t in tariffs:
            q = await _renew_quote(tg_id, t)
            per_month = (q["price"] / (q["seconds"] / 2592000)
                         if q["seconds"] else None)
            quotes.append((t, q, per_month))
            if per_month and (best is None or per_month < best):
                best = per_month
        out = []
        for t, q, per_month in quotes:
            out.append({"id": t[0], "name": fmt_duration(q["seconds"]),
                        "period": fmt_duration(q["seconds"]),
                        "price": q["price"],
                        "per_month": round(per_month) if per_month else None,
                        "best": bool(best and per_month
                                     and per_month == best
                                     and len(tariffs) > 1)})
        pending = await get_active_payment(tg_id, "platega")
        return web.json_response({
            "trial": ({"seconds": trial_sec, "text": fmt_duration(trial_sec)}
                      if trial_sec > 0 else None),
            "tariffs": out,
            "presets_ready": bool(_paid_presets_ready(cfg)),
            "auto_trial": bool(cfg.get("auto_approve_trial", False)),
            "pending_request": bool(await get_pending_request(tg_id)),
            "pending": ({"id": pending[0], "amount": pending[4],
                         "url": pending[8], "period": pending[5]}
                        if pending and pending[8] else None),
        })

    async def trial_request(request):
        """Запрос пробного периода — зеркало handle_request_sub из бота:
        пресеты не готовы — 409, заявка уже висит — 200 pending,
        авто-одобрение — триал сразу той же svc.create_paid_sub, иначе
        заявка админу с кнопками одобрения и антифрод-предупреждениями."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        from config import ADMIN_ID, load_config
        from core.database import get_user_info
        from paidsub.handlers import _paid_presets_ready
        from paidsub.storage import (add_history, add_request,
                                     get_paid_sub_by_tg_id,
                                     get_pending_request, resolve_request)
        from paidsub.time_parser import fmt_duration
        if await get_paid_sub_by_tg_id(tg_id):
            return web.json_response({"error": "has_sub"}, status=409)
        cfg = load_config()
        trial_sec = int(cfg.get("paid_trial_period") or 0)
        if not _paid_presets_ready(cfg) or trial_sec <= 0:
            # 0 секунд — не триал: в боте здесь создался бы триал на 0 сек
            return web.json_response({"error": "presets_not_ready"},
                                     status=409)
        if await get_pending_request(tg_id):
            return web.json_response({"ok": True, "status": "pending"})
        if cfg.get("auto_approve_trial", False):
            from paidsub import service as _svc
            try:
                res = await _svc.create_paid_sub(tg_id, trial=True, bot=_bot)
            except Exception as ex:
                logging.error("кабинет: авто-триал %s: %s", tg_id, ex)
                return web.json_response({"error": "panel_failed"},
                                         status=502)
            if not res.get("ok"):
                return web.json_response(
                    {"error": "panel_failed",
                     "details": str(res.get("error") or "")}, status=502)
            await add_request(tg_id)
            await resolve_request(tg_id, "approved")
            await add_history(tg_id, "trial_approved", "Авто-одобрение")
            notified = False
            if _bot is not None:
                from config import sub_url_for_display
                sub_link = sub_url_for_display(res["sub_url"])
                try:
                    await _bot.send_message(
                        chat_id=tg_id,
                        text=("🎉 <b>Подписка готова!</b>\n\n"
                              f"<blockquote>📅 Действует до: <b>{res['expire'][:16]}</b></blockquote>\n\n"
                              "🔑 <b>Ссылка для подключения</b>\n"
                              f"<code>{sub_link}</code>\n\n"
                              "<i>Нажмите на ссылку — она скопируется — и вставьте её в INCY.</i>"),
                        parse_mode="HTML")
                    notified = True
                except Exception as ex:
                    logging.error("кабинет: авто-триал notify %s: %s",
                                  tg_id, ex)
            bonus_error = None
            if _bot is not None:
                try:
                    from types import SimpleNamespace
                    from paidsub.handlers import _process_referral_bonus
                    await _process_referral_bonus(
                        tg_id, SimpleNamespace(bot=_bot))
                except Exception as ex:
                    logging.error("кабинет: авто-триал bonus %s: %s",
                                  tg_id, ex)
                    bonus_error = f"{type(ex).__name__}: {ex}"
            if _bot is not None:
                try:
                    from core.log_channel import send_log
                    from html import escape as _esc
                    user = await get_user_info(tg_id)
                    uname = _esc(f"@{user[2]}" if user and user[2]
                                 else f"id{tg_id}")
                    await send_log(
                        _bot,
                        f"⚡ Авто-триал выдан: {_esc(str((user[1] if user else None) or tg_id))} "
                        f"({uname}) · <code>{tg_id}</code>")
                except Exception as ex:
                    logging.error("кабинет: авто-триал send_log %s: %s",
                                  tg_id, ex)
            out = {"ok": True, "status": "trial", "notified": notified,
                   "subscription": {"id": res["sub_id"],
                                    "email": res["email"],
                                    "expire": res["expire"]}}
            if bonus_error:
                out["referral_bonus_error"] = bonus_error
            return web.json_response(out)
        # Ручное одобрение: заявка + сообщение админу, как в боте.
        await add_request(tg_id)
        admin_notified = False
        if _bot is not None:
            try:
                from paidsub.handlers import _esc_name
                from paidsub.keyboards import approve_keyboard
                user = await get_user_info(tg_id)
                first = user[1] if user else None
                uname = f"@{user[2]}" if user and user[2] else f"id{tg_id}"
                hwid = int(cfg.get("paid_preset_hwid", 0) or 0)
                traf_raw = int(cfg.get("paid_preset_traffic", 0) or 0)
                hwid_str = str(hwid) if hwid > 0 else "безлимит"
                traf_str = f"{traf_raw} ГБ" if traf_raw > 0 else "безлимит"
                fraud_block = ""
                try:
                    from features.fraud import pre_trial_check
                    warns = await pre_trial_check(tg_id)
                    if warns:
                        fraud_block = ("\n🕵 <b>Антифрод:</b>\n"
                                       + "\n".join(
                                           f"· {html.escape(w)}"
                                           for w in warns)
                                       + "\n")
                except Exception:
                    pass
                await _bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(f"🆕 <b>Запрос на подписку</b>\n\n"
                          f'👤 <a href="tg://user?id={tg_id}">{_esc_name(first, tg_id)}</a> '
                          f"({_esc_name(uname, tg_id)})\n"
                          f"🆔 TG ID: <code>{tg_id}</code>\n"
                          f"{fraud_block}\n"
                          f"<b>Параметры подписки:</b>\n"
                          f"🆓 Пробный период: <b>{fmt_duration(trial_sec)}</b>\n"
                          f"🖥 Лимит устройств: <b>{hwid_str}</b>\n"
                          f"📶 Трафик: <b>{traf_str}</b>\n\n"
                          "Одобрить пробную подписку?"),
                    parse_mode="HTML",
                    reply_markup=approve_keyboard(tg_id))
                admin_notified = True
            except Exception as ex:
                logging.error("кабинет: заявка на триал notify %s: %s",
                              tg_id, ex)
        return web.json_response({"ok": True, "status": "requested",
                                  "admin_notified": admin_notified})

    async def buy(request):
        """Первая покупка — тот же счёт Platega, что продление в боте
        (handle_pay_invoice с row=None): тариф + цена из _renew_quote
        (устройств у нового юзера нет), подтверждение — тем же вебхуком,
        его код не трогается. Повторное нажатие на тот же тариф не плодит
        счета: возвращается уже созданная ссылка."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            tariff_id = int(body.get("tariff_id") or 0)
        except (TypeError, ValueError):
            tariff_id = 0
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        from core.database import (add_payment, get_active_payment,
                                   get_tariff, get_user_info,
                                   set_payment_external_id,
                                   set_payment_status)
        from paidsub.storage import get_paid_sub_by_tg_id
        import services.platega_api as pg
        if await get_paid_sub_by_tg_id(tg_id):
            return web.json_response({"error": "has_sub"}, status=409)
        tariff = await get_tariff(tariff_id) if tariff_id else None
        if not tariff or not tariff[4]:
            return web.json_response({"error": "bad_tariff"}, status=400)
        if not pg.is_configured():
            return web.json_response({"error": "pay_unavailable"}, status=503)
        q = await _renew_quote(tg_id, tariff)
        existing = await get_active_payment(tg_id, "platega")
        if (existing and existing[4] == q["price"]
                and existing[5] == q["seconds"] and existing[8]
                and (len(existing) < 12 or existing[11] == q["extra"])
                and (len(existing) < 13 or not existing[12])):
            return web.json_response({"payment_id": existing[0],
                                      "url": existing[8],
                                      "amount": existing[4], "reused": True})
        user = await get_user_info(tg_id)
        from web.site_deploy import pay_redirect_urls
        urls = pay_redirect_urls()
        cabinet_url = ""
        try:
            from web import site_deploy as site
            cabinet_url = (site.cabinet_link() or "") + "/payments"
        except Exception:
            cabinet_url = ""
        # строку создаём ДО запроса к платёжке: её id едет в payload,
        # а по payload колбэк находит счёт обратно
        pid = await add_payment(
            tg_id, "platega", None, q["price"], q["seconds"],
            "", promo_code=q["promo_code"], kind=q["kind"],
            extra=q["extra"])
        res = await pg.create_payment(
            amount=q["price"],
            description=f"Подписка Drebol VPN · {q['name']} · {tg_id}",
            tg_id=tg_id, username=user[2] if user else None,
            order_id=f"drebol-{pid}",
            success_url=urls.get("success") or cabinet_url or None,
            fail_url=urls.get("fail") or cabinet_url or None,
            back_url=urls.get("back") or cabinet_url or None)
        if not res.get("ok"):
            logging.error("кабинет: счёт Platega не создан (покупка) для %s: %s",
                          tg_id, res.get("error"))
            await set_payment_status(pid, "error", res.get("error"))
            return web.json_response({"error": "pay_failed"}, status=502)
        await set_payment_external_id(pid, res["payment_id"], res["url"])
        return web.json_response({"payment_id": pid, "url": res["url"],
                                  "amount": q["price"]})

    async def gift_options(request):
        """Тарифы для подарка — те же, что в боте на экране gift_pick:
        срок и цена со скидкой висящего промокода дарителя, без устройств.
        Своя подписка для подарка не нужна, как и в боте."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        from core.database import list_tariffs
        from paidsub.time_parser import fmt_duration
        tariffs = await list_tariffs(only_active=True)
        if not tariffs:
            return web.json_response({"error": "no_tariffs"}, status=409)
        out = []
        promo = None
        for t in tariffs:
            q = await _gift_quote(tg_id, t)
            if promo is None and q["promo_code"]:
                promo = {"code": q["promo_code"],
                         "percent": q["promo_percent"]}
            out.append({"id": t[0], "name": fmt_duration(q["seconds"]),
                        "period": fmt_duration(q["seconds"]),
                        "price": q["price"]})
        return web.json_response({"tariffs": out, "promo": promo})

    async def gift_resolve(request):
        """Получатель подарка — проверка, как в боте перед оплатой:
        @ник или TG ID, себе и людям из ЧС дарить нельзя."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        try:
            res = await _resolve_gift_recipient(tg_id, body.get("target"))
        except ValueError as ex:
            code = str(ex)
            status = {"bad_target": 400, "self_gift": 400,
                      "user_not_found": 404, "blocked": 403,
                      "no_bot": 503}.get(code, 400)
            return web.json_response({"error": code}, status=status)
        return web.json_response(res)

    async def gift(request):
        """Счёт за подарок — тот же счёт Platega, что в боте
        (handle_pay_invoice с gift_tg_id): платит даритель, подписка
        откроется у получателя, подтверждение — тем же вебхуком, его
        код не трогается. Повторное нажатие на тот же тариф и того же
        получателя не плодит счета: возвращается уже созданная ссылка."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            tariff_id = int(body.get("tariff_id") or 0)
            gift_tg = int(body.get("tg_id") or 0)
        except (TypeError, ValueError):
            return web.json_response({"error": "bad_params"}, status=400)
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        if not gift_tg or gift_tg == tg_id:
            return web.json_response({"error": "self_gift"}, status=400)
        if await is_blacklisted(gift_tg):
            return web.json_response({"error": "blocked_recipient"}, status=403)
        from core.database import (add_payment, get_active_payment, get_tariff,
                              get_user_info, set_payment_external_id,
                              set_payment_status)
        import services.platega_api as pg
        tariff = await get_tariff(tariff_id) if tariff_id else None
        if not tariff or not tariff[4]:
            return web.json_response({"error": "bad_tariff"}, status=400)
        if not pg.is_configured():
            return web.json_response({"error": "pay_unavailable"}, status=503)
        q = await _gift_quote(tg_id, tariff)
        existing = await get_active_payment(tg_id, "platega")
        if (existing and existing[4] == q["price"]
                and existing[5] == q["seconds"] and existing[8]
                and (len(existing) < 12 or existing[11] == 0)
                and (len(existing) < 13 or (existing[12] or 0) == gift_tg)):
            return web.json_response({"payment_id": existing[0],
                                      "url": existing[8],
                                      "amount": existing[4], "reused": True})
        user = await get_user_info(tg_id)
        # Имя получателя — только для описания счёта, как gift_name в боте.
        try:
            rcpt = await _resolve_gift_recipient(tg_id, gift_tg)
            gift_name = rcpt["display"]
        except ValueError:
            gift_name = f"id{gift_tg}"
        from web.site_deploy import pay_redirect_urls
        urls = pay_redirect_urls()
        cabinet_url = ""
        try:
            from web import site_deploy as site
            cabinet_url = (site.cabinet_link() or "") + "/payments"
        except Exception:
            cabinet_url = ""
        # строку создаём ДО запроса к платёжке: её id едет в payload,
        # а по payload колбэк находит счёт обратно
        pid = await add_payment(
            tg_id, "platega", None, q["price"], q["seconds"],
            "", promo_code=q["promo_code"], kind="period", extra=0,
            gift_tg_id=gift_tg)
        res = await pg.create_payment(
            amount=q["price"],
            description=f"Подписка Drebol VPN · 🎁 Подарок для {gift_name}",
            tg_id=tg_id, username=user[2] if user else None,
            order_id=f"drebol-{pid}",
            success_url=urls.get("success") or cabinet_url or None,
            fail_url=urls.get("fail") or cabinet_url or None,
            back_url=urls.get("back") or cabinet_url or None)
        if not res.get("ok"):
            logging.error("кабинет: счёт Platega за подарок не создан для %s: %s",
                          tg_id, res.get("error"))
            await set_payment_status(pid, "error", res.get("error"))
            return web.json_response({"error": "pay_failed"}, status=502)
        await set_payment_external_id(pid, res["payment_id"], res["url"])
        return web.json_response({"payment_id": pid, "url": res["url"],
                                  "amount": q["price"]})

    async def devices_buy(request):
        """Докупка мест для устройств отдельным счётом — как кнопка
        «Добавить место» в боте: платёж kind="devices", подтверждение
        вебхуком начислит места через apply_devices_payment."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            count = int(body.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        from features.blacklist import is_blacklisted
        if await is_blacklisted(tg_id):
            return web.json_response({"error": "blocked"}, status=403)
        from config import load_config
        from core.database import (add_payment, get_active_payment, get_user_info,
                                   set_payment_external_id, set_payment_status)
        from paidsub.storage import base_hwid, get_paid_sub_by_tg_id
        import services.platega_api as pg
        row = await get_paid_sub_by_tg_id(tg_id)
        if not row:
            return web.json_response({"error": "no_sub"}, status=404)
        cfg = load_config()
        price = int(cfg.get("device_price", 0) or 0)
        max_extra = int(cfg.get("device_max_extra") or 5)
        bought = int(row[18] or 0) if len(row) > 18 else 0
        limit_now = int(row[8] or 0)
        if price <= 0 or not limit_now or not base_hwid(limit_now, bought):
            return web.json_response({"error": "unavailable"}, status=409)
        left = max(0, max_extra - bought)
        if left <= 0:
            return web.json_response({"error": "max_reached"}, status=409)
        count = max(1, min(count, left))
        amount = price * count
        if not pg.is_configured():
            return web.json_response({"error": "pay_unavailable"}, status=503)
        existing = await get_active_payment(tg_id, "platega")
        if (existing and existing[4] == amount and existing[8]
                and len(existing) > 11 and existing[10] == "devices"
                and existing[11] == count):
            return web.json_response({"payment_id": existing[0],
                                      "url": existing[8],
                                      "amount": existing[4], "reused": True})
        user = await get_user_info(tg_id)
        from web.site_deploy import pay_redirect_urls
        urls = pay_redirect_urls()
        cabinet_url = ""
        try:
            from web import site_deploy as site
            cabinet_url = (site.cabinet_link() or "") + "/payments"
        except Exception:
            cabinet_url = ""
        pid = await add_payment(
            tg_id, "platega", None, amount, 0,
            "", promo_code=None, kind="devices", extra=count)
        res = await pg.create_payment(
            amount=amount,
            description=f"Доп. устройства Drebol VPN · {count} · {tg_id}",
            tg_id=tg_id, username=user[2] if user else None,
            order_id=f"drebol-{pid}",
            success_url=urls.get("success") or cabinet_url or None,
            fail_url=urls.get("fail") or cabinet_url or None,
            back_url=urls.get("back") or cabinet_url or None)
        if not res.get("ok"):
            logging.error("кабинет: счёт за устройства не создан для %s: %s",
                          tg_id, res.get("error"))
            await set_payment_status(pid, "error", res.get("error"))
            return web.json_response({"error": "pay_failed"}, status=502)
        await set_payment_external_id(pid, res["payment_id"], res["url"])
        return web.json_response({"payment_id": pid, "url": res["url"],
                                  "amount": amount})

    async def payment_status(request):
        """Статус своего счёта — его опрашивает страница, пока ждёт
        подтверждения. Чужие счета не отдаём: только свои."""
        tg_id = await session_user(request)
        if not tg_id:
            return web.json_response({"error": "no_session"}, status=401)
        try:
            pid = int(request.query.get("id") or 0)
        except (TypeError, ValueError):
            pid = 0
        from core.database import get_payment
        p = await get_payment(pid) if pid else None
        if not p or p[1] != tg_id:
            return web.json_response({"error": "no_payment"}, status=404)
        return web.json_response({"id": p[0], "status": p[7], "amount": p[4],
                                  "url": p[8], "period": p[5]})

    async def platega_webhook(request):
        """Колбэк Platega: мгновенное подтверждение оплаты.

        Platega шлёт POST с заголовками X-MerchantId / X-Secret (те же,
        что в настройках бота). Тело: id (uuid уведомления), status,
        paymentMethod, payload. Счёт ищем по payload — туда мы кладём
        «drebol-<id строки в базе>». Статусы: CONFIRMED — засчитать счёт,
        CANCELED — пометить отменённым, CHARGEBACKED / DISPUTED — возврат,
        PARTIALLY_REFUNDED — учесть частичный возврат.
        Если колбэк придёт раньше опроса или дважды — подтверждение
        идемпотентно: засчитываются только счета в статусе pending.
        Возвраты обрабатываются ВСЕГДА, а не только для pending: возврат
        в кабинете Platega приходит уже после подтверждения, и прежний
        ранний выход «не pending — игнорировать» молча терял его —
        платёж оставался «оплаченным» и шёл в чистую прибыль.
        """
        import services.platega_api as pg
        if not pg.verify_callback(request.headers):
            logging.warning("кабинет: колбэк Platega с неверными заголовками")
            return web.json_response({"error": "bad_auth"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "bad_json"}, status=400)
        status = (body.get("status") or "").upper()
        payload = str(body.get("payload") or "")
        if status not in ("CONFIRMED", "CANCELED", "CHARGEBACKED",
                          "PARTIALLY_REFUNDED", "DISPUTED") or not payload:
            return web.json_response({"ok": True, "ignored": True})
        if not payload.startswith("drebol-"):
            logging.warning("кабинет: колбэк Platega с чужим payload %s", payload)
            return web.json_response({"ok": True, "unknown": True})
        try:
            pay_row_id = int(payload.split("-", 1)[1])
        except (TypeError, ValueError):
            return web.json_response({"ok": True, "unknown": True})
        from core.database import (
            get_payment, get_payment_by_external, set_payment_status,
            set_partial_refunded,
        )
        row = await get_payment(pay_row_id)
        if not row:
            logging.warning("кабинет: колбэк Platega на неизвестный счёт %s", payload)
            return web.json_response({"ok": True, "unknown": True})
        if status == "CANCELED":
            # отмена — только пока счёт ждёт оплаты; оплаченный счёт
            # отменённым уже не станет
            if row[7] == "pending":
                await set_payment_status(pay_row_id, "canceled")
            return web.json_response({"ok": True})
        if status in ("CHARGEBACKED", "DISPUTED"):
            if _bot is None:
                logging.error("кабинет: колбэк Platega о возврате, а бот не подключён к API")
                return web.json_response({"error": "no_bot"}, status=500)
            from types import SimpleNamespace
            from handlers.payments import finalize_refund
            await finalize_refund(SimpleNamespace(bot=_bot), pay_row_id)
            return web.json_response({"ok": True})
        if status == "PARTIALLY_REFUNDED":
            # частичный возврат — тоже после подтверждения; уже полностью
            # возвращённый счёт не трогаем
            if row[7] not in ("refunded", "chargebacked"):
                refunded = body.get("refundedAmount")
                if refunded is not None:
                    try:
                        await set_partial_refunded(pay_row_id, int(float(refunded)))
                    except (TypeError, ValueError):
                        pass
            return web.json_response({"ok": True})
        # CONFIRMED — только для pending: подтверждение идемпотентно,
        # повторный колбэк по оплаченному счёту просто игнорируется
        if row[7] != "pending":
            return web.json_response({"ok": True, "already": True})
        if _bot is None:
            logging.error("кабинет: колбэк Platega, а бот не подключён к API")
            return web.json_response({"error": "no_bot"}, status=500)
        p = await get_payment_by_external(row[3]) if row[3] else None
        if not p:
            logging.warning("кабинет: колбэк Platega, счёт %s без external_id", payload)
            return web.json_response({"ok": True, "unknown": True})
        from handlers.payments import confirm_provider_payment
        await confirm_provider_payment(_bot, p)
        return web.json_response({"ok": True})

    async def admin_page_handler(_request):
        """Страница веб-админки на самом API-сервере — запасной путь
        (SSH-туннель), когда сайт недоступен. Основной путь — /admin/
        на сайте, куда страницу заливает deploy()."""
        from web.admin_page import admin_page
        username = ""
        try:
            username = getattr(_bot, "username", "") or ""
        except Exception:
            username = ""
        return web.Response(text=admin_page(username),
                            content_type="text/html")

    app = web.Application(middlewares=[web.middleware(guard)])
    # Веб-админка (фаза 1): подприложение /api/admin/* со своими
    # правилами CORS/сессий/CSRF — см. web/admin_api.py.
    from web.admin_api import build_admin_app
    admin_app = build_admin_app()
    # Фаза 3: узлы/панель, логи, синхронизации, сайт, бэкап, ЧС, фрод.
    # Пути в admin_infra.register — относительные, без /api/admin.
    from web.admin_infra import register as _register_admin_infra
    _register_admin_infra(admin_app)
    app.add_subapp("/api/admin", admin_app)
    # Токен-вход Muse по секретной ссылке — ДО хвостового /admin/{tail:.*},
    # иначе страница админки перехватит адрес.
    from web.admin_console import register_top as _register_console_top
    _register_console_top(app)
    app.router.add_get("/admin/", admin_page_handler)
    app.router.add_get("/admin/{tail:.*}", admin_page_handler)
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/auth", auth)
    app.router.add_post("/api/auth/password", auth_password)
    app.router.add_post("/api/auth/forgot", auth_forgot)
    app.router.add_post("/api/auth/reset", auth_reset)
    app.router.add_post("/api/profile/email", profile_email)
    app.router.add_post("/api/profile/password", profile_password)
    app.router.add_get("/api/me", me)
    app.router.add_get("/api/info", info)
    app.router.add_get("/api/qr", qr)
    app.router.add_post("/api/logout", logout)
    app.router.add_post("/api/device/delete", device_delete)
    app.router.add_post("/api/reissue", reissue)
    app.router.add_get("/api/renew-options", renew_options)
    app.router.add_get("/api/payments", payments_more)
    app.router.add_post("/api/promo/apply", promo_apply)
    app.router.add_post("/api/promo/remove", promo_remove)
    app.router.add_post("/api/renew", renew)
    app.router.add_get("/api/buy-options", buy_options)
    app.router.add_post("/api/trial/request", trial_request)
    app.router.add_post("/api/buy", buy)
    app.router.add_get("/api/gift-options", gift_options)
    app.router.add_post("/api/gift/resolve", gift_resolve)
    app.router.add_post("/api/gift", gift)
    app.router.add_post("/api/devices/buy", devices_buy)
    app.router.add_get("/api/payment", payment_status)
    app.router.add_post("/api/webhooks/platega", platega_webhook)
    return app


async def start_server(bot=None, application=None) -> dict:
    """Поднимает API, если он включён в настройках.

    application — Telegram Application бота: веб-админке он нужен,
    чтобы пересобирать утреннюю задачу после смены времени/включения
    (handlers.morning.schedule_morning_sync)."""
    global _runner, _bot
    _bot = bot
    if application is not None:
        try:
            from web.admin_api import set_application
            set_application(application)
        except Exception:
            pass
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
    """Раз в сутки убирает просроченные сессии и коды сброса."""
    from core.database import (
        admin_sessions_purge, admin_setup_purge,
        password_resets_purge, web_sessions_purge,
    )
    await web_sessions_purge()
    await password_resets_purge()
    await admin_sessions_purge()
    await admin_setup_purge()


# ── Настройки кабинета (админка) ─────────────────────────────────────────────

async def handle_web_menu(query, context=None, note: str = ""):
    """Веб-доступ: сайт и личный кабинет на одном экране."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from config import load_config, turnstile_keys
    from core.database import web_sessions_stats
    import web.site_deploy as site
    if context:
        context.user_data.pop("state", None)
    cfg = load_config()
    s = settings()
    public = cfg.get("webapi_public") or ""
    stats = await web_sessions_stats()
    c = site.creds()
    url = site.site_url()
    link = site.cabinet_link()
    upstream = cfg.get("webapi_upstream") or ""
    has_ssh = site.paramiko_ready()

    lines = ["🌐 <b>Веб-доступ</b>", ""]
    if note:
        lines += [note, ""]

    # — Сайт —
    lines.append("<b>Сайт</b>")
    if has_ssh:
        state = (f"🟢 развёрнут {c['deployed_at']}" if c["deployed_at"]
                 else "⚪️ ещё не разворачивали")
        server = (f"<code>{html.escape(c['host'])}</code> · {html.escape(c['user'])}"
                  if c["host"] else "не задан")
        domain = (f"<code>{html.escape(c['domain'])}</code>"
                  if c["domain"] else "не задан")
        card = [f"🚀 Статус: <b>{state}</b>",
                f"🖥 Сервер: {server}",
                f"🌍 Домен: {domain}" + ("  ·  🔒 HTTPS" if c.get("https") else ""),
                "⚡ Автообновление: "
                + ("вкл" if cfg.get("site_auto", True) else "выкл")]
        if url and c["deployed_at"]:
            card.append(f"🔗 {html.escape(url)}")
        lines.append("<blockquote>" + "\n".join(card) + "</blockquote>")
    else:
        lines.append("<blockquote>⚠️ Сайт: нужна библиотека для SSH — "
                     f"<code>{html.escape(site.pip_path())} install paramiko</code>, "
                     "потом <code>systemctl restart drebol-vpn</code></blockquote>")

    # — Личный кабинет —
    ready = [
        ("🌐 Сайт развёрнут", bool(site.creds()["domain"] and cfg.get("site_deployed_at"))),
        ("🔌 API включён", s["enabled"]),
        ("🛰 API работает", is_running()),
        ("🔗 Адрес API задан", bool(public)),
        ("🪪 Кабинет опубликован", site.cabinet_ready()),
    ]
    lines.append("<b>Личный кабинет</b>")
    lines.append("<blockquote>" + "\n".join(
        ("✅ " if ok else "⬜️ ") + name for name, ok in ready) + "</blockquote>")
    lines.append(
        "<blockquote>"
        f"🔌 Порт: <b>{s['port']}</b>  ·  слушаем: <b>{s['bind']}</b>\n"
        f"🔗 Адрес API: <b>{html.escape(public) if public else 'не задан'}</b>\n"
        f"👥 Живых сессий: <b>{stats['live']}</b>  ·  людей: <b>{stats['people']}</b>  ·  "
        f"входов сегодня: <b>{stats['today']}</b>"
        "</blockquote>")
    ts_site, ts_secret = turnstile_keys()
    lines.append(
        "<blockquote>"
        "🔑 Капча Turnstile: "
        f"site key <b>{html.escape(ts_site[:8] + '…') if ts_site else 'не задан'}</b>"
        f"  ·  secret: <b>{'задан' if ts_secret else 'не задан'}</b>"
        "</blockquote>")
    if link:
        lines.append(f"<blockquote>🪪 Кабинет: {html.escape(link)}</blockquote>")
    if upstream:
        lines.append(f"<blockquote>🔀 Сайт шлёт <code>/api/</code> на "
                     f"<b>{html.escape(upstream)}</b></blockquote>")
    lines.append(
        "\n<i>Кабинет только показывает: срок, ссылку подписки, устройства и платежи. "
        "Менять что-либо можно только в боте.</i>")

    kb = []
    # сайт
    if site.configured() and has_ssh:
        kb.append([InlineKeyboardButton(
            "🔄 Обновить сайт" if c["deployed_at"] else "🚀 Развернуть сайт",
            callback_data="site_deploy")])
    kb.append([InlineKeyboardButton("🖥 Сервер", callback_data="site_server"),
               InlineKeyboardButton("🌍 Домен", callback_data="site_domain")])
    kb.append([InlineKeyboardButton("✍️ Тексты сайта", callback_data="site_texts")])
    if site.configured() and has_ssh:
        extra = []
        if c["domain"] and c["deployed_at"] and not c["https"]:
            extra.append(InlineKeyboardButton("🔒 Включить HTTPS", callback_data="site_cert"))
        if c["deployed_at"]:
            extra.append(InlineKeyboardButton("🩺 Проверить", callback_data="site_check"))
            extra.append(InlineKeyboardButton(
                "⚡ Авто: вкл" if cfg.get("site_auto", True) else "💤 Авто: выкл",
                callback_data="site_auto"))
        if extra:
            kb.append(extra)
        if c["deployed_at"] and url:
            kb.append([InlineKeyboardButton("🔗 Открыть сайт", url=url),
                       InlineKeyboardButton("🗑 Удалить", callback_data="site_delete")])
    # кабинет
    kb.append([InlineKeyboardButton("🔴 Выключить API" if s["enabled"] else "🟢 Включить API",
                                callback_data="cab_toggle"),
           InlineKeyboardButton("🩺 Проверить", callback_data="cab_check")])
    kb.append([InlineKeyboardButton("🔍 Найти адрес бота", callback_data="cab_find")])
    kb.append([InlineKeyboardButton("🔀 Через сайт", callback_data="cab_upstream"),
           InlineKeyboardButton("🔗 Адрес API", callback_data="cab_public"),
           InlineKeyboardButton("🔌 Порт", callback_data="cab_port")])
    kb.append([InlineKeyboardButton("🔑 Капча Turnstile", callback_data="cab_turnstile")])
    if link:
        kb.append([InlineKeyboardButton("🪪 Открыть кабинет", url=link)])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_cabinet_menu(query, context=None, note: str = ""):
    """Старое имя экрана кабинета: теперь это общий экран «Веб-доступ»."""
    await handle_web_menu(query, context, note=note)


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


async def handle_turnstile_menu(query, context=None, note: str = ""):
    """Капча для входа в кабинет по почте: ключи Cloudflare Turnstile."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from config import turnstile_keys
    if context:
        context.user_data.pop("state", None)
    site_key, secret = turnstile_keys()
    lines = ["🔑 <b>Капча Turnstile</b>", ""]
    if note:
        lines += [note, ""]
    lines.append(
        "<blockquote>"
        f"🔑 Site key: <b>{html.escape(site_key[:8] + '…') if site_key else 'не задан'}</b>\n"
        f"🔒 Secret key: <b>{'задан' if secret else 'не задан'}</b>"
        "</blockquote>")
    lines.append(
        "<i>Ключи берутся в Cloudflare: dash.cloudflare.com → Turnstile → Add site. "
        "Site key публичный — он вставляется в страницу входа, secret никому не показываем. "
        "Без ключей вход по почте выключен, вход через Telegram работает. "
        "После смены site key разверни сайт заново — страница кабинета уедет с новым ключом.</i>")
    kb = [[InlineKeyboardButton("🔑 Site key", callback_data="cab_turnstile_site"),
           InlineKeyboardButton("🔒 Secret key", callback_data="cab_turnstile_secret")],
          [InlineKeyboardButton("◀️ Назад", callback_data="cab_menu")]]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_turnstile_ask(query, context, what: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.states import AWAITING_TURNSTILE_SECRET, AWAITING_TURNSTILE_SITE
    if what == "site":
        context.user_data["state"] = AWAITING_TURNSTILE_SITE
        text = ("🔑 <b>Site key Turnstile</b>\n\n"
                "<blockquote>Пришли site key из Cloudflare (Turnstile → твой сайт → Settings). "
                "Он публичный — вставляется в страницу входа.</blockquote>\n\n"
                "<i>Пришли <code>-</code>, чтобы убрать ключ.</i>")
    else:
        context.user_data["state"] = AWAITING_TURNSTILE_SECRET
        text = ("🔒 <b>Secret key Turnstile</b>\n\n"
                "<blockquote>Пришли secret key из Cloudflare. Его никому не показываем — "
                "он нужен боту, чтобы проверять капчу.</blockquote>\n\n"
                "<i>Пришли <code>-</code>, чтобы убрать ключ.</i>")
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="cab_turnstile")]]))


async def handle_cabinet_ask(query, context, what: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from core.states import AWAITING_CABINET_PORT, AWAITING_CABINET_PUBLIC, AWAITING_CABINET_UPSTREAM
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
    from core.states import (AWAITING_CABINET_PORT, AWAITING_CABINET_UPSTREAM,
                             AWAITING_TURNSTILE_SECRET, AWAITING_TURNSTILE_SITE)
    import web.site_deploy as site
    msg = update.message
    back = InlineKeyboardMarkup([[InlineKeyboardButton("🪪 К кабинету", callback_data="cab_menu")]])
    cfg = load_config()
    if state in (AWAITING_TURNSTILE_SITE, AWAITING_TURNSTILE_SECRET):
        key = ("turnstile_site_key" if state == AWAITING_TURNSTILE_SITE
               else "turnstile_secret_key")
        name = "Site key" if state == AWAITING_TURNSTILE_SITE else "Secret key"
        back_ts = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔑 К капче", callback_data="cab_turnstile")]])
        value = text.strip()
        if value == "-":
            cfg[key] = ""
            save_config(cfg)
            context.user_data.pop("state", None)
            await msg.reply_text(
                f"✅ <b>{name} убран</b>\n\n"
                "<i>Вход по почте выключен, пока ключей нет.</i>",
                parse_mode="HTML", reply_markup=back_ts)
            return
        if not value or " " in value:
            await msg.reply_text("❌ <b>Ключ — одна строка без пробелов</b>",
                                 parse_mode="HTML", reply_markup=back_ts)
            return
        cfg[key] = value
        save_config(cfg)
        context.user_data.pop("state", None)
        tail = ("\n\n<i>Разверни сайт заново — страница кабинета уедет с новым ключом.</i>"
                if state == AWAITING_TURNSTILE_SITE else "")
        await msg.reply_text(f"✅ <b>{name} сохранён</b>{tail}",
                             parse_mode="HTML", reply_markup=back_ts)
        return
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
            await msg.reply_text("❌ <b>Нужен адрес вида <code>10.0.0.5:8088</code></b>\n\n"
                                 "<i>Или нажми «🔍 Найти адрес бота» — подберу сам.</i>",
                                 parse_mode="HTML", reply_markup=back)
            return
        if host in SAMPLE_HOSTS:
            await msg.reply_text(
                f"❌ <b>{html.escape(host)} — это адрес из примера</b>\n\n"
                "<i>Нужен настоящий адрес сервера с ботом. Проще всего нажать "
                "«🔍 Найти адрес бота» — бот подберёт его сам.</i>",
                parse_mode="HTML", reply_markup=back)
            return
        # спрашиваем сам сервер сайта: дойдёт ли он туда
        probe_res = await site.probe_targets([target])
        code = probe_res.get(target) if "error" not in probe_res else None
        cfg["webapi_upstream"] = target
        # раз сайт сам отдаёт /api/, кабинету достаточно адреса сайта
        if site.creds()["domain"]:
            cfg["webapi_public"] = site.site_url()
        save_config(cfg)
        context.user_data.pop("state", None)
        if code == "200":
            tail = "<i>Сервер сайта туда дозвонился. Осталось развернуть сайт заново.</i>"
        elif code and code != "000":
            tail = (f"⚠️ <i>Сервер сайта получил оттуда ответ {html.escape(code)} — "
                    "похоже, это не бот. Проверь адрес или нажми «🔍 Найти адрес бота».</i>")
        else:
            tail = ("⚠️ <i>Сервер сайта туда не дозвонился: закрыт порт или не тот адрес. "
                    "Нажми «🔍 Найти адрес бота» — подберу сам.</i>")
        await msg.reply_text(
            f"✅ <b>Сайт будет слать /api/ на {html.escape(target)}</b>\n\n"
            f"<blockquote>🔗 Адрес API: "
            f"{html.escape(cfg.get('webapi_public') or 'задай вручную')}</blockquote>\n\n"
            + tail, parse_mode="HTML", reply_markup=back)
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


async def probe() -> dict:
    """Проверяет кабинет так же, как это делает браузер человека."""
    import aiohttp
    from config import load_config
    cfg = load_config()
    s = settings()
    public = str(cfg.get("webapi_public") or "").rstrip("/")
    out = {"enabled": s["enabled"], "running": is_running(), "public": public,
           "upstream": str(cfg.get("webapi_upstream") or ""),
           "local": None, "outside": None, "from_site": None, "advice": []}

    async def ping(url: str) -> dict:
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as r:
                    body = (await r.text())[:200]
                    return {"ok": r.status == 200 and '"ok"' in body,
                            "status": r.status, "body": body}
        except Exception as ex:
            return {"ok": False, "status": 0, "body": f"{type(ex).__name__}: {ex}"}

    if not s["enabled"]:
        out["advice"].append("API выключен — включи его кнопкой выше.")
        return out
    out["local"] = await ping(f"http://127.0.0.1:{s['port']}/api/health")
    if not out["local"]["ok"]:
        out["advice"].append("Бот не отвечает сам себе: порт занят другим сервисом "
                             "или API не поднялся — посмотри journalctl.")
        return out

    if not public:
        out["advice"].append("Не задан адрес API — нажми «🔀 Через сайт» или «🔗 Адрес API».")
        return out
    out["outside"] = await ping(f"{public}/api/health")
    if out["outside"]["ok"]:
        return out
    if out["upstream"]:
        import web.site_deploy as site
        checked = await site.probe_targets([out["upstream"]])
        out["from_site"] = checked.get(out["upstream"]) if "error" not in checked else None
        if out["from_site"] != "200":
            got = str(out.get("from_site") or "")
            how = ("связи нет" if got in ("", "000") else f"ответ {got}")
            out["advice"].append(
                f"Сервер сайта не достучался до <code>{html.escape(out['upstream'])}</code> "
                f"({how}). Нажми «🔍 Найти адрес бота» — подберу рабочий сам.")
            return out
    if out["outside"]["status"] in (404, 403):
        out["advice"].append("Адрес отвечает, но не тем: сайт не пересылает <code>/api/</code>. "
                             "Нажми «🔀 Через сайт», укажи адрес бота и разверни сайт заново.")
    elif out["outside"]["status"]:
        out["advice"].append(f"Адрес ответил кодом {out['outside']['status']} — "
                             "проверь, что путь ведёт к боту, а не к панели или сайту.")
    else:
        out["advice"].append("Снаружи бот недоступен: закрыт порт "
                             f"{s['port']} или указан не тот адрес. "
                             "Открой порт для сервера сайта и проверь адрес.")
    if public.startswith("http://"):
        out["advice"].append("Адрес по http — браузер не пустит такие запросы со "
                             "страницы по https. Нужен https или пересылка через сайт.")
    return out


async def handle_cabinet_check(query, context):
    """Кнопка «Проверить»: бот сам стучится в кабинет и объясняет, что не так."""
    await query.edit_message_text("🩺 Проверяю кабинет…", parse_mode="HTML")
    r = await probe()
    lines = ["🩺 <b>Проверка кабинета</b>", ""]
    rows = [("🔌 API включён", r["enabled"]),
            ("🛰 Сервер поднят", r["running"])]
    if r["local"] is not None:
        rows.append((f"🏠 Отвечает себе ({settings()['port']})", r["local"]["ok"]))
    if r["outside"] is not None:
        rows.append(("🌍 Отвечает снаружи", r["outside"]["ok"]))
    lines.append("<blockquote>" + "\n".join(
        ("✅ " if ok else "❌ ") + name for name, ok in rows) + "</blockquote>")
    if r["public"]:
        lines.append(f"<blockquote>🔗 Проверял: <code>{html.escape(r['public'])}/api/health</code>"
                     + (f"\n📨 Ответ: <code>{html.escape(str((r['outside'] or {}).get('body'))[:120])}</code>"
                        if r["outside"] else "") + "</blockquote>")
    if r["advice"]:
        lines.append("<blockquote>" + "\n\n".join("⚠️ " + a for a in r["advice"]) + "</blockquote>")
    elif r["outside"] and r["outside"]["ok"]:
        lines.append("<i>Кабинет отвечает. Если страница всё равно просит вход — "
                     "скажи @BotFather команду /setdomain с доменом сайта и "
                     "разверни сайт заново, чтобы уехала свежая страница.</i>")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Ещё раз", callback_data="cab_check"),
             InlineKeyboardButton("◀️ К кабинету", callback_data="cab_menu")]]))


# Адреса из примеров: если такой ввели, значит скопировали подсказку как есть
SAMPLE_HOSTS = {"1.2.3.4", "0.0.0.0", "8.8.8.8", "example.com", "host", "ip"}


async def my_public_ip() -> str:
    """Внешний адрес сервера бота — чтобы не искать его руками."""
    import aiohttp
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            timeout = aiohttp.ClientTimeout(total=6)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as r:
                    ip = (await r.text()).strip()
                    if ip and len(ip) < 46 and " " not in ip:
                        return ip
        except Exception:
            continue
    return ""


async def find_upstream() -> dict:
    """Сам ищет адрес, по которому сайт достучится до бота.

    Пробует по очереди: тот же сервер, внешний адрес бота, адрес сервера сайта.
    Проверку делает сам сервер сайта — именно ему потом ходить к боту.
    """
    import web.site_deploy as site
    s = settings()
    port = s["port"]
    candidates = [f"127.0.0.1:{port}"]
    ip = await my_public_ip()
    if ip:
        candidates.append(f"{ip}:{port}")
    host = site.creds()["host"]
    if host and f"{host}:{port}" not in candidates:
        candidates.append(f"{host}:{port}")

    res = await site.probe_targets(candidates)
    if "error" in res:
        return {"ok": False, "error": res["error"], "tried": candidates}
    for target in candidates:
        if res.get(target) == "200":
            return {"ok": True, "target": target, "tried": res, "ip": ip}
    return {"ok": False, "tried": res, "ip": ip,
            "error": "ни один адрес не ответил"}


async def handle_cabinet_find(query, context):
    """Кнопка «Найти адрес»: бот подбирает его сам и сохраняет."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from config import load_config, save_config
    import web.site_deploy as site
    await query.edit_message_text("🔎 Ищу адрес, по которому сайт достучится до бота…",
                                  parse_mode="HTML")
    r = await find_upstream()
    back = InlineKeyboardMarkup([[InlineKeyboardButton("🪪 К кабинету", callback_data="cab_menu")]])
    if not r.get("ok"):
        tried = r.get("tried")
        lines = ["🔎 <b>Адрес не нашёлся</b>", ""]
        if isinstance(tried, dict):
            lines.append("<blockquote>" + "\n".join(
                f"<code>{html.escape(t)}</code> — ответ {html.escape(str(code))}"
                for t, code in tried.items()) + "</blockquote>")
        lines.append(f"<i>{html.escape(str(r.get('error')))}</i>")
        lines.append("\n<i>Чаще всего мешает файрвол: открой порт "
                     f"{settings()['port']} на сервере бота для адреса сервера сайта. "
                     "Например: <code>ufw allow from АДРЕС_САЙТА to any port "
                     f"{settings()['port']}</code></i>")
        await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back)
        return

    cfg = load_config()
    cfg["webapi_upstream"] = r["target"]
    if site.creds()["domain"]:
        cfg["webapi_public"] = site.site_url()
    save_config(cfg)
    await query.edit_message_text(
        f"✅ <b>Нашёл: {html.escape(r['target'])}</b>\n\n"
        f"<blockquote>🔀 Сайт будет слать <code>/api/</code> туда\n"
        f"🔗 Адрес API: <b>{html.escape(cfg.get('webapi_public') or '—')}</b></blockquote>\n\n"
        "<i>Осталось развернуть сайт заново — и кабинет заработает.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 К сайту", callback_data="site_menu"),
             InlineKeyboardButton("🩺 Проверить", callback_data="cab_check")],
            [InlineKeyboardButton("🪪 К кабинету", callback_data="cab_menu")]]))
