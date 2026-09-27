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


def is_public_ip(value: str) -> bool:
    """Адрес, по которому вообще можно кого-то узнать.

    За обратным прокси или CDN панель пишет внутренний адрес — он одинаковый
    у всех клиентов, и уликой быть не может.
    """
    import ipaddress
    try:
        ip = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast)


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
    from panel import is_configured
    if not is_configured():
        return
    batch = await _subs_slice(int(cfg.get("fraud_batch", 8) or 8))
    for _sub_id, tg_id, email, times_renewed in batch:
        await scan_sub(context, tg_id, email, bool(times_renewed))


async def scan_sub(context, tg_id: int, email: str, paid: bool) -> list:
    """Запоминает отпечатки одной подписки и проверяет их на пересечения."""
    from database import remember_fingerprints, fingerprint_owners
    from panel import get_client_hwids, get_client_ips

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

    cfg = load_config()
    if cfg.get("fraud_use_ip", True):
        ips = await get_client_ips(email)
        if ips.get("ok"):
            values = [i["ip"] for i in ips["items"]
                      if i.get("ip") and is_public_ip(i["ip"])]
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
    from database import note_fraud_pair

    if not await note_fraud_pair(tg_id, other_tg, kind, value):
        return False

    if kind == "hwid":
        head = "🕵 <b>Одно устройство на двух аккаунтах</b>"
        note = "Совпал идентификатор устройства — это один и тот же телефон или компьютер."
    else:
        head = "🕵 <b>Один адрес на двух аккаунтах</b>"
        note = ("Совпал IP-адрес. Улика слабая: общий Wi-Fi, семья или "
                "мобильный оператор дают такое же совпадение.")

    from database import fingerprint_cluster
    cluster = await fingerprint_cluster(kind, value)
    cluster_line = (f"\n👥 Аккаунтов с этим отпечатком: <b>{len(cluster)}</b>"
                    if len(cluster) > 2 else "")

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"{head}\n\n"
            f"{await who_line(tg_id)}\n\n"
            f"{await who_line(other_tg)}\n\n"
            f"<blockquote>{_match_line(kind, value)}{cluster_line}</blockquote>\n\n"
            f"<i>{note}</i>"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 Разобрать",
                                  callback_data=f"fraud_pair:{tg_id}:{other_tg}")],
            [InlineKeyboardButton("⛔ В ЧС первого", callback_data=f"bl_add_for:{tg_id}"),
             InlineKeyboardButton("🙈 Не фрод", callback_data=f"fraud_ok:{tg_id}:{other_tg}")],
        ]),
    )
    from log_channel import send_log
    await send_log(context.bot,
        f"🕵 Совпадение ({kind}): <code>{tg_id}</code> и <code>{other_tg}</code>")
    return True


# ── Кто эти двое ──────────────────────────────────────────────────────────────

async def who_line(tg_id: int) -> str:
    """Короткая справка о человеке: кто, когда пришёл, что с подпиской."""
    from html import escape
    from database import get_user_info, user_fingerprint_stats
    from paidsub.storage import get_paid_sub_by_tg_id
    from paidsub.handlers import _esc_name

    u = await get_user_info(tg_id)
    name = _esc_name(u[1] if u else None, tg_id)
    uname = f" (@{escape(u[2])})" if u and u[2] else ""
    since = f" · с {str(u[3])[:10]}" if u and len(u) > 3 and u[3] else ""

    row = await get_paid_sub_by_tg_id(tg_id)
    if row:
        status = row[11] if len(row) > 11 else "active"
        renewed = row[12] if len(row) > 12 else 0
        kind = "платная" if renewed else "пробная"
        labels = {"active": "активна", "expired": "истекла"}
        sub = f"{kind}, {labels.get(status, status)}, до {str(row[6])[:16]}"
    else:
        sub = "подписки нет"

    marks = await user_fingerprint_stats(tg_id)
    seen = " · ".join(x for x in (
        f"устройств: {marks.get('hwid', 0)}" if marks.get("hwid") else "",
        f"адресов: {marks.get('ip', 0)}" if marks.get("ip") else "") if x)
    return (f"👤 <b>{name}</b>{uname}\n"
            f"<code>{tg_id}</code>{since}\n"
            f"💳 {sub}" + (f"\n🔎 {seen}" if seen else ""))


def _match_line(kind: str, value: str) -> str:
    if kind == "hwid":
        return f"📱 Одно устройство · <code>{value[:24]}</code>"
    if kind == "ip":
        return f"🌐 Один адрес · <code>{value[:40]}</code>"
    return f"🔎 {kind} · <code>{value[:30]}</code>"


# ── Экран в админке ───────────────────────────────────────────────────────────

async def handle_fraud_menu(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import fraud_stats
    cfg = load_config()
    enabled = cfg.get("fraud_enabled", True)
    use_ip = cfg.get("fraud_use_ip", True)
    st = await fraud_stats()
    status = "🟢 включена" if enabled else "🔴 выключена"

    lines = ["🕵 <b>Повторные триалы</b>", "",
             "<blockquote>"
             f"Слежка: <b>{status}</b>\n"
             f"📱 Устройств запомнено: <b>{st['devices']}</b>\n"
             f"🌐 Адресов запомнено: <b>{st['ips']}</b></blockquote>", "",
             "<blockquote>"
             f"🔎 Находок всего: <b>{st['pairs']}</b>\n"
             f"🆕 Не разобрано: <b>{st['new']}</b>\n"
             f"⛔ Закончились блокировкой: <b>{st['blocked']}</b>\n"
             f"🙈 Отмечено «не фрод»: <b>{st['ignored']}</b>"
             + (f"\n👨‍👩‍👧 Устройств на трёх и более аккаунтах: <b>{st['clusters']}</b>"
                if st["clusters"] else "")
             + "</blockquote>", "",
             "<i>Бот по кругу опрашивает панель и запоминает, с каких устройств и "
             "адресов работают подписки. Совпало устройство у двух аккаунтов — "
             "приносит находку сюда. Сам никого не банит: решение за тобой.</i>"]

    kb = [[InlineKeyboardButton("🔴 Выключить" if enabled else "🟢 Включить",
                                callback_data="fraud_toggle"),
           InlineKeyboardButton("🔍 Проверить сейчас", callback_data="fraud_scan")]]
    if st["pairs"]:
        kb.append([InlineKeyboardButton(
            f"📋 Находки{' · 🆕 ' + str(st['new']) if st['new'] else ''}",
            callback_data="fraud_list:new" if st["new"] else "fraud_list:all")])
    kb.append([InlineKeyboardButton(
        f"🌐 Адрес как улика: {'да' if use_ip else 'нет'}", callback_data="fraud_ip_toggle")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_fraud_ip_toggle(query):
    """Адрес — слабая улика: у мобильных операторов и общего Wi-Fi он совпадает
    у чужих людей. Этой кнопкой его можно вовсе перестать учитывать."""
    cfg = load_config()
    cfg["fraud_use_ip"] = not cfg.get("fraud_use_ip", True)
    save_config(cfg)
    await handle_fraud_menu(query)


_KIND_ICON = {"hwid": "📱", "ip": "🌐"}
_STATUS_LABEL = {"new": "🆕", "ignored": "🙈", "blocked": "⛔"}


async def handle_fraud_list(query, which: str = "new"):
    """Список находок с фильтром."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import list_fraud_pairs, get_user_info
    from paidsub.handlers import _esc_name

    status = None if which == "all" else which
    rows = await list_fraud_pairs(status, limit=12)
    titles = {"new": "не разобранные", "ignored": "«не фрод»",
              "blocked": "с блокировкой", "all": "все"}
    lines = [f"📋 <b>Находки — {titles.get(which, which)}</b>", ""]
    kb = []
    if not rows:
        lines.append("<blockquote>Пусто.</blockquote>")
    for tg_a, tg_b, kind, _value, st, created in rows:
        a = await get_user_info(tg_a)
        b = await get_user_info(tg_b)
        a_name = _esc_name(a[1] if a else None, tg_a)
        b_name = _esc_name(b[1] if b else None, tg_b)
        when = str(created)[5:16] if created else ""
        lines.append(f"{_STATUS_LABEL.get(st, '·')} {_KIND_ICON.get(kind, '🔎')} "
                     f"{a_name} ↔ {b_name} · {when}")
        kb.append([InlineKeyboardButton(
            f"{_KIND_ICON.get(kind, '🔎')} {a_name[:14]} ↔ {b_name[:14]}",
            callback_data=f"fraud_pair:{tg_a}:{tg_b}")])

    tabs = [("🆕 Новые", "new"), ("⛔ Блок", "blocked"),
            ("🙈 Не фрод", "ignored"), ("📚 Все", "all")]
    kb.append([InlineKeyboardButton(("• " if key == which else "") + label,
                                    callback_data=f"fraud_list:{key}")
               for label, key in tabs])
    kb.append([InlineKeyboardButton("◀️ К повторным триалам", callback_data="fraud_menu")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_fraud_pair(query, a: int, b: int):
    """Карточка находки: кто эти двое, что совпало и что можно сделать."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import get_fraud_pair, fingerprint_cluster, get_user_info
    from paidsub.handlers import _esc_name
    from paidsub.storage import get_paid_sub_by_tg_id

    pair = await get_fraud_pair(a, b)
    if not pair:
        await query.answer("Находка не найдена", show_alert=True)
        await handle_fraud_list(query, "all")
        return
    tg_a, tg_b, kind, value, status, created = pair

    cluster = await fingerprint_cluster(kind, value)
    others = [c for c in cluster if c[0] not in (tg_a, tg_b)]
    first_seen = min((c[2] for c in cluster if c[2]), default=None)
    last_seen = max((c[3] for c in cluster if c[3]), default=None)

    facts = [_match_line(kind, value)]
    if first_seen:
        facts.append(f"📆 Впервые: {str(first_seen)[:16]} · последний раз: "
                     f"{str(last_seen)[:16]}")
    if others:
        names = []
        for tg_id, _email, _f, _l in others[:4]:
            u = await get_user_info(tg_id)
            names.append(_esc_name(u[1] if u else None, tg_id))
        facts.append(f"👥 Тот же отпечаток ещё у <b>{len(others)}</b>: " + ", ".join(names))
    if kind == "ip":
        facts.append("<i>Адрес — улика слабая: общий Wi-Fi, семья или мобильный "
                     "оператор дают такое же совпадение.</i>")

    state_line = {"new": "🆕 не разобрано", "ignored": "🙈 отмечено «не фрод»",
                  "blocked": "⛔ закончилось блокировкой"}.get(status, status)

    text = ("🕵 <b>Находка</b>\n"
            f"<i>{state_line} · {str(created)[:16]}</i>\n\n"
            f"{await who_line(tg_a)}\n\n"
            f"{await who_line(tg_b)}\n\n"
            "<blockquote>" + "\n".join(facts) + "</blockquote>")

    kb = [[InlineKeyboardButton("👤 Первый", callback_data=f"user_profile:{tg_a}"),
           InlineKeyboardButton("👤 Второй", callback_data=f"user_profile:{tg_b}")],
          [InlineKeyboardButton("⛔ В ЧС первого", callback_data=f"bl_add_for:{tg_a}"),
           InlineKeyboardButton("⛔ В ЧС второго", callback_data=f"bl_add_for:{tg_b}")]]

    # закрыть триал предлагаем только тому, кто ещё ни разу не платил
    for tg_id, label in ((tg_a, "первому"), (tg_b, "второму")):
        row = await get_paid_sub_by_tg_id(tg_id)
        renewed = (row[12] if row and len(row) > 12 else 0)
        status_now = (row[11] if row and len(row) > 11 else "")
        if row and not renewed and status_now != "expired":
            kb.append([InlineKeyboardButton(
                f"🚫 Закрыть триал {label}", callback_data=f"fraud_stop:{tg_id}:{tg_a}:{tg_b}")])

    if status != "ignored":
        kb.append([InlineKeyboardButton("🙈 Не фрод — больше не спрашивать",
                                        callback_data=f"fraud_ok:{tg_a}:{tg_b}")])
    kb.append([InlineKeyboardButton("◀️ К находкам", callback_data="fraud_list:new")])
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_fraud_stop(query, context, tg_id: int, a: int, b: int):
    """Закрывает пробную подписку: срок в прошлое, доступ выключен."""
    from datetime import datetime
    from paidsub.storage import (get_paid_sub_by_tg_id, set_expire_date,
                                 update_paid_sub_field, add_history)
    from panel import update_client_expire, toggle_client
    from database import set_fraud_pair_status
    from log_channel import send_log

    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        await query.answer("Подписки нет", show_alert=True)
        return
    sub_id, email = row[0], row[2]
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    await set_expire_date(sub_id, now)
    await update_paid_sub_field(sub_id, "status", "expired")
    pushed = await update_client_expire(email, now)
    off = await toggle_client(email, False)
    await add_history(tg_id, "trial_stopped", "Триал закрыт: повторная регистрация")
    await set_fraud_pair_status(a, b, "blocked")

    trouble = ""
    if not pushed.get("success"):
        trouble += f" · срок: {pushed.get('error')}"
    if not off.get("success"):
        trouble += f" · отключение: {off.get('error')}"
    await send_log(context.bot,
                   f"🚫 Триал закрыт у <code>{tg_id}</code> (повторная регистрация){trouble}")
    await query.answer("Триал закрыт" + (" · панель ответила с ошибкой" if trouble else ""),
                       show_alert=bool(trouble))
    await handle_fraud_pair(query, a, b)


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
    from database import ignore_fraud_pair, get_fraud_pair
    await ignore_fraud_pair(a, b)
    await query.answer("Больше про эту пару не напомню")
    if await get_fraud_pair(a, b):
        await handle_fraud_pair(query, a, b)
    else:
        await handle_fraud_menu(query)
