"""«Точно?» перед опасными кнопками админки.

Опасная кнопка сначала показывает вопрос: ✅ Да — выполнить, ❌ Нет — вернуться
туда, где её нажали, ◀️ Назад — в раздел выше. Само действие приходит с
приставкой ok: и выполняется только после «Да».
"""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

OK_PREFIX = "ok:"

# Как действие называется в аудите «Контроля»
CONFIRM_TITLES = {
    "paid_sub_delete": "Удаление подписки",
    "sub_delete": "Удаление админской подписки",
    "paid_sub_toggle": "Вкл/выкл подписки",
    "sub_toggle": "Вкл/выкл админской подписки",
    "paid_sub_freeze": "Заморозка подписки",
    "ban_user": "Бан пользователя",
    "promo_delete": "Удаление промокода",
    "helper_del": "Снятие помощника",
    "mnt_toggle": "Вкл/выкл техработ",
    "git_update": "Обновление с GitHub",
    "clear_log_channel": "Отключение лог-канала",
    "bl_del": "Снятие с ЧС",
    "bl_stop": "Остановка подписки из-за ЧС",
    "bl_readd": "Возврат в ЧС",
    "bl_remote_toggle": "Общий ЧС вкл/выкл",
    "paid_hwid_clear": "Очистка устройств подписки",
}


def confirm_title(data: str) -> str | None:
    return CONFIRM_TITLES.get(data.split(":")[0])


def confirm_keyboard(yes_label: str, yes_cb: str, no_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(yes_label, callback_data=yes_cb)],
        [InlineKeyboardButton("❌ Нет", callback_data=no_cb),
         InlineKeyboardButton("◀️ Назад", callback_data=back_cb)],
    ])


async def _who(tg_id) -> str:
    if not tg_id:
        return "без привязки к Telegram"
    from database import get_user_info
    u = await get_user_info(tg_id)
    if not u:
        return f"<code>{tg_id}</code>"
    name = html.escape(u[1] or str(tg_id))
    return (f"{name} (@{html.escape(u[2])})" if u[2] else name) + f" · <code>{tg_id}</code>"


async def _panel_enabled(email) -> bool | None:
    """Включён ли клиент в панели; None — панель не ответила."""
    from xui_api import get_client_info
    try:
        info = await get_client_info(email)
    except Exception:
        return None
    return info.get("enabled", True) if info.get("success") else None


# Каждое правило отдаёт: текст вопроса, надпись «Да», куда «Нет», куда «Назад»

async def _paid_sub_delete(arg):
    from paidsub.storage import get_paid_sub
    row = await get_paid_sub(int(arg))
    who = await _who(row[1]) if row else "?"
    return (f"🗑 <b>Удалить подписку #{arg}?</b>\n\n👤 {who}\n📅 До: {row[6] if row else '?'}\n\n"
            "Клиент удалится из панели 3x-UI, ключ перестанет работать. Отменить это нельзя.",
            "🗑 Да, удалить", f"paid_sub_view:{arg}", "paid_subs")


async def _sub_delete(arg):
    from adminsub.storage import get_sub
    row = await get_sub(int(arg))
    who = await _who(row[1]) if row else "?"
    return (f"🗑 <b>Удалить админскую подписку #{arg}?</b>\n\n👤 {who}\n📅 До: {row[6] if row else '?'}\n\n"
            "Клиент удалится из панели 3x-UI, ключ перестанет работать. Отменить это нельзя.",
            "🗑 Да, удалить", f"sub_view:{arg}", "admin_subs")


async def _toggle(arg, admin_sub: bool):
    if admin_sub:
        from adminsub.storage import get_sub as get_row
    else:
        from paidsub.storage import get_paid_sub as get_row
    row = await get_row(int(arg))
    who = await _who(row[1]) if row else "?"
    enabled = await _panel_enabled(row[2]) if row else None
    kind = "админскую подписку" if admin_sub else "подписку"
    view = f"{'sub_view' if admin_sub else 'paid_sub_view'}:{arg}"
    back = "admin_subs" if admin_sub else "paid_subs"
    if enabled is False:
        return (f"▶️ <b>Включить {kind} #{arg}?</b>\n\n👤 {who}\n\n"
                "VPN у клиента снова заработает. Клиенту придёт уведомление.",
                "▶️ Да, включить", view, back)
    if enabled:
        return (f"⏸ <b>Приостановить {kind} #{arg}?</b>\n\n👤 {who}\n\n"
                "VPN у клиента перестанет работать, пока не включишь обратно. "
                "Клиенту придёт уведомление.",
                "⏸ Да, приостановить", view, back)
    return (f"⏯ <b>Переключить {kind} #{arg}?</b>\n\n👤 {who}\n\n"
            "<i>Панель не ответила — не видно, включена ли она сейчас.</i>",
            "⏯ Да, переключить", view, back)


async def _paid_sub_freeze(arg):
    from paidsub.storage import get_paid_sub
    row = await get_paid_sub(int(arg))
    who = await _who(row[1]) if row else "?"
    return (f"🧊 <b>Заморозить подписку #{arg}?</b>\n\n👤 {who}\n\n"
            "VPN у клиента отключится. Клиенту придёт уведомление о заморозке.",
            "🧊 Да, заморозить", f"paid_sub_view:{arg}", "paid_subs")


async def _ban_user(arg):
    return (f"🚫 <b>Забанить пользователя?</b>\n\n👤 {await _who(int(arg))}\n\n"
            "Пользоваться ботом будет нельзя, пока не разбанишь.",
            "🚫 Да, забанить", f"user_profile:{arg}", "admin_panel")


async def _promo_delete(arg):
    from paidsub.storage import get_promo_by_id, promo_use_count
    p = await get_promo_by_id(int(arg))
    info = (f"🎟 <b>{html.escape(p[1])}</b> · −{p[2]}% · использован {await promo_use_count(p[1])} раз"
            if p else "🎟 ?")
    return (f"🗑 <b>Удалить промокод?</b>\n\n{info}\n\nОтменить это нельзя.",
            "🗑 Да, удалить", f"promo_view:{arg}", "promo_menu")


async def _helper_del(arg):
    return (f"👥 <b>Убрать помощника?</b>\n\n👤 {await _who(int(arg))}\n\n"
            "Доступ к панели поддержки пропадёт сразу.",
            "👥 Да, убрать", "helpers_menu", "admin_panel")


async def _mnt_toggle(arg):
    import maintenance as mnt
    if mnt.is_maintenance():
        return ("✅ <b>Выключить техработы?</b>\n\nБот снова заработает для всех пользователей.",
                "✅ Да, выключить", "mnt_menu", "admin_panel")
    return ("🛠 <b>Включить техработы?</b>\n\n"
            "Пользователи увидят сообщение о работах, бот для них остановится. "
            "На тебя и помощников это не действует.",
            "🛠 Да, включить", "mnt_menu", "admin_panel")


async def _git_update(arg):
    return ("🔄 <b>Обновиться с GitHub?</b>\n\n"
            "Бот скачает код из репозитория и перезапустится — несколько секунд он не будет отвечать.",
            "🔄 Да, обновить", "admin_panel", "admin_panel")


async def _clear_log_channel(arg):
    return ("🗑 <b>Отключить лог-канал?</b>\n\n"
            "События перестанут дублироваться в канал. Вернуть можно, снова указав его ID.",
            "🗑 Да, отключить", "log_channel_settings", "admin_panel")


async def _bl_del(arg):
    from blacklist import entry
    from database import bl_holds
    from paidsub.time_parser import fmt_duration
    tg_id = int(arg)
    e = await entry(tg_id)
    holds = {h[1]: h[3] for h in await bl_holds(tg_id)}
    lines = []
    if holds.get("paid"):
        lines.append(f"Подписка снова заработает, вернётся остаток: {fmt_duration(holds['paid'])}")
    if "admin" in holds:
        lines.append("Админская подписка снова включится.")
    if not lines:
        lines.append("Подписку бот не трогает — возвращать нечего.")
    if e and e["source"] == "remote":
        lines.append("Человек есть в общем списке — бот запомнит исключение, "
                     "и следующее обновление не вернёт его в ЧС.")
    return (f"✅ <b>Убрать из чёрного списка?</b>\n\n👤 {await _who(tg_id)}\n\n" + "\n".join(lines),
            "✅ Да, убрать", f"bl_view:{arg}", "bl_menu")


async def _bl_stop(arg):
    from paidsub.storage import get_paid_sub_by_tg_id
    tg_id = int(arg)
    sub = await get_paid_sub_by_tg_id(tg_id)
    return (f"⛔ <b>Остановить подписку?</b>\n\n👤 {await _who(tg_id)}\n"
            f"💳 Действует до: {sub[6] if sub else '?'}\n\n"
            "VPN отключится сразу. Остаток срока сохранится и вернётся, если убрать человека из ЧС. "
            "Клиенту придёт сообщение, что доступ закрыт.",
            "⛔ Да, остановить", f"bl_view:{arg}", "bl_menu")


async def _bl_readd(arg):
    from database import bl_lookup
    from paidsub.storage import get_paid_sub_by_tg_id
    tg_id = int(arg)
    info = await bl_lookup(tg_id)
    sub = await get_paid_sub_by_tg_id(tg_id)
    sub_line = (f"💳 Подписка до {sub[6]} остановится сразу, остаток срока сохранится."
                if sub and sub[11] in ("active", "renewal") else "💳 Действующей подписки нет.")
    return (f"⛔ <b>Вернуть в чёрный список?</b>\n\n👤 {await _who(tg_id)}\n"
            f"📝 Причина из общего списка: {html.escape(info.get('remote') or '—')}\n{sub_line}",
            "⛔ Да, вернуть", f"bl_view:{arg}", "bl_menu")


async def _bl_remote_toggle(arg):
    from blacklist import remote_on
    if remote_on():
        return ("🌐 <b>Выключить общий список?</b>\n\n"
                "Люди из него снова смогут брать триал и платить, остановленные из-за него "
                "подписки вернутся. Твои ручные записи продолжат действовать.",
                "🌐 Да, выключить", "bl_menu", "admin_panel")
    return ("🌐 <b>Включить общий список?</b>\n\n"
            "Бот сразу его обновит. Триалы твоих пользователей из списка остановятся, "
            "про оплаченные подписки бот спросит тебя.",
            "🌐 Да, включить", "bl_menu", "admin_panel")


async def _paid_hwid_clear(arg):
    from paidsub.storage import get_paid_sub
    row = await get_paid_sub(int(arg))
    who = await _who(row[1]) if row else "?"
    return (f"🧹 <b>Очистить все устройства?</b>\n\n👤 {who}\n\n"
            "Панель забудет все запомненные устройства этой подписки. "
            "Клиенту придётся подключить их заново — сообщение об этом бот пришлёт.",
            "🧹 Да, очистить", f"paid_devices:{arg}", f"paid_sub_view:{arg}")


RULES = {
    "paid_hwid_clear": _paid_hwid_clear,
    "paid_sub_delete": _paid_sub_delete,
    "sub_delete": _sub_delete,
    "paid_sub_toggle": lambda arg: _toggle(arg, admin_sub=False),
    "sub_toggle": lambda arg: _toggle(arg, admin_sub=True),
    "paid_sub_freeze": _paid_sub_freeze,
    "ban_user": _ban_user,
    "promo_delete": _promo_delete,
    "helper_del": _helper_del,
    "mnt_toggle": _mnt_toggle,
    "git_update": _git_update,
    "clear_log_channel": _clear_log_channel,
    "bl_del": _bl_del,
    "bl_stop": _bl_stop,
    "bl_readd": _bl_readd,
    "bl_remote_toggle": _bl_remote_toggle,
}


async def confirm_gate(query, data: str) -> str | None:
    """Что выполнять дальше; None — показан вопрос или подтверждать нечего."""
    confirmed = data.startswith(OK_PREFIX)
    target = data[len(OK_PREFIX):] if confirmed else data
    key, _, arg = target.partition(":")
    rule = RULES.get(key)
    if confirmed:
        # «Да» пропускает только то, что правда требует подтверждения
        return target if rule else None
    if not rule:
        return data
    try:
        text, yes, no_cb, back_cb = await rule(arg)
    except Exception:
        # не смогли собрать подробности — всё равно спрашиваем
        text, yes, no_cb, back_cb = ("⚠️ <b>Точно выполнить это действие?</b>",
                                     "✅ Да", "admin_panel", "admin_panel")
    await query.edit_message_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=confirm_keyboard(yes, OK_PREFIX + target, no_cb, back_cb),
    )
    return None
