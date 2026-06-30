from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from pathlib import Path

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID
from loader import bot

router = Router()

TICKETS_FILE = Path("data/tickets.json")
EXIT_HINT = "\n\n<i>Для выхода введите /cancel</i>"

_admin_active_ticket: int | None = None


def set_admin_active_ticket(ticket_id: int | None) -> None:
    global _admin_active_ticket
    _admin_active_ticket = ticket_id


def get_admin_active_ticket() -> int | None:
    return _admin_active_ticket


class TicketUser(StatesGroup):
    chatting = State()


class TicketAdmin(StatesGroup):
    chatting = State()


def _load() -> dict:
    if not TICKETS_FILE.exists():
        return {"next_id": 1, "tickets": {}}
    try:
        return json.loads(TICKETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"next_id": 1, "tickets": {}}


def _save(data: dict) -> None:
    os.makedirs(TICKETS_FILE.parent, exist_ok=True)
    TICKETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_user_ticket(user_id: int) -> dict | None:
    for ticket in _load()["tickets"].values():
        if ticket["user_id"] == user_id:
            return ticket
    return None


def get_or_create_ticket(user_id: int) -> tuple[dict, bool]:
    existing = get_user_ticket(user_id)
    if existing:
        return existing, False
    data = _load()
    ticket_id = int(data["next_id"])
    ticket = {
        "id": ticket_id,
        "user_id": user_id,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "has_unread": False,
        "messages": [],
    }
    data["tickets"][str(ticket_id)] = ticket
    data["next_id"] = ticket_id + 1
    _save(data)
    return ticket, True


def get_ticket(ticket_id: int) -> dict | None:
    return _load()["tickets"].get(str(ticket_id))


def set_unread(ticket_id: int, value: bool) -> None:
    data = _load()
    ticket = data["tickets"].get(str(ticket_id))
    if ticket:
        ticket["has_unread"] = value
        _save(data)


def add_message(
    ticket_id: int,
    from_type: str,
    text: str | None = None,
    media_type: str | None = None,
    from_chat_id: int | None = None,
    message_id: int | None = None,
) -> None:
    data = _load()
    ticket = data["tickets"].get(str(ticket_id))
    if not ticket:
        return
    entry = {"from": from_type, "timestamp": datetime.now().strftime("%d.%m %H:%M")}
    if text:
        entry["text"] = text[:300]
    if media_type:
        entry["media"] = media_type
    if from_chat_id and message_id:
        entry["from_chat_id"] = from_chat_id
        entry["message_id"] = message_id
    ticket["messages"].append(entry)
    _save(data)


def _format_msg_preview(message_data: dict, limit: int = 160) -> str:
    who = "👤 Пользователь" if message_data.get("from") == "user" else "👨‍💻 Админ"
    time = message_data.get("timestamp", "")
    content = message_data.get("text") or f"[{message_data.get('media', 'медиа')}]"
    content = escape(content)
    if len(content) > limit:
        content = content[: limit - 3] + "..."
    return f"<b>{who}</b> <i>{time}</i>\n{content}"


def format_history(ticket: dict, last_n: int = 20) -> str:
    messages = ticket["messages"][-last_n:]
    if not messages:
        return "<i>Сообщений пока нет</i>"
    lines = []
    for message_data in messages:
        lines.append(_format_msg_preview(message_data, limit=220))
    return "\n\n".join(lines)


def format_history_compact(ticket: dict, last_n: int = 8) -> str:
    messages = ticket["messages"][-last_n:]
    if not messages:
        return "<i>Сообщений пока нет</i>"
    return "\n\n".join(_format_msg_preview(message_data, limit=220) for message_data in messages)


async def _ticket_user_label(bot_obj, user_id: int) -> str:
    try:
        chat = await bot_obj.get_chat(user_id)
        return f"@{chat.username}" if chat.username else chat.full_name or str(user_id)
    except Exception:
        return str(user_id)


def ticket_panel_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✍️ Ответить", callback_data=f"adm_ticket_reply_{ticket_id}"),
                InlineKeyboardButton(text="📜 История", callback_data=f"adm_ticket_history_{ticket_id}"),
            ],
            [
                InlineKeyboardButton(text="📎 Медиа", callback_data=f"adm_ticket_media_{ticket_id}"),
                InlineKeyboardButton(text="↩️ К тикетам", callback_data="admin_tickets"),
            ],
        ]
    )


def _media_type(message: types.Message) -> str | None:
    if message.photo:
        return "фото"
    if message.video:
        return "видео"
    if message.document:
        return "документ"
    if message.voice:
        return "голосовое"
    if message.audio:
        return "аудио"
    if message.sticker:
        return "стикер"
    if message.video_note:
        return "видео-кружок"
    return None


async def _forward_to(message: types.Message, target_uid: int, label: str) -> None:
    media = _media_type(message)
    if message.text:
        await bot.send_message(target_uid, f"{label}\n{message.text}", parse_mode=ParseMode.HTML)
    elif media:
        await bot.send_message(target_uid, f"{label} [{media}]", parse_mode=ParseMode.HTML)
        await message.copy_to(target_uid)


async def open_support_flow(message_or_call, state: FSMContext, *, edit: bool = False) -> None:
    message = message_or_call.message if hasattr(message_or_call, "message") else message_or_call
    user = message_or_call.from_user if hasattr(message_or_call, "from_user") else message.from_user

    ticket, is_new = get_or_create_ticket(user.id)
    await state.set_state(TicketUser.chatting)
    await state.update_data(ticket_id=ticket["id"])

    if is_new:
        text = (
            "💬 <b>Поддержка открыта!</b>\n\n"
            "Напишите сюда сообщение — можно отправлять текст, фото, видео и файлы."
            f"{EXIT_HINT}"
        )
    else:
        history = format_history(ticket)
        text = (
            "💬 <b>Ваш чат с поддержкой</b>\n\n"
            f"{history}"
            f"{EXIT_HINT}"
        )

    if edit:
        await message.edit_text(text, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, parse_mode=ParseMode.HTML)

    if is_new and ADMIN_ID:
        try:
            nick = await _ticket_user_label(bot, user.id)
            await bot.send_message(
                ADMIN_ID,
                f"🎫 <b>Новый тикет #{ticket['id']}</b>\n"
                f"👤 {escape(nick)} (<code>{user.id}</code>)",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"💬 Открыть тикет #{ticket['id']}", callback_data=f"adm_ticket_{ticket['id']}")]
                    ]
                ),
            )
        except Exception:
            pass


@router.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    await open_support_flow(message, state)


@router.callback_query(F.data == "start_support")
async def cb_start_support(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await open_support_flow(call, state, edit=True)


@router.message(TicketUser.chatting)
async def user_ticket_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    if not ticket_id:
        await state.clear()
        return

    text = message.text or message.caption
    media = _media_type(message)
    add_message(
        ticket_id,
        "user",
        text=text,
        media_type=media,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )

    ticket = get_ticket(ticket_id)
    user = message.from_user
    nick = f"@{user.username}" if user.username else user.full_name or str(user.id)
    now = datetime.now().strftime("%d.%m %H:%M")
    label = f"📩 Тикет #{ticket_id} · {nick} · {now}"

    try:
        if get_admin_active_ticket() == ticket_id:
            if message.text:
                await bot.send_message(ADMIN_ID, f"{label}\n\n{message.text}", parse_mode=ParseMode.HTML)
            else:
                caption = f"{label}\n{message.caption or ''}".strip()
                await message.copy_to(ADMIN_ID, caption=caption)
        else:
            if not ticket.get("has_unread"):
                set_unread(ticket_id, True)
                await bot.send_message(
                    ADMIN_ID,
                    f"📩 <b>Тикет #{ticket_id} · {nick}</b>\nЕсть новые сообщения",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text=f"💬 Открыть тикет #{ticket_id}", callback_data=f"adm_ticket_{ticket_id}")]
                        ]
                    ),
                )
    except Exception as exc:
        await message.answer(f"❌ Ошибка отправки: {exc}")
        return

    await message.answer(f"✅ Отправлено{EXIT_HINT}", parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "admin_tickets")
async def cb_admin_tickets(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа", show_alert=True)

    await state.clear()
    set_admin_active_ticket(None)
    data = _load()
    tickets = sorted(data["tickets"].values(), key=lambda item: item["id"], reverse=True)

    buttons = []
    for ticket in tickets:
        nick = await _ticket_user_label(call.bot, ticket["user_id"])
        unread = " 🔴" if ticket.get("has_unread") else ""
        last = ticket["messages"][-1] if ticket.get("messages") else {}
        last_from = "👤" if last.get("from") == "user" else "👨‍💻" if last else "·"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"#{ticket['id']} {last_from} {nick} · {len(ticket['messages'])}{unread}",
                    callback_data=f"adm_ticket_{ticket['id']}",
                )
            ]
        )

    text = (
        f"🎫 <b>Тикеты ({len(tickets)})</b>\n\n"
        f"🔴 — есть непрочитанные\n"
        f"👤/👨‍💻 — кто написал последним"
    ) if tickets else "🎫 <b>Тикеты</b>\n\n<i>Пока нет тикетов.</i>"
    buttons.append([InlineKeyboardButton(text="↩️ Назад в меню", callback_data="back_to_admin")])
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data == "back_to_admin")
async def cb_back_to_admin(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа", show_alert=True)

    from handlers.admin import render_admin_menu

    await state.clear()
    set_admin_active_ticket(None)
    await call.answer()
    await render_admin_menu(call.message, call.from_user.id, edit=True)


@router.callback_query(F.data.regexp(r"^adm_ticket_\d+$"))
async def cb_adm_open_ticket(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа", show_alert=True)

    ticket_id = int(call.data.split("_")[2])
    ticket = get_ticket(ticket_id)
    if not ticket:
        return await call.answer("Тикет не найден", show_alert=True)

    set_unread(ticket_id, False)
    set_admin_active_ticket(None)
    await state.clear()
    user_id = int(ticket["user_id"])
    nick = await _ticket_user_label(call.bot, user_id)
    last_msg = ticket["messages"][-1] if ticket.get("messages") else None
    last_text = _format_msg_preview(last_msg, limit=180) if last_msg else "<i>Сообщений пока нет</i>"
    text = (
        f"🎫 <b>Тикет #{ticket['id']}</b>\n"
        f"👤 {escape(nick)} · <code>{user_id}</code>\n"
        f"📅 Создан: <b>{ticket['created_at']}</b>\n"
        f"📨 Сообщений: <b>{len(ticket.get('messages', []))}</b>\n"
        f"📌 Статус: {'🔴 Есть новые' if ticket.get('has_unread') else '✅ Прочитано'}\n\n"
        f"<b>Последнее сообщение:</b>\n{last_text}"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=ticket_panel_kb(ticket_id))
    await call.answer()


@router.callback_query(F.data.startswith("adm_ticket_history_"))
async def cb_adm_ticket_history(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа", show_alert=True)

    ticket_id = int(call.data.split("_")[3])
    ticket = get_ticket(ticket_id)
    if not ticket:
        return await call.answer("Тикет не найден", show_alert=True)

    history = format_history_compact(ticket, last_n=8)
    await call.message.edit_text(
        f"📜 <b>История тикета #{ticket_id}</b>\n\n{history}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="↩️ К тикету", callback_data=f"adm_ticket_{ticket_id}")],
                [InlineKeyboardButton(text="🏠 К списку", callback_data="admin_tickets")],
            ]
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_ticket_media_"))
async def cb_adm_ticket_media(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа", show_alert=True)

    ticket_id = int(call.data.split("_")[3])
    ticket = get_ticket(ticket_id)
    if not ticket:
        return await call.answer("Тикет не найден", show_alert=True)

    media_messages = [
        message_data
        for message_data in ticket["messages"]
        if message_data.get("from") == "user"
        and message_data.get("media")
        and message_data.get("from_chat_id")
        and message_data.get("message_id")
    ][-10:]
    if media_messages:
        for message_data in media_messages:
            try:
                await bot.copy_message(
                    chat_id=ADMIN_ID,
                    from_chat_id=message_data["from_chat_id"],
                    message_id=message_data["message_id"],
                )
            except Exception:
                pass
        await call.answer(f"Отправлено медиа: {len(media_messages)}")
    else:
        await call.answer("В тикете нет медиа", show_alert=True)


@router.callback_query(F.data.startswith("adm_ticket_reply_"))
async def cb_adm_ticket_reply(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа", show_alert=True)

    ticket_id = int(call.data.split("_")[3])
    ticket = get_ticket(ticket_id)
    if not ticket:
        return await call.answer("Тикет не найден", show_alert=True)

    nick = await _ticket_user_label(call.bot, ticket["user_id"])
    set_admin_active_ticket(ticket_id)
    await state.set_state(TicketAdmin.chatting)
    await state.update_data(ticket_id=ticket_id, ticket_user_id=ticket["user_id"], ticket_nick=nick)
    await call.message.edit_text(
        f"✍️ <b>Ответ в тикет #{ticket_id}</b>\n\n"
        f"Получатель: {escape(nick)} · <code>{ticket['user_id']}</code>\n\n"
        f"Отправьте текст, фото, видео или файл.\n"
        f"{EXIT_HINT}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm_ticket_{ticket_id}")]
            ]
        ),
    )
    await call.answer()


@router.message(TicketAdmin.chatting)
async def admin_ticket_message(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    target_uid = data.get("ticket_user_id")
    nick = data.get("ticket_nick", "пользователь")

    if not ticket_id or not target_uid:
        await state.clear()
        return

    text = message.text or message.caption
    media = _media_type(message)
    add_message(ticket_id, "admin", text=text, media_type=media)

    try:
        await _forward_to(message, target_uid, "💬 <b>Ответ администратора:</b>")
        await message.answer(f"✅ Доставлено → {nick}{EXIT_HINT}", parse_mode=ParseMode.HTML)
    except Exception as exc:
        await message.answer(f"❌ Не удалось доставить: {exc}")
