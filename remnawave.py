"""Remnawave: подключение к панели и заведение клиентов пачкой.

Здесь живут настройки панели, выбор сквадов, разовое заведение всех живых
подписок из базы и рассылка ссылок людям.

Пути и поля взяты из контракта API панели: всё под /api, ответы завёрнуты
в {"response": ...}. Пользователь опознаётся по username — его мы генерируем
сами из email подписки, поэтому повторный перенос не плодит дублей,
а обновляет уже заведённых.
"""

import asyncio
import re
from datetime import datetime
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
        "expire_squads": list(cfg.get("rw_expire_squads") or []),
        "migrated_at": cfg.get("rw_migrated_at") or "",
        "migrated_count": int(cfg.get("rw_migrated_count") or 0),
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


# метка «стереть поле»: просто None в patch означает «не трогать»
CLEAR = object()


async def patch(username: str, **fields) -> dict:
    """Точечная правка пользователя: меняем только переданное.

    Поле, которому передали CLEAR, уходит в панель как null — так снимается
    тег и прочее, что панель хранит «или значение, или ничего».
    """
    body = {"username": username}
    for key, value in fields.items():
        if value is CLEAR:
            body[key] = None
        elif value is not None:
            body[key] = value
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


def build_payload(row, squads: list) -> dict:
    """Собирает тело запроса из нашей подписки."""
    (_sub_id, tg_id, email, expire_date, _limit_ip, limit_hwid,
     total_gb, _status, _renewed, _extra, _sub_url) = row
    payload = {
        "username": make_username(email, tg_id),
        "status": "ACTIVE",
        "expireAt": to_iso(expire_date),
        "trafficLimitBytes": int(total_gb or 0) * 1024 ** 3,
        "hwidDeviceLimit": int(limit_hwid or 0),
        "telegramId": int(tg_id),
        "description": "Заведено ботом Drebol VPN",
    }
    if squads:
        payload["activeInternalSquads"] = list(squads)
    return payload


async def migrate_subs(progress=None) -> dict:
    """Заводит в панели все живые подписки из базы.

    Уже заведённых не создаём заново, а приводим к нашим данным: так можно
    повторять сколько угодно раз, ничего не ломая. Пригодится после чистой
    установки панели или восстановления базы из бэкапа.
    """
    from paidsub.storage import subs_for_migration, update_paid_sub_field
    s = settings()
    rows = await subs_for_migration()
    if not rows:
        return {"ok": True, "total": 0, "created": 0, "updated": 0, "errors": []}

    created = updated = 0
    errors = []
    for i, row in enumerate(rows, 1):
        sub_id, tg_id, email = row[0], row[1], row[2]
        payload = build_payload(row, s["squads"])
        try:
            found = await get_user(payload["username"])
            if found["ok"]:
                body = dict(payload)
                body.pop("status", None)      # статусом управляет сама панель
                res = await update_user(body)
                action = "updated"
            else:
                res = await create_user(payload)
                action = "created"

            if not res["ok"]:
                errors.append(f"{email}: {res.get('error')}")
                continue

            data = res["data"] or {}
            link = data.get("subscriptionUrl") or ""
            if link:
                await update_paid_sub_field(sub_id, "sub_url", link)
            if data.get("shortUuid"):
                await update_paid_sub_field(sub_id, "sub_id", data["shortUuid"])
            if data.get("vlessUuid"):
                await update_paid_sub_field(sub_id, "uuid", data["vlessUuid"])
            created += action == "created"
            updated += action == "updated"
        except Exception as e:
            errors.append(f"{email}: {type(e).__name__}: {e}")

        if progress and (i % 10 == 0 or i == len(rows)):
            await progress(i, len(rows))
        await asyncio.sleep(STEP_PAUSE)

    save_settings(rw_migrated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                  rw_migrated_count=created + updated)
    return {"ok": True, "total": len(rows), "created": created,
            "updated": updated, "errors": errors}


# ── Метки, оставшиеся от переезда ─────────────────────────────────────────────

# По этим приметам видно клиента, заведённого при переезде со старой панели.
OLD_MARKS = ("3x-UI", "3xui", "Перенос из")
OLD_TAGS = ("MIGRATED", "MIGRATION", "FROM3XUI")


def _has_old_mark(user: dict) -> bool:
    tag = (user.get("tag") or "").upper()
    note = user.get("description") or ""
    return tag in OLD_TAGS or any(m.lower() in note.lower() for m in OLD_MARKS)


async def count_old_marks() -> dict:
    """Сколько клиентов ещё помечены переездом."""
    users = await all_users()
    marked = [u for u in users if _has_old_mark(u)]
    return {"ok": True, "total": len(users), "marked": len(marked)}


async def clear_old_marks(progress=None) -> dict:
    """Снимает тег и описание, оставшиеся от переезда.

    Вместо старой пометки пишем обычное описание: ник человека, если он есть
    в базе бота, — по нему клиента видно в панели без сверки с базой.
    """
    from database import get_user_info
    users = await all_users()
    marked = [u for u in users if _has_old_mark(u)]
    cleaned, errors = 0, []
    for i, u in enumerate(marked, 1):
        name = u.get("username")
        if not name:
            continue
        note = "Создано ботом Drebol VPN"
        tg_id = u.get("telegramId")
        if tg_id:
            try:
                row = await get_user_info(int(tg_id))
                if row and row[2]:
                    note = f"Drebol VPN · @{row[2]}"
            except Exception:
                pass
        r = await patch(name, description=note, tag=CLEAR)
        if r["ok"]:
            cleaned += 1
        else:
            errors.append(f"{name}: {r.get('error')}")
        if progress and (i % 10 == 0 or i == len(marked)):
            await progress(i, len(marked))
        await asyncio.sleep(STEP_PAUSE)
    return {"ok": True, "marked": len(marked), "cleaned": cleaned, "errors": errors}


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
    expire_squads = (f"выбрано <b>{len(s['expire_squads'])}</b>"
                     if s["expire_squads"] else "нет — доступ просто отключаем")
    state = (f"{s['migrated_at']} · {s['migrated_count']} подписок"
             if s["migrated_at"] else "ещё не заводили пачкой")

    lines = ["🖥 <b>Панель Remnawave</b>", "",
             "<blockquote>"
             f"🌐 Адрес: {url}\n"
             f"🔑 Токен: <b>{token}</b>\n"
             f"👥 Сквады: {squads}\n"
             f"🏁 Сквады окончания: {expire_squads}\n"
             f"🚚 Заводили клиентов: {state}</blockquote>", "",
             "<i>Через неё идут выдача, продление, лимиты устройств, "
             "перевыпуск ключа и заморозка.</i>"]

    kb = [[InlineKeyboardButton("🌐 Адрес панели", callback_data="rw_url"),
           InlineKeyboardButton("🔑 Токен", callback_data="rw_token")]]
    if is_configured():
        kb.append([InlineKeyboardButton("👥 Сквады", callback_data="rw_squads"),
                   InlineKeyboardButton("🏁 Окончание", callback_data="rw_squads_expire")])
        kb.append([InlineKeyboardButton("🔌 Проверить", callback_data="rw_test"),
                   InlineKeyboardButton("🧹 Метки переезда", callback_data="rw_marks")])
        kb.append([InlineKeyboardButton("🩺 Здоровье узлов", callback_data="healthcheck")])
        kb.append([InlineKeyboardButton("🚚 Завести клиентов в панели",
                                        callback_data="rw_migrate")])
        kb.append([InlineKeyboardButton("📨 Разослать ссылки клиентам",
                                        callback_data="rw_notify")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


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


SQUAD_MODES = {
    "main": {
        "key": "rw_squads", "toggle": "rw_squad", "screen": "rw_squads",
        "title": "👥 <b>Сквады для клиентов</b>",
        "hint": "Отметь, какие выдавать. Выбранные получат все новые подписки "
                "и все, кого заводим пачкой.",
        "empty": "<i>Ничего не выбрано — панель заведёт людей без доступа.</i>",
        "back": ("◀️ К панели", "rw_menu"),
    },
    "expire": {
        "key": "rw_expire_squads", "toggle": "rw_squad_exp", "screen": "rw_squads_expire",
        "title": "🏁 <b>Сквады после окончания подписки</b>",
        "hint": "Куда переводить клиента, когда срок кончился. Доступ к этому "
                "моменту всё равно закрыт — смысл в порядке: в рабочих сквадах "
                "остаются только платящие, и сразу видно, кто отвалился. "
                "После оплаты клиент вернётся в рабочие сквады сам.",
        "empty": "<i>Ничего не выбрано — по окончании просто отключаем доступ "
                 "и сквады не трогаем.</i>",
        "back": ("◀️ К настройкам", "paid_sub_presets"),
    },
}


async def handle_rw_squads(query, context, mode: str = "main"):
    """Выбор сквадов: и тех, что выдаём, и тех, куда уводим после окончания."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cfg = SQUAD_MODES.get(mode) or SQUAD_MODES["main"]
    await query.edit_message_text("👥 Загружаю сквады…")
    r = await list_squads()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить список</b>\n\n<code>{escape(str(r.get('error'))[:300])}</code>",
            parse_mode="HTML", reply_markup=_back())
        return

    chosen = set(load_config().get(cfg["key"]) or [])
    rows = []
    for sq in r["squads"]:
        mark = "✅ " if sq["uuid"] in chosen else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{sq['name']} · {sq['inbounds']} инб · {sq['members']} чел",
            callback_data=f"{cfg['toggle']}:{sq['uuid']}")])
    rows.append([InlineKeyboardButton(cfg["back"][0], callback_data=cfg["back"][1])])

    await query.edit_message_text(
        cfg["title"] + "\n\n" + cfg["hint"] + "\n\n"
        + (cfg["empty"] if not chosen else ""),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_rw_squad_toggle(query, context, uuid: str, mode: str = "main"):
    key = (SQUAD_MODES.get(mode) or SQUAD_MODES["main"])["key"]
    chosen = list(load_config().get(key) or [])
    if uuid in chosen:
        chosen.remove(uuid)
    else:
        chosen.append(uuid)
    save_settings(**{key: chosen})
    await handle_rw_squads(query, context, mode)


# ── Метки переезда ────────────────────────────────────────────────────────────

async def handle_rw_marks(query, context):
    """Сколько клиентов помечены переездом и предложение снять метки."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🧹 Смотрю метки…")
    r = await count_old_marks()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Панель не ответила</b>\n\n<code>{escape(str(r.get('error'))[:300])}</code>",
            parse_mode="HTML", reply_markup=_back())
        return
    if not r["marked"]:
        await query.edit_message_text(
            "🧹 <b>Метки переезда</b>\n\n"
            f"<blockquote>Клиентов в панели: <b>{r['total']}</b>\n"
            "Помеченных переездом: <b>нет</b></blockquote>\n\n"
            "<i>Чистить нечего.</i>",
            parse_mode="HTML", reply_markup=_back())
        return

    await query.edit_message_text(
        "🧹 <b>Метки переезда</b>\n\n"
        f"<blockquote>Клиентов в панели: <b>{r['total']}</b>\n"
        f"С меткой переезда: <b>{r['marked']}</b></blockquote>\n\n"
        "Сниму тег и напишу обычное описание: ник человека, если он есть "
        "в базе бота.\n\n"
        "<i>Подписок, сроков и ссылок это не касается.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 Снять метки", callback_data="rw_marks_go")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="rw_menu")],
        ]),
    )


async def handle_rw_marks_go(query, context):
    await query.edit_message_text("🧹 Снимаю метки…")

    async def progress(done, total):
        try:
            await query.edit_message_text(
                f"🧹 Снимаю метки… <b>{done}</b> из <b>{total}</b>", parse_mode="HTML")
        except Exception:
            pass

    res = await clear_old_marks(progress)
    errors = res.get("errors") or []
    lines = ["✅ <b>Готово</b>", "",
             "<blockquote>"
             f"Было с меткой: <b>{res['marked']}</b>\n"
             f"Почистили: <b>{res['cleaned']}</b>\n"
             f"С ошибкой: <b>{len(errors)}</b></blockquote>"]
    if errors:
        shown = "\n".join(escape(e[:120]) for e in errors[:5])
        lines += ["", "⚠️ <b>Не получилось</b>", f"<blockquote>{shown}</blockquote>"]
        if len(errors) > 5:
            lines.append(f"<i>…и ещё {len(errors) - 5}</i>")

    from log_channel import send_log
    await send_log(context.bot,
                   f"🧹 Метки переезда сняты у {res['cleaned']} клиентов, "
                   f"ошибок {len(errors)}")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=_back())


async def handle_rw_migrate(query, context):
    """Показывает, кого заведём в панели, и спрашивает подтверждение."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import subs_for_migration
    rows = await subs_for_migration()
    s = settings()
    if not rows:
        await query.answer("Заводить некого: живых подписок нет", show_alert=True)
        return

    warn = ("\n⚠️ <b>Сквады не выбраны</b> — люди заведутся без доступа.\n"
            if not s["squads"] else "")
    await query.edit_message_text(
        "🚚 <b>Завести клиентов в панели</b>\n\n"
        f"<blockquote>Живых подписок: <b>{len(rows)}</b>\n"
        f"Сквадов: <b>{len(s['squads'])}</b></blockquote>\n"
        f"{warn}\n"
        "Срок, лимит устройств и трафик возьму из базы. Кто уже есть в панели — "
        "обновлю, а не продублирую.\n\n"
        "<i>Ссылки в боте обновятся сразу, клиентам разошлём отдельной кнопкой.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚚 Завести", callback_data="rw_migrate_go")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="rw_menu")],
        ]),
    )


async def handle_rw_migrate_go(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text("🚚 Завожу…")

    async def progress(done, total):
        try:
            await query.edit_message_text(f"🚚 Завожу… <b>{done}</b> из <b>{total}</b>",
                                          parse_mode="HTML")
        except Exception:
            pass

    res = await migrate_subs(progress)
    errors = res.get("errors") or []
    lines = ["✅ <b>Готово</b>", "",
             "<blockquote>"
             f"Всего подписок: <b>{res['total']}</b>\n"
             f"Создано: <b>{res['created']}</b>\n"
             f"Обновлено: <b>{res['updated']}</b>\n"
             f"С ошибкой: <b>{len(errors)}</b></blockquote>"]
    if errors:
        shown = "\n".join(escape(e[:120]) for e in errors[:5])
        lines += ["", "⚠️ <b>Не получилось</b>", f"<blockquote>{shown}</blockquote>"]
        if len(errors) > 5:
            lines.append(f"<i>…и ещё {len(errors) - 5}</i>")
    lines += ["", "<i>Открой пару ссылок из панели — и можно рассылать их людям.</i>"]

    from log_channel import send_log
    await send_log(context.bot,
        f"🚚 Клиенты в Remnawave: создано {res['created']}, "
        f"обновлено {res['updated']}, ошибок {len(errors)}")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К Remnawave", callback_data="rw_menu")]]),
        disable_web_page_preview=True,
    )


# ── Рассылка новых ссылок ─────────────────────────────────────────────────────

async def handle_rw_notify(query, context):
    """Спрашивает подтверждение: ссылки уходят живым людям, молча нельзя."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import subs_for_migration
    rows = await subs_for_migration()
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
    from paidsub.storage import subs_for_migration
    rows = [r for r in await subs_for_migration() if r[10]]
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
