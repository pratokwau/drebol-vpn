"""Помощники: люди с частью админских прав.

Каждому помощнику права выдаются поштучно: карточки пользователей,
подписки, оплаты, промокоды, чёрный список, рассылки, статистика. Что не
выдано — то закрыто: и кнопки, и ввод текстом. Всё, что помощник делает,
видно в «📜 Логи → Аудит админки».

Права заданы белым списком кнопок. Новая кнопка в админке помощнику по
умолчанию недоступна, пока её не впишут в нужное право, — так безопаснее.
"""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID, load_config, save_config
from core.states import (
    AWAITING_DM_USER, AWAITING_FIND_USER, AWAITING_HELPER_ID,
    AWAITING_PAID_SUB_EXTEND, AWAITING_PAID_SUB_REDUCE,
    AWAITING_PROMO_GIVE_USER, AWAITING_PROMO_CUSTOM,
    AWAITING_BL_ADD, AWAITING_BL_REASON, AWAITING_BL_CHECK, AWAITING_BL_UNTIL,
    AWAITING_BROADCAST, AWAITING_BROADCAST_BUTTONS, AWAITING_BROADCAST_PHOTO,
    AWAITING_LOG_FILTER_USER, AWAITING_LOG_FILTER_DATE, AWAITING_LOG_EXPORT_USER,
)

# Что открыто каждому помощнику независимо от прав: вход в панель и выход из неё
BASE_EXACT = {"admin_panel", "back_start", "noop", "helper_panel"}

# Права: ключ → что открывает. exact — точные кнопки, prefix — начала
# callback'ов, states — ввод текстом, который эти кнопки запускают.
PERMS = {
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
    "support": {
        "label": "🛟 Поддержка",
        "hint": "отвечать людям в группе поддержки; нужно состоять в группе — приглашение выдаёт бот",
        "exact": {"helper_support"},
        "prefix": (),
        "states": set(),
        "button": ("🛟 Поддержка", "helper_support"),
    },
    "subs": {
        "label": "💳 Подписки — смотреть",
        "hint": "список подписок, карточка, устройства и адреса",
        "exact": {"paid_subs"},
        "prefix": ("paid_subs:", "paid_sub_view:", "paid_devices:", "paid_ips:",
                   "ctl_hist:"),
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
        "exact": {"promo_menu", "promo_give", "promo_income"},
        "prefix": ("promo_view:", "promo_give_for:", "promo_give_do:",
                   "promo_give_custom:", "promo_give_pick:", "promo_list:",
                   "promo_uses:", "promo_income"),
        "states": {AWAITING_PROMO_GIVE_USER, AWAITING_PROMO_CUSTOM},
        "button": ("🎟 Промокоды", "promo_menu"),
    },
    "blacklist": {
        "label": "⛔ Чёрный список",
        "hint": "добавлять и снимать из чёрного списка",
        "exact": {"bl_menu", "bl_list", "bl_add_start", "bl_add", "bl_check", "bl_add_apply"},
        "prefix": ("bl_view:", "bl_add_for:", "bl_del:", "bl_readd:", "bl_list:",
                   "bl_reason:", "bl_term:"),
        "states": {AWAITING_BL_ADD, AWAITING_BL_REASON, AWAITING_BL_CHECK,
                   AWAITING_BL_UNTIL},
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
        "exact": {"dashboard", "ctl_menu", "ctl_online", "ctl_feed", "log_storage_menu"},
        "prefix": ("act_f", "user_feed:", "ctl_hist:", "payment_stats:", "log_export"),
        "states": {AWAITING_LOG_FILTER_USER, AWAITING_LOG_FILTER_DATE,
                   AWAITING_LOG_EXPORT_USER},
        "button": ("📊 Статистика", "dashboard"),
    },
}

# Что получает помощник, добавленный до появления прав
DEFAULT_PERMS = ("users", "dm", "support")

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


# ── Группа поддержки: доступ помощников ──────────────────────────────────────
# Поддержка живёт в форум-группе: бот поддержки копирует ответы из тем
# пользователям, поэтому отвечать может любой участник группы. Барьер у
# помощника один — он не состоит в группе. Бот — админ группы и выдаёт
# одноразовые приглашения; членство проверяется через getChatMember.

def support_group_id() -> int:
    try:
        return int(load_config().get("support_group_id") or 0)
    except (TypeError, ValueError):
        return 0


def group_open_url(group_id: int) -> str:
    """Ссылка на приватную группу для тех, кто уже состоит в ней."""
    s = str(group_id)
    return f"https://t.me/c/{s[4:]}" if s.startswith("-100") else ""


async def support_member_status(bot, uid: int) -> str:
    """in / out / no_group / unknown — состоит ли человек в группе поддержки."""
    gid = support_group_id()
    if not gid:
        return "no_group"
    try:
        m = await bot.get_chat_member(chat_id=gid, user_id=uid)
    except Exception:
        return "unknown"
    status = getattr(m, "status", "")
    status = str(getattr(status, "value", status))
    if status in ("member", "administrator", "creator"):
        return "in"
    if status == "restricted" and getattr(m, "is_member", False):
        return "in"
    return "out"


async def kick_from_support_group(bot, uid: int) -> bool:
    """Вывести человека из группы поддержки (при снятии помощника).

    ban+unban = выгон без вечного бана: если его снова добавят
    помощником, он сможет вступить по новому приглашению. Админов
    группы Telegram выгнать не даст — вернётся False.
    """
    gid = support_group_id()
    if not gid:
        return False
    if await support_member_status(bot, uid) != "in":
        return False
    try:
        await bot.ban_chat_member(chat_id=gid, user_id=uid)
        await bot.unban_chat_member(chat_id=gid, user_id=uid, only_if_banned=True)
        return True
    except Exception:
        return False


async def make_support_invite(bot, uid: int) -> str | None:
    """Одноразовая ссылка-приглашение в группу поддержки для помощника."""
    gid = support_group_id()
    if not gid:
        return None
    try:
        link = await bot.create_chat_invite_link(
            chat_id=gid, name=f"Помощник {uid}"[:32], member_limit=1)
        return link.invite_link
    except Exception:
        return None


async def handle_helper_support(query, context=None):
    """Экран помощника «Поддержка»: статус в группе и вход в неё."""
    uid = query.from_user.id
    bot = context.bot if context is not None else query.bot
    gid = support_group_id()
    back = [InlineKeyboardButton("◀️ В панель", callback_data="helper_panel")]
    if not gid:
        await query.edit_message_text(
            "🛟 <b>Поддержка</b>\n\n"
            "<i>Группа поддержки ещё не настроена — скажи администратору.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([back]))
        return
    status = await support_member_status(bot, uid)
    if status == "in":
        rows = []
        url = group_open_url(gid)
        if url:
            rows.append([InlineKeyboardButton("💬 Открыть группу поддержки", url=url)])
        rows.append([InlineKeyboardButton("🔄 Проверить снова", callback_data="helper_support")])
        rows.append(back)
        await query.edit_message_text(
            "🛟 <b>Поддержка</b>\n\n"
            "✅ <b>Вы в группе поддержки.</b>\n\n"
            "<i>Обращения людей лежат в темах группы: открывай тему и отвечай "
            "прямо в ней — бот поддержки сам доставит ответ человеку. "
            "Команда /close в теме закрывает обращение.</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
        return
    invite = await make_support_invite(bot, uid)
    rows = []
    if invite:
        rows.append([InlineKeyboardButton("📩 Вступить в группу поддержки", url=invite)])
    rows.append([InlineKeyboardButton("🔄 Я вступил — проверить", callback_data="helper_support")])
    rows.append(back)
    await query.edit_message_text(
        "🛟 <b>Поддержка</b>\n\n"
        "⚠️ <b>Вы пока не в группе поддержки</b>, а обращения людей лежат именно там.\n\n"
        + ("<i>Нажми кнопку ниже — это одноразовое приглашение лично для тебя. "
           "Вступишь — и сможешь отвечать людям в темах группы.</i>"
           if invite else
           "<i>Не удалось создать приглашение (бот должен быть админом группы). "
           "Напиши администратору — он пришлёт ссылку вручную.</i>"),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


# ── Панель помощника ─────────────────────────────────────────────────────────

async def handle_helper_panel(query):
    """Меню помощника: только то, на что у него есть права."""
    uid = query.from_user.id
    perms = helper_perms(uid)

    rows, pair = [], []
    for key, rule in PERMS.items():
        if key not in perms or not rule["button"]:
            continue
        label, cb = rule["button"]
        pair.append(InlineKeyboardButton(label, callback_data=cb))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="back_start")])

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
    from core.database import get_user_info
    ids = helper_ids()
    lines = ["👥 <b>Помощники</b>", ""]
    kb = []
    if ids:
        bot = context.bot if context is not None else query.bot
        people = []
        for uid in ids:
            u = await get_user_info(uid)
            perms = helper_perms(uid)
            st = await support_member_status(bot, uid)
            badge = {"in": " · 🟢 в группе", "out": " · ⚪ нет в группе"}.get(st, "")
            people.append(f"🛡 {_name(u, uid)} · прав: <b>{len(perms)}</b>{badge}")
            label = (u[1] if u and u[1] else str(uid))[:20]
            kb.append([InlineKeyboardButton(f"⚙️ {label} · {len(perms)} прав",
                                            callback_data=f"helper_card:{uid}")])
        lines.append("<blockquote>" + "\n".join(people) + "</blockquote>")
    else:
        lines.append("<blockquote>Пока никого.</blockquote>")
    lines += ["", "<i>Права выдаются поштучно: карточки людей, подписки, "
              "оплаты, промокоды, чёрный список, рассылки, статистика, поддержка. "
              "Для поддержки помощник должен состоять в группе — приглашение "
              "выдаётся в его карточке. Что не выдано — закрыто. Действия "
              "помощников видны в 📜 Логи → Аудит админки.</i>"]
    kb.append([InlineKeyboardButton("➕ Добавить помощника", callback_data="helper_add")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_helper_card(query, uid: int, context=None):
    """Карточка помощника: что ему открыто, переключатели прав, группа."""
    from core.database import get_user_info
    if not is_helper(uid):
        await query.answer("Этот человек больше не помощник", show_alert=True)
        await handle_helpers_menu(query)
        return
    u = await get_user_info(uid)
    perms = helper_perms(uid)
    bot = context.bot if context is not None else query.bot
    st = await support_member_status(bot, uid)
    group_line = {
        "in": "🟢 <b>В группе поддержки</b> — может отвечать людям в темах.",
        "out": "⚪ <b>Не в группе поддержки</b> — отвечать людям не сможет, пока не вступит.",
        "no_group": "⚠️ Группа поддержки не настроена.",
        "unknown": "❔ Статус в группе поддержки не проверился.",
    }[st]

    kb = []
    for key, rule in PERMS.items():
        on = key in perms
        kb.append([InlineKeyboardButton(
            f"{'✅' if on else '🔘'} {rule['label']}",
            callback_data=f"helper_perm:{uid}:{key}")])
    if st == "out":
        kb.append([InlineKeyboardButton("📩 Пригласить в группу поддержки",
                                        callback_data=f"helper_invite:{uid}")])
    kb.append([InlineKeyboardButton("🗑 Убрать помощника", callback_data=f"helper_del:{uid}")])
    kb.append([InlineKeyboardButton("◀️ К помощникам", callback_data="helpers_menu")])

    hints = "\n".join(f"· {PERMS[k]['label']} — {PERMS[k]['hint']}" for k in PERMS if k in perms)
    await query.edit_message_text(
        f"🛡 <b>{_name(u, uid)}</b>\n<code>{uid}</code>\n\n{group_line}\n\n"
        + ("<blockquote>" + hints + "</blockquote>\n\n" if hints
           else "<blockquote>Прав не выдано — панель поддержки у него пустая.</blockquote>\n\n")
        + "<i>Нажми на право, чтобы выдать или снять. Изменения действуют сразу.</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_helper_invite(query, context, uid: int):
    """Админ: создать приглашение в группу и отправить его помощнику."""
    from core.database import get_user_info
    bot = context.bot if context is not None else query.bot
    invite = await make_support_invite(bot, uid)
    if not invite:
        await query.answer("Не удалось создать приглашение: группа не настроена "
                           "или бот не админ в ней", show_alert=True)
        return
    u = await get_user_info(uid)
    sent = False
    try:
        await bot.send_message(
            chat_id=uid,
            text=("🛟 <b>Приглашение в группу поддержки Drebol VPN</b>\n\n"
                  "<i>В группе лежат обращения людей. Вступи — и сможешь отвечать "
                  "им прямо в темах: бот поддержки доставит ответ человеку. "
                  "Ссылка одноразовая, только для тебя.</i>"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Вступить в группу поддержки", url=invite)],
            ]))
        sent = True
    except Exception:
        sent = False
    from core.log_channel import send_log
    await send_log(bot, f"👥 Приглашение в группу поддержки → {_name(u, uid)} · <code>{uid}</code>")
    await query.answer(
        "Приглашение отправлено помощнику в личку" if sent else
        "Он не запускал бота — перешли ему ссылку вручную (см. карточку)",
        show_alert=True)
    if not sent:
        # бот не достучался — покажем ссылку админу прямо в карточке
        await query.edit_message_text(
            f"📩 <b>Приглашение для {_name(u, uid)}</b>\n\n<code>{invite}</code>\n\n"
            "<i>Бот не смог написать ему сам (не запускал бота или заблокировал). "
            "Перешли ссылку вручную — она одноразовая.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К карточке", callback_data=f"helper_card:{uid}")],
            ]))
        return
    await handle_helper_card(query, uid, context)


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
        from core.database import get_user_info
        from core.log_channel import send_log
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
    from core.database import get_user_info, find_user_by_username
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
    invite = await make_support_invite(context.bot, uid)
    rows = []
    if invite:
        rows.append([InlineKeyboardButton("📩 Вступить в группу поддержки", url=invite)])
    rows.append([InlineKeyboardButton("🛡 Панель поддержки", callback_data="admin_panel")])
    try:
        await context.bot.send_message(
            chat_id=uid,
            text=(
                "🛡 <b>Вам выдан доступ помощника Drebol VPN</b>\n\n"
                "<blockquote>Поддержка живёт в отдельной группе: там лежат обращения "
                "людей по темам. Вступи в группу по кнопке ниже — и сможешь отвечать "
                "людям прямо в темах, бот поддержки доставит ответ человеку.</blockquote>\n\n"
                "<i>Панель помощника — в главном меню бота, раздел «🛟 Поддержка» "
                "покажет твой статус в группе.</i>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except Exception:
        note = "\n\n⚠️ <i>Написать ему не удалось — возможно, он заблокировал бота.</i>"

    from core.log_channel import send_log
    await send_log(context.bot, f"👥 Новый помощник: {_name(u, uid)} · <code>{uid}</code>")
    await update.message.reply_text(
        f"✅ <b>{_name(u, uid)}</b> теперь помощник.\n\n"
        "<blockquote>Выдано по умолчанию: карточки людей, сообщения людям, поддержка. "
        "Приглашение в группу поддержки ушло ему в личку — без группы отвечать "
        "людям он не сможет.</blockquote>"
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
        from core.database import get_user_info
        from core.log_channel import send_log
        u = await get_user_info(uid)
        # из группы поддержки — тоже вон, иначе продолжит отвечать людям
        kicked = await kick_from_support_group(context.bot, uid)
        await send_log(context.bot, f"👥 Помощник убран: {_name(u, uid)} · <code>{uid}</code>"
                       + (" · выведен из группы поддержки" if kicked else ""))
        try:
            await context.bot.send_message(
                chat_id=uid,
                text="🛡 <b>Доступ помощника снят</b>"
                     + ("\n\n<i>Вы также выведены из группы поддержки.</i>" if kicked else ""),
                parse_mode="HTML")
        except Exception:
            pass
    await handle_helpers_menu(query, context)
