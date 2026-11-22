"""Вотчер новых устройств в платных подписках.

Заказ владельца: «если чел добавил новое устройство в подписку — бот ему
пишет об этом». Раз в 10 минут смотрим устройства (HWID) активных платных
подписок в панели Remnawave и сравниваем со снимком в таблице
known_devices. Новый HWID — сообщение владельцу подписки и строка в
лог-канал (для антифрода видно, у кого плодятся устройства).

Это НЕ синхронизация с панелью: только один узкий запрос устройств по
каждой подписке, никаких правок ни в панели, ни в базе подписок. Полная
синхронизация остаётся ручной (решение владельца 2026-11-19), а этот
вотчер включён отдельным прямым заказом; выключается тумблером
«device_watch» в настройках «⏰ Синхронизация».

Первый успешный проход по подписке — тихая база: все текущие устройства
просто записываются в снимок (таблица device_watch_baseline), уведомлений
о них нет. Уведомления — только о HWID, появившихся после базы. Если
панель по подписке не ответила, подписка пропускается и база по ней НЕ
фиксируется: иначе следующий успешный проход принял бы все её устройства
за новые и заспамил владельца.

Снимок — точная копия текущего списка панели: устройство, удалённое из
панели, уходит и из снимка, поэтому повторное подключение того же
устройства позже снова считается новым и снова уведомляет.
"""

import asyncio
from datetime import datetime
from html import escape

import aiosqlite

from core.database import DB_PATH

_LOCK = asyncio.Lock()

_CREATE_KNOWN = """
CREATE TABLE IF NOT EXISTS known_devices (
    sub_key TEXT NOT NULL,
    hwid TEXT NOT NULL,
    app TEXT,
    platform TEXT,
    first_seen TEXT,
    PRIMARY KEY (sub_key, hwid)
)
"""

_CREATE_BASELINE = """
CREATE TABLE IF NOT EXISTS device_watch_baseline (
    sub_key TEXT PRIMARY KEY,
    done_at TEXT
)
"""

# Минимальный маппинг «чем подключаются» — запасной, на случай если
# _device_app из handlers.user импортировать не вышло. Основной путь —
# тот же код, что рисует экран «Мои устройства».
_APPS_FALLBACK = (
    ("happ", "Happ"), ("incy", "INCY"), ("hiddify", "Hiddify"),
    ("streisand", "Streisand"), ("shadowrocket", "Shadowrocket"),
    ("v2rayng", "v2RayNG"), ("v2rayn", "v2RayN"), ("v2box", "V2Box"),
    ("nekobox", "NekoBox"), ("nekoray", "NekoRay"), ("sing-box", "sing-box"),
    ("singbox", "sing-box"), ("clash", "Clash"), ("foxray", "FoXray"),
    ("karing", "Karing"), ("exclave", "Exclave"), ("throne", "Throne"),
    ("husi", "Husi"), ("loon", "Loon"), ("stash", "Stash"),
    ("quantumult", "Quantumult"),
)


def _fallback_app(item: dict) -> str:
    blob = " ".join(str(item.get(k, "")) for k in
                    ("userAgent", "user_agent", "ua", "appName", "app",
                     "client", "clientName", "deviceApp", "software",
                     "platform")).lower()
    for needle, name in _APPS_FALLBACK:
        if needle in blob:
            return name
    raw = str(item.get("userAgent") or item.get("user_agent") or "")
    head = raw.split("/")[0].strip()
    return head if 1 < len(head) <= 20 else ""


def _fallback_title(item: dict) -> str:
    parts = [str(item[k]).strip() for k in ("deviceModel", "deviceOs")
             if item.get(k)]
    return " · ".join(parts) or "устройство"


def _device_app_title(item: dict) -> tuple:
    """(приложение, подпись устройства) — как на экране «Мои устройства».

    Импорт отложенный: handlers.user тянет клавиатуры и конфиг, а вотчер
    импортируется из bot.py при регистрации задач — к моменту тика всё
    уже загружено и цикла нет. Не вышло — локальный маппинг выше.
    """
    try:
        from handlers.user import _device_app, _device_title
        return _device_app(item), _device_title(item)
    except Exception:
        return _fallback_app(item), _fallback_title(item)


def _expired(expire_date) -> bool:
    """Срок в базе — текстом «дд.мм.гггг чч:мм:сс». Не разобрали — не
    считаем истёкшей: лучше лишний проход, чем пропущенное уведомление."""
    try:
        dt = datetime.strptime(str(expire_date).strip(), "%d.%m.%Y %H:%M:%S")
    except (TypeError, ValueError):
        return False
    return dt < datetime.now()


def _notify_text(item: dict) -> str:
    app, title = _device_app_title(item)
    model = title if title and title != "устройство" else ""
    if app:
        via = f"через <b>{escape(app)}</b>"
        if model:
            via += f" — {escape(model)}"
    else:
        via = "через другой VPN-клиент"
        if model:
            via += f" ({escape(model)})"
    return (
        "📱 <b>Новое устройство в вашей подписке</b>\n\n"
        f"К Drebol VPN подключилось новое устройство {via}.\n\n"
        "Если это были не вы — отключите устройство: «Моя подписка» → "
        "«📱 Устройства», или напишите в поддержку."
    )


async def _notify_owner(bot, tg_id, item) -> bool:
    if not bot or not tg_id:
        return False
    try:
        await bot.send_message(chat_id=tg_id, text=_notify_text(item),
                               parse_mode="HTML")
        return True
    except Exception:
        # Заблокировал бота, удалил аккаунт и т.п. — проход не валим.
        return False


async def _log_new_device(bot, email, tg_id, item):
    try:
        from core.log_channel import send_log
        app, title = _device_app_title(item)
        what = escape(app) if app else "другой VPN-клиент"
        extra = (f" · {escape(title)}"
                 if title and title != "устройство" else "")
        await send_log(
            bot,
            f"📱 Новое устройство в подписке <b>{escape(str(email))}</b> "
            f"(tg <code>{tg_id}</code>): {what}{extra}")
    except Exception:
        pass


async def _watch_sub(db, bot, row, fetch, now, counters):
    """Одна подписка: сверить устройства панели со снимком."""
    sub_id, tg_id, email = row[0], row[1], row[2]
    if not tg_id or not email:
        counters["skipped"] += 1
        return
    if len(row) > 6 and row[6] not in ("active", "renewal"):
        counters["skipped"] += 1
        return
    if _expired(row[3]):
        counters["skipped"] += 1
        return
    sub_key = str(email)

    r = await fetch(sub_id)
    if not r.get("ok"):
        # Панель не ответила — подписку не трогаем вообще: ни снимок,
        # ни базу. Иначе следующий успешный проход примет все её
        # устройства за новые.
        counters["panel_fail"] += 1
        return
    counters["checked"] += 1
    current = {str(d["hwid"]): d for d in (r.get("items") or [])
               if d.get("hwid")}

    async with db.execute(
            "SELECT done_at FROM device_watch_baseline WHERE sub_key = ?",
            (sub_key,)) as cur:
        baselined = await cur.fetchone() is not None
    async with db.execute(
            "SELECT hwid FROM known_devices WHERE sub_key = ?",
            (sub_key,)) as cur:
        known = {r_[0] for r_ in await cur.fetchall()}

    if not baselined:
        # Тихая база: фиксируем то, что уже подключено, без уведомлений.
        for hwid, d in current.items():
            app, _ = _device_app_title(d)
            await db.execute(
                "INSERT OR REPLACE INTO known_devices"
                " (sub_key, hwid, app, platform, first_seen)"
                " VALUES (?, ?, ?, ?, ?)",
                (sub_key, hwid, app,
                 str(d.get("platform") or d.get("deviceOs") or ""), now))
        await db.execute(
            "INSERT OR REPLACE INTO device_watch_baseline (sub_key, done_at)"
            " VALUES (?, ?)", (sub_key, now))
        await db.commit()
        counters["baseline"] += 1
        return

    # Снимок приводим к текущему списку панели: ушедшие устройства
    # убираем (вернутся — снова будут новыми), новые добавляем ДО
    # уведомления, чтобы сбой отправки не плодил повторов каждые 10 минут.
    for hwid in known - set(current):
        await db.execute(
            "DELETE FROM known_devices WHERE sub_key = ? AND hwid = ?",
            (sub_key, hwid))
    new_hwids = [h for h in current if h not in known]
    for hwid in new_hwids:
        d = current[hwid]
        app, _ = _device_app_title(d)
        await db.execute(
            "INSERT OR REPLACE INTO known_devices"
            " (sub_key, hwid, app, platform, first_seen)"
            " VALUES (?, ?, ?, ?, ?)",
            (sub_key, hwid, app,
             str(d.get("platform") or d.get("deviceOs") or ""), now))
    await db.commit()

    for hwid in new_hwids:
        counters["new"] += 1
        if await _notify_owner(bot, tg_id, current[hwid]):
            counters["notified"] += 1
        await _log_new_device(bot, email, tg_id, current[hwid])


async def run_device_watch(bot, *, subs=None, fetch=None) -> dict:
    """Один проход вотчера. Возвращает счётчики.

    subs — строки paid_subs в формате paidsub.storage.all_paid_subs
    (id, tg_id, email, expire_date, total_gb, created_at, status, ...);
    None — берутся все из базы, неактивные и истёкшие отсеиваются внутри.
    fetch — async (sub_id) -> dict как paidsub.service.list_devices;
    None — настоящий list_devices(kind="paid"). Параметры — для тестов.
    """
    counters = {"ok": True, "checked": 0, "baseline": 0, "new": 0,
                "notified": 0, "panel_fail": 0, "skipped": 0}
    if fetch is None:
        from paidsub.service import list_devices

        async def fetch(sub_id):
            return await list_devices(sub_id, kind="paid")
    if subs is None:
        from paidsub.storage import all_paid_subs
        subs = await all_paid_subs(scope="all")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_KNOWN)
        await db.execute(_CREATE_BASELINE)
        await db.commit()
        for row in subs:
            try:
                await _watch_sub(db, bot, row, fetch, now, counters)
            except Exception:
                counters["skipped"] += 1
    return counters


async def device_watch_tick(context) -> dict:
    """Тик job_queue (раз в 10 минут, тумблер «device_watch»).

    Ошибка панели или одного пользователя проход не валит, сам тик бота
    не роняет никогда. Второй параллельный проход не запускаем.
    """
    if _LOCK.locked():
        return {"ok": True, "skipped": "already_running"}
    async with _LOCK:
        try:
            import services.remnawave as rw
            if not rw.is_configured():
                return {"ok": False, "error": "панель не настроена"}
            return await run_device_watch(context.bot)
        except Exception as e:
            return {"ok": False, "error": str(e)}
