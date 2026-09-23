"""Ловля повторных триалов.

Человек берёт пробный период, потом заводит новый аккаунт и берёт ещё один —
с тем же телефоном и той же квартирой. Панель про это знает: у подписки видны
устройства (HWID) и адреса, с которых она подключалась. Бот их постепенно
запоминает и, когда у двух разных аккаунтов совпадает устройство или адрес,
приносит находку админу — решение всегда за человеком, сам бот никого не банит.

Совпадение устройства — сильная улика: это буквально один и тот же телефон.
Совпадение адреса слабее (общий Wi-Fi, оператор сотовой связи), поэтому про
него бот пишет только когда замешана пробная подписка, и честно помечает,
что улика слабая.
"""

from config import ADMIN_ID, load_config, save_config


# Ключи, под которыми панель отдаёт настоящий идентификатор устройства.
# Их написание меняется от версии к версии, поэтому перебираем.
_STRONG_KEYS = ("hwid", "hwId", "deviceId", "device_id", "fingerprint", "uuid")
# Слабый запасной вариант: «iOS · iPhone» совпадает у тысяч людей,
# поэтому такие отпечатки просто запоминаем, но никогда не считаем уликой.
_WEAK_KEYS = ("deviceOs", "deviceModel", "appVersion")


def device_key(item: dict):
    """Отпечаток устройства и признак того, что он надёжный."""
    for k in _STRONG_KEYS:
        val = item.get(k)
        if val:
            return str(val), True
    parts = [str(item.get(k)) for k in _WEAK_KEYS if item.get(k)]
    return ("|".join(parts), False) if parts else (None, False)


async def _subs_slice(limit: int) -> list:
    """Очередная порция подписок для опроса панели.

    Ходим по кругу: за раз трогаем несколько подписок, чтобы не устраивать
    панели шквал запросов, но со временем обойти всех.
    """
    import aiosqlite
    from database import DB_PATH
    cfg = load_config()
    cursor = int(cfg.get("fraud_cursor", 0) or 0)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, tg_id, email, times_renewed FROM paid_subs "
            "WHERE tg_id IS NOT NULL AND status IN ('active', 'renewal') ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return []
    start = cursor % len(rows)
    batch = rows[start:start + limit]
    if len(batch) < limit:
        batch += rows[:limit - len(batch)]
    cfg["fraud_cursor"] = (start + len(batch)) % len(rows)
    save_config(cfg)
    return batch


async def fraud_tick(context):
    """Обходит подписки по кругу и запоминает их устройства и адреса."""
    cfg = load_config()
    if not cfg.get("fraud_enabled", True):
        return
    if not cfg.get("xui_url") or not cfg.get("xui_token"):
        return
    batch = await _subs_slice(int(cfg.get("fraud_batch", 8) or 8))
    for _sub_id, tg_id, email, times_renewed in batch:
        await scan_sub(context, tg_id, email, bool(times_renewed))


async def scan_sub(context, tg_id: int, email: str, paid: bool) -> list:
    """Запоминает отпечатки одной подписки и проверяет их на пересечения."""
    from database import remember_fingerprints, fingerprint_owners
    from xui_api import get_client_hwids, get_client_ips

    found = []
    hw = await get_client_hwids(email)
    if hw.get("ok"):
        strong, weak = [], []
        for item in hw["items"]:
            value, is_strong = device_key(item)
            if not value:
                continue
            (strong if is_strong else weak).append(value)
        await remember_fingerprints(email, tg_id, "hwid_weak", weak)
        fresh = await remember_fingerprints(email, tg_id, "hwid", strong)
        found += [("hwid", v) for v in fresh]

    ips = await get_client_ips(email)
    if ips.get("ok"):
        values = [i["ip"] for i in ips["items"] if i.get("ip")]
        fresh = await remember_fingerprints(email, tg_id, "ip", values)
        # адрес — улика слабая, поэтому смотрим на него только у пробных
        if not paid:
            found += [("ip", v) for v in fresh]

    alerts = []
    for kind, value in found:
        for other_tg, other_email in await fingerprint_owners(kind, value, tg_id):
            if await report_pair(context, tg_id, other_tg, kind, value, email, other_email):
                alerts.append((other_tg, kind))
    return alerts


async def report_pair(context, tg_id: int, other_tg: int, kind: str,
                      value: str, email: str, other_email: str) -> bool:
    """Показывает находку админу. Одну пару беспокоим только раз."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import note_fraud_pair, get_user_info
    from paidsub.handlers import _esc_name

    if not await note_fraud_pair(tg_id, other_tg, kind, value):
        return False

    a = await get_user_info(tg_id)
    b = await get_user_info(other_tg)
    a_name = _esc_name(a[1] if a else None, tg_id)
    b_name = _esc_name(b[1] if b else None, other_tg)
    if kind == "hwid":
        head = "🕵 <b>Одно устройство на двух аккаунтах</b>"
        note = "Совпал идентификатор устройства — это один и тот же телефон или компьютер."
    else:
        head = "🕵 <b>Один адрес на двух аккаунтах</b>"
        note = ("Совпал IP-адрес. Улика слабая: общий Wi-Fi, семья или "
                "мобильный оператор дают такое же совпадение.")

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"{head}\n\n"
            f"<blockquote>👤 {a_name} (<code>{tg_id}</code>)\n"
            f"👤 {b_name} (<code>{other_tg}</code>)\n"
            f"🔎 Совпадение: <code>{value[:40]}</code></blockquote>\n\n"
            f"<i>{note}</i>"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Первый", callback_data=f"user_profile:{tg_id}"),
             InlineKeyboardButton("👤 Второй", callback_data=f"user_profile:{other_tg}")],
            [InlineKeyboardButton("⛔ В ЧС первого", callback_data=f"bl_add_for:{tg_id}"),
             InlineKeyboardButton("🙈 Не фрод", callback_data=f"fraud_ok:{tg_id}:{other_tg}")],
        ]),
    )
    from log_channel import send_log
    await send_log(context.bot,
        f"🕵 Совпадение ({kind}): <code>{tg_id}</code> и <code>{other_tg}</code>")
    return True


# ── Экран в админке ───────────────────────────────────────────────────────────

async def handle_fraud_menu(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import fraud_stats
    cfg = load_config()
    enabled = cfg.get("fraud_enabled", True)
    st = await fraud_stats()
    status = "🟢 включена" if enabled else "🔴 выключена"
    await query.edit_message_text(
        "🕵 <b>Повторные триалы</b>\n\n"
        f"<blockquote>Слежка: <b>{status}</b>\n"
        f"🔎 Запомнено отпечатков: <b>{st['fingerprints']}</b>\n"
        f"👥 Найдено совпадений: <b>{st['pairs']}</b>"
        + (f"  ·  «не фрод»: {st['ignored']}" if st["ignored"] else "") + "</blockquote>\n\n"
        "<i>Бот по кругу опрашивает панель и запоминает, с каких устройств и "
        "адресов работают подписки. Когда устройство всплывает у второго "
        "аккаунта — присылает находку сюда. Сам он никого не банит: решение за тобой.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Выключить" if enabled else "🟢 Включить",
                                  callback_data="fraud_toggle"),
             InlineKeyboardButton("🔍 Проверить сейчас", callback_data="fraud_scan")],
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_fraud_toggle(query):
    cfg = load_config()
    cfg["fraud_enabled"] = not cfg.get("fraud_enabled", True)
    save_config(cfg)
    await handle_fraud_menu(query)


async def handle_fraud_scan(query, context):
    """Ручной прогон: полезно сразу после включения."""
    await query.edit_message_text("🔍 Опрашиваю панель…")
    cfg = load_config()
    batch = await _subs_slice(int(cfg.get("fraud_batch", 8) or 8))
    alerts = 0
    for _sub_id, tg_id, email, times_renewed in batch:
        alerts += len(await scan_sub(context, tg_id, email, bool(times_renewed)))
    await query.answer(
        f"Проверено подписок: {len(batch)} · находок: {alerts}", show_alert=True)
    await handle_fraud_menu(query)


async def handle_fraud_ok(query, a: int, b: int):
    from database import ignore_fraud_pair
    await ignore_fraud_pair(a, b)
    await query.edit_message_text(
        f"🙈 <b>Помечено «не фрод»</b>\n\n"
        f"<blockquote><code>{a}</code> и <code>{b}</code></blockquote>\n\n"
        "<i>Об этой паре больше не напомню.</i>",
        parse_mode="HTML",
    )
