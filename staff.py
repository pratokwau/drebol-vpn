"""Помощники: люди с частью админских прав.

Каждому помощнику права выдаются поштучно: тикеты, карточки пользователей,
подписки, оплаты, промокоды, чёрный список, рассылки, статистика. Что не
выдано — то закрыто: и кнопки, и ввод текстом. Всё, что помощник делает,
видно в «🛰 Контроль → Аудит админки».

Права заданы белым списком кнопок. Новая кнопка в админке помощнику по
умолчанию недоступна, пока её не впишут в нужное право, — так безопаснее.
"""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID, load_config, save_config
from states import (
    AWAITING_ADMIN_REPLY, AWAITING_DM_USER, AWAITING_FIND_USER, AWAITING_HELPER_ID,
    AWAITING_PAID_SUB_EXTEND, AWAITING_PAID_SUB_REDUCE, AWAITING_QUICK_REPLY,
    AWAITING_PROMO_GIVE_USER, AWAITING_PROMO_CUSTOM,
    AWAITING_BL_ADD, AWAITING_BL_REASON, AWAITING_BL_CHECK,
    AWAITING_BROADCAST, AWAITING_BROADCAST_BUTTONS, AWAITING_BROADCAST_PHOTO,
)

# Что открыто каждому помощнику независимо от прав: вход в панель и выход из неё
BASE_EXACT = {"admin_panel", "back_start", "noop", "helper_panel"}

# Права: ключ → что открывает. exact — точные кнопки, prefix — начала
# callback'ов, states — ввод текстом, который эти кнопки запускают.
PERMS = {
    "tickets": {
        "label": "🎫 Тикеты",
        "hint": "читать обращения и отвечать в поддержке",
        "exact": set(),
        "prefix": ("ticket_list:", "ticket_view:", "ticket_files:", "ticket_reply:",
                   "ticket_tab:", "ticket_quick:", "ticket_send:", "ticket_close:",
                   "quick_menu", "quick_add", "quick_del:"),
        "states": {AWAITING_ADMIN_REPLY, AWAITING_QUICK_REPLY},
        "button": ("🎫 Тикеты", "ticket_list:1"),
    },
    "users": {
        "label": "🔍 Карточки людей",
        "hint": "искать пользователя и смотреть его карточку",
        "exact": {"find_user"},
        "prefix": ("user_profile:", "user_activity:"),
        "states": {AWAITING_FIND_USER},
        "button": ("🔍 Найти юзера", "find_user"),
    },
    "dm": {
        "label": "✉️ Писать людям",
        "hint": "отправить сообщение пользователю из его карточки",
        "exact": set(),
        "prefix": ("dm_user:",),
        "states": {AWAITING_DM_USER},
        "button": None,
    },
    "subs": {
        "label": "💳 Подписки — смотреть",
        "hint": "список подписок, карточка, устройства и адреса",
        "exact": {"paid_subs", "paid_requests"},
        "prefix": ("paid_subs:", "paid_sub_view:", "paid_devices:", "paid_ips:",
                   "paid_history", "paid_history_page:", "paid_history_view:"),
        "states": set(),
        "button": ("💳 Подписки", "paid_subs"),
    },
    "subs_edit": {
        "label": "🛠 Подписки — менять",
        "hint": "продлевать и убавлять срок, включать, отключать устройства",
        "exact": set(),
        "prefix": ("paid_sub_extend:", "paid_sub_reduce:", "paid_sub_toggle:",
                   "paid_hwid_del:", "paid_hwid_clear:"),
        "states": {AWAITING_PAID_SUB_EXTEND, AWAITING_PAID_SUB_REDUCE},
        "button": None,
    },
    "payments": {
        "label": "💰 Оплаты",
        "hint": "смотреть платежи и их карточки",
        "exact": set(),
        "prefix": ("payments:", "payment_view:", "payment_stats:"),
        "states": set(),
        "button": ("💰 Оплаты", "payments:paid:1"),
    },
    "promos": {
        "label": "🎟 Промокоды",
        "hint": "выдавать промокоды людям",
        "exact": {"promos_menu"},
        "prefix": ("promo_view:", "promo_give_for:", "promo_give_do:",
                   "promo_give_custom:", "promo_income"),
        "states": {AWAITING_PROMO_GIVE_USER, AWAITING_PROMO_CUSTOM},
        "button": ("🎟 Промокоды", "promos_menu"),
    },
    "blacklist": {
        "label": "⛔ Чёрный список",
        "hint": "добавлять и снимать из чёрного списка",
        "exact": {"bl_menu", "bl_list", "bl_add_start"},
        "prefix": ("bl_view:", "bl_add_for:", "bl_del:", "bl_readd:", "bl_list:"),
        "states": {AWAITING_BL_ADD, AWAITING_BL_REASON, AWAITING_BL_CHECK},
        "button": ("⛔ Чёрный список", "bl_menu"),
    },
    "broadcast": {
        "label": "📣 Рассылки",
        "hint": "отправлять рассылки всем или сегменту",
        "exact": {"broadcast"},
        "prefix": ("broadcast_segment:", "bcast_"),
        "states": {AWAITING_BROADCAST, AWAITING_BROADCAST_BUTTONS, AWAITING_BROADCAST_PHOTO},
        "button": ("📣 Рассылка", "broadcast"),
    },
    "stats": {
        "label": "📊 Статистика",
        "hint": "сводка по деньгам и людям, кто онлайн, трафик",
        "exact": {"dashboard", "ctl_menu", "ctl_online", "ctl_traffic", "ctl_feed"},
        "prefix": ("ctl_feed:", "payment_stats:"),
        "states": set(),
        "button": ("📊 Статистика", "dashboard"),
    },
}

# Что получает помощник, добавленный до появления прав
DEFAULT_PERMS = ("tickets", "users", "dm")

# Все состояния помощников — из них messages.py узнаёт, что ввод не пользовательский
HELPER_STATES = {st for p in PERMS.values() for st in p["states"]}


def helper_ids() -> list[int]:
    out = []
    for v in load_config().get("helper_ids") or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def is_helper(uid: int) -> bool:
    return uid != ADMIN_ID and uid in helper_ids()


def is_staff(uid: int) -> bool:
    return uid == ADMIN_ID or is_helper(uid)


def helper_perms(uid: int) -> set:
    """Права помощника. У добавленных раньше — набор по умолчанию."""
    if uid == ADMIN_ID:
        return set(PERMS)
    stored = (load_config().get("helper_perms") or {}).get(str(uid))
    if stored is None:
        return set(DEFAULT_PERMS)
    return {p for p in stored if p in PERMS}


def set_helper_perms(uid: int, perms) -> None:
    cfg = load_config()
    all_perms = cfg.get("helper_perms") or {}
    all_perms[str(uid)] = sorted(p for p in perms if p in PERMS)
    cfg["helper_perms"] = all_perms
    save_config(cfg)


def toggle_helper_perm(uid: int, perm: str) -> set:
    perms = helper_perms(uid)
    perms.discard(perm) if perm in perms else perms.add(perm)
    set_helper_perms(uid, perms)
    return perms


def helper_can(data: str, uid: int) -> bool:
    """Открыта ли помощнику эта кнопка."""
    if data in BASE_EXACT:
        return True
    for key in helper_perms(uid):
        rule = PERMS[key]
        if data in rule["exact"] or data.startswith(rule["prefix"]):
            return True
    return False


def helper_states(uid: int) -> set:
    """Какой ввод текстом помощнику разрешён."""
    out = set()
    for key in helper_perms(uid):
        out |= PERMS[key]["states"]
    return out


def staff_chat_ids(perm: str = "tickets") -> list[int]:
    """Кому слать уведомления. По умолчанию — тем, кто ведёт тикеты."""
    return [ADMIN_ID] + [h for h in helper_ids()
                         if h != ADMIN_ID and perm in helper_perms(h)]


def _save_ids(ids: list[int]):
    cfg = load_config()
    cfg["helper_ids"] = ids
    save_config(cfg)


def _forget(uid: int):
    cfg = load_config()
    ids = [h for h in helper_ids() if h != uid]
    cfg["helper_ids"] = ids
    perms = cfg.get("helper_perms") or {}
    perms.pop(str(uid), None)
    cfg["helper_perms"] = perms
    save_config(cfg)


def _name(u, uid) -> str:
    if not u:
        return f"<code>{uid}</code>"
    fn = html.escape(u[1] or str(uid))
    return f"{fn} (@{html.escape(u[2])})" if u[2] else fn


# ── Панель помощника ─────────────────────────────────────────────────────────

async def handle_helper_panel(query):
    """Меню помощника: только то, на что у него есть права."""
    from database import get_unread_tickets_count
    uid = query.from_user.id
    perms = helper_perms(uid)

    rows, pair = [], []
    for key, rule in PERMS.items():
        if key not in perms or not rule["button"]:
            continue
        label, cb = rule["button"]
        if key == "tickets":
            unread = await get_unread_tickets_count()
            if unread:
                label = f"🎫 Тикеты · 🔴 {unread}"
        pair.append(InlineKeyboardButton(label, callback_data=cb))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])

    what = [PERMS[k]["label"] for k in PERMS if k in perms]
    await query.edit_message_text(
        "🛡 <b>Панель поддержки</b>\n\n"
        + ("<blockquote>Доступно:\n" + "\n".join(f"· {w}" for w in what) + "</blockquote>\n\n"
           if what else "<blockquote>Прав пока не выдано — напиши администратору.</blockquote>\n\n")
        + "<i>Остальные разделы закрыты. Всё, что ты делаешь, видит администратор.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── Управление помощниками (только админ) ────────────────────────────────────

async def handle_helpers_menu(query, context=None):
    if context:
        context.user_data.pop("state", None)
    from database import get_user_info
    ids = helper_ids()
    lines = ["👥 <b>Помощники</b>", ""]
    kb = []
    if ids:
        people = []
        for uid in ids:
            u = await get_user_info(uid)
            perms = helper_perms(uid)
            people.append(f"🛡 {_name(u, uid)} · прав: <b>{len(perms)}</b>")
            label = (u[1] if u and u[1] else str(uid))[:20]
            kb.append([InlineKeyboardButton(f"⚙️ {label} · {len(perms)} прав",
                                            callback_data=f"helper_card:{uid}")])
        lines.append("<blockquote>" + "\n".join(people) + "</blockquote>")
    else:
        lines.append("<blockquote>Пока никого.</blockquote>")
    lines += ["", "<i>Права выдаются поштучно: тикеты, карточки людей, подписки, "
              "оплаты, промокоды, чёрный список, рассылки, статистика. Что не выдано — "
              "закрыто. Действия помощников видны в 🛰 Контроль → Аудит админки.</i>"]
    kb.append([InlineKeyboardButton("➕ Добавить помощника", callback_data="helper_add")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_helper_card(query, uid: int):
    """Карточка помощника: что ему открыто, и переключатели прав."""
    from database import get_user_info
    if not is_helper(uid):
        await query.answer("Этот человек больше не помощник", show_alert=True)
        await handle_helpers_menu(query)
        return
    u = await get_user_info(uid)
    perms = helper_perms(uid)

    kb = []
    for key, rule in PERMS.items():
        on = key in perms
        kb.append([InlineKeyboardButton(
            f"{'✅' if on else '🔘'} {rule['label']}",
            callback_data=f"helper_perm:{uid}:{key}")])
    kb.append([InlineKeyboardButton("🗑 Убрать помощника", callback_data=f"helper_del:{uid}")])
    kb.append([InlineKeyboardButton("◀️ К помощникам", callback_data="helpers_menu")])

    hints = "\n".join(f"· {PERMS[k]['label']} — {PERMS[k]['hint']}" for k in PERMS if k in perms)
    await query.edit_message_text(
        f"🛡 <b>{_name(u, uid)}</b>\n<code>{uid}</code>\n\n"
        + ("<blockquote>" + hints + "</blockquote>\n\n" if hints
           else "<blockquote>Прав не выдано — панель поддержки у него пустая.</blockquote>\n\n")
        + "<i>Нажми на право, чтобы выдать или снять. Изменения действуют сразу.</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_helper_perm(query, context, uid: int, perm: str):
    if perm not in PERMS:
        await query.answer("Неизвестное право", show_alert=True)
        return
    perms = toggle_helper_perm(uid, perm)
    on = perm in perms
    await query.answer(f"{PERMS[perm]['label']}: {'выдано' if on else 'снято'}")

    # незаконченный ввод по снятому праву больше не должен сработать
    if not on and context is not None:
        ud = context.application.user_data.get(uid)
        if ud is not None and ud.get("state") in PERMS[perm]["states"]:
            ud.pop("state", None)

    if context is not None:
        from database import get_user_info
        from log_channel import send_log
        u = await get_user_info(uid)
        await send_log(context.bot,
                       f"👥 {_name(u, uid)}: {PERMS[perm]['label']} — "
                       f"{'выдано' if on else 'снято'}")
    await handle_helper_card(query, uid)


async def handle_helper_add(query, context):
    context.user_data["state"] = AWAITING_HELPER_ID
    await query.edit_message_text(
        "➕ <b>Новый помощник</b>\n\n"
        "Пришли его Telegram ID или @username.\n\n"
        "<i>Он должен хотя бы раз запустить бота командой /start. "
        "Права выдашь сразу после добавления.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="helpers_menu")],
        ]),
    )


async def handle_helper_input(update, context, text: str):
    from database import get_user_info, find_user_by_username
    back = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К помощникам", callback_data="helpers_menu")]])
    raw = text.strip()
    u = await get_user_info(int(raw)) if raw.isdigit() else await find_user_by_username(raw)
    if not u:
        # ввод не сбрасываем — можно сразу прислать ещё раз
        await update.message.reply_text(
            "🔍 <b>Такого пользователя нет в базе бота</b>\n\n"
            "<i>Пусть сначала нажмёт /start, потом пришли ID или @username ещё раз.</i>",
            parse_mode="HTML", reply_markup=back,
        )
        return
    uid = u[0]
    if uid == ADMIN_ID:
        await update.message.reply_text("😎 <b>У тебя и так полный доступ</b>", parse_mode="HTML",
                                        reply_markup=back)
        return
    context.user_data.pop("state", None)
    ids = helper_ids()
    if uid in ids:
        await update.message.reply_text(f"ℹ️ <b>{_name(u, uid)}</b> уже помощник.",
                                        parse_mode="HTML", reply_markup=back)
        return
    _save_ids(ids + [uid])
    set_helper_perms(uid, DEFAULT_PERMS)

    note = ""
    try:
        await context.bot.send_message(
            chat_id=uid,
            text=(
                "🛡 <b>Вам выдан доступ помощника</b>\n\n"
                "<blockquote>Сюда будут приходить новые обращения в поддержку — отвечать "
                "можно прямо из уведомления.</blockquote>\n\n"
                "<i>Панель поддержки есть в главном меню.</i>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛡 Панель поддержки", callback_data="admin_panel")],
            ]),
        )
    except Exception:
        note = "\n\n⚠️ <i>Написать ему не удалось — возможно, он заблокировал бота.</i>"

    from log_channel import send_log
    await send_log(context.bot, f"👥 Новый помощник: {_name(u, uid)} · <code>{uid}</code>")
    await update.message.reply_text(
        f"✅ <b>{_name(u, uid)}</b> теперь помощник.\n\n"
        "<blockquote>Выдано по умолчанию: тикеты, карточки людей, сообщения людям.</blockquote>"
        + note,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Настроить права", callback_data=f"helper_card:{uid}")],
            [InlineKeyboardButton("◀️ К помощникам", callback_data="helpers_menu")],
        ]),
    )


async def handle_helper_del(query, context, uid: int):
    ids = helper_ids()
    if uid in ids:
        _forget(uid)
        # начатый ответ или поиск не должен сработать после снятия доступа
        ud = context.application.user_data.get(uid)
        if ud is not None:
            ud.pop("state", None)
        from database import get_user_info
        from log_channel import send_log
        u = await get_user_info(uid)
        await send_log(context.bot, f"👥 Помощник убран: {_name(u, uid)} · <code>{uid}</code>")
        try:
            await context.bot.send_message(chat_id=uid, text="🛡 <b>Доступ помощника снят</b>",
                                           parse_mode="HTML")
        except Exception:
            pass
    await handle_helpers_menu(query)
