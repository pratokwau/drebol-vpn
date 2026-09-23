"""Помощники: второй человек в поддержке с урезанными правами.

Помощник видит тикеты и карточки юзеров, отвечает в поддержке и может
написать юзеру. Оплаты, возвраты, управление подписками, рассылки и настройки
ему недоступны. Права заданы белым списком кнопок: всё, что появится в админке
потом, помощнику по умолчанию закрыто.
"""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID, load_config, save_config
from states import (
    AWAITING_ADMIN_REPLY, AWAITING_DM_USER, AWAITING_FIND_USER, AWAITING_HELPER_ID,
)

# Кнопки, открытые помощнику
HELPER_EXACT = {"admin_panel", "find_user", "back_start"}
HELPER_PREFIXES = (
    "ticket_list:", "ticket_view:", "ticket_files:", "ticket_reply:",
    "ticket_tab:", "ticket_quick:", "ticket_send:", "ticket_close:",
    "user_profile:", "user_activity:", "dm_user:",
)
# Ввод, который помощник запускает этими кнопками
HELPER_STATES = {AWAITING_FIND_USER, AWAITING_ADMIN_REPLY, AWAITING_DM_USER}


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


def helper_can(data: str) -> bool:
    return data in HELPER_EXACT or data.startswith(HELPER_PREFIXES)


def staff_chat_ids() -> list[int]:
    """Кому слать уведомления о новых обращениях."""
    return [ADMIN_ID] + [h for h in helper_ids() if h != ADMIN_ID]


def _save_ids(ids: list[int]):
    cfg = load_config()
    cfg["helper_ids"] = ids
    save_config(cfg)


def _name(u, uid) -> str:
    if not u:
        return f"<code>{uid}</code>"
    fn = html.escape(u[1] or str(uid))
    return f"{fn} (@{html.escape(u[2])})" if u[2] else fn


# ── Панель помощника ─────────────────────────────────────────────────────────

async def handle_helper_panel(query):
    from database import get_unread_tickets_count
    unread = await get_unread_tickets_count()
    tickets = f"🎫 Тикеты · 🔴 {unread}" if unread else "🎫 Тикеты"
    await query.edit_message_text(
        "🛡 <b>Панель поддержки</b>\n\n"
        + (f"<blockquote>🔴 Открытых тикетов: <b>{unread}</b></blockquote>\n\n" if unread
           else "<blockquote>✅ Все обращения разобраны</blockquote>\n\n")
        + "<i>Тикеты и карточки пользователей. Оплаты, подписки и настройки — "
          "у администратора.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tickets, callback_data="ticket_list:1"),
             InlineKeyboardButton("🔍 Найти юзера", callback_data="find_user")],
            [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")],
        ]),
    )


# ── Управление помощниками (только админ) ────────────────────────────────────

async def handle_helpers_menu(query, context=None):
    if context:
        context.user_data.pop("state", None)
    from database import get_user_info
    ids = helper_ids()
    lines = ["👥 <b>Помощники</b>", ""]
    kb = []
    people = []
    for uid in ids:
        u = await get_user_info(uid)
        people.append(f"🛡 {_name(u, uid)} · <code>{uid}</code>")
        label = (u[1] if u and u[1] else str(uid))[:24]
        kb.append([InlineKeyboardButton(f"🗑 Убрать {label}", callback_data=f"helper_del:{uid}")])
    lines.append("<blockquote>" + ("\n".join(people) if people else "Пока никого.") + "</blockquote>")
    lines += ["",
              "<i>Помощник отвечает в поддержке: видит тикеты и карточки юзеров, "
              "может написать юзеру. Оплаты, возвраты, управление подписками, "
              "рассылки и настройки ему недоступны. "
              "Всё, что он делает, видно в 🛰 Контроль → Аудит админки.</i>"]
    kb.append([InlineKeyboardButton("➕ Добавить помощника", callback_data="helper_add")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_helper_add(query, context):
    context.user_data["state"] = AWAITING_HELPER_ID
    await query.edit_message_text(
        "➕ <b>Новый помощник</b>\n\n"
        "Пришли его Telegram ID или @username.\n\n"
        "<i>Он должен хотя бы раз запустить бота командой /start.</i>",
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
    await update.message.reply_text(f"✅ <b>{_name(u, uid)}</b> теперь помощник.{note}",
                                    parse_mode="HTML", reply_markup=back)


async def handle_helper_del(query, context, uid: int):
    ids = helper_ids()
    if uid in ids:
        _save_ids([h for h in ids if h != uid])
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
