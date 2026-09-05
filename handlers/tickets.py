from datetime import datetime
from telegram.ext import ContextTypes
from database import (
    get_ticket_users, get_support_messages, get_user_info, add_support_message,
    mark_ticket_read, get_unread_tickets_count, count_support_files, get_support_files,
)
from keyboards import ticket_list_keyboard, ticket_view_keyboard, cancel_admin
from states import AWAITING_ADMIN_REPLY


def _fmt_time(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return raw


async def handle_ticket_list(query, page: int = 1):
    rows, total_pages = await get_ticket_users(page)
    unread_total = await get_unread_tickets_count()
    title = "🎫 <b>Тикеты</b>"
    if not rows:
        await query.edit_message_text(
            f"{title}\n\nОбращений пока нет.",
            parse_mode="HTML",
            reply_markup=ticket_list_keyboard([], 1, 1),
        )
        return
    header = (
        f"{title} — стр. {page}/{total_pages}\n"
        f"🔴 Непрочитанных: <b>{unread_total}</b>\n\n"
        "🔴 — новые сообщения · ✅ — вы ответили последним\n"
        "Выберите диалог:"
    )
    await query.edit_message_text(
        header,
        parse_mode="HTML",
        reply_markup=ticket_list_keyboard(rows, page, total_pages),
    )


async def handle_ticket_view(query, user_id: int, page: int = 1):
    await mark_ticket_read(user_id)

    user_info = await get_user_info(user_id)
    first_name = user_info[1] if user_info else str(user_id)
    username = f" (@{user_info[2]})" if user_info and user_info[2] else ""

    msgs, total_pages = await get_support_messages(user_id, page)
    has_files = (await count_support_files(user_id)) > 0
    lines = [
        f"👤 <b>{first_name}</b>{username}\n"
        f"🆔 <code>{user_id}</code> · стр. {page}/{total_pages}\n"
    ]
    for row in msgs:
        text, from_admin, created_at = row[0], row[1], row[2]
        file_id = row[3] if len(row) > 3 else None
        file_type = row[4] if len(row) > 4 else None
        who = "🛡 <b>Поддержка</b>" if from_admin else "👤 <b>Юзер</b>"
        file_mark = ""
        if file_id:
            file_mark = " 🖼" if file_type == "photo" else " 📎"
        lines.append(f"{who} · 🕐 {_fmt_time(created_at)}{file_mark}\n{text}")

    await query.edit_message_text(
        "\n\n".join(lines),
        parse_mode="HTML",
        reply_markup=ticket_view_keyboard(user_id, page, total_pages, has_files),
    )


async def handle_ticket_reply_start(query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_ADMIN_REPLY
    context.user_data["reply_to"] = user_id
    user_info = await get_user_info(user_id)
    name = user_info[1] if user_info else str(user_id)
    await query.edit_message_text(
        f"✏️ <b>Ответ пользователю {name}</b>\n\nНапишите ответ или отправьте файл/фото:",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def handle_ticket_files(query, user_id: int):
    files = await get_support_files(user_id)
    if not files:
        await query.answer("Файлов нет.", show_alert=True)
        return
    user_info = await get_user_info(user_id)
    first_name = user_info[1] if user_info else str(user_id)
    await query.answer(f"Отправляю {len(files)} файл(ов)...")
    for file_id, file_type, from_admin, created_at in files:
        who = "🛡 Поддержка" if from_admin else f"👤 {first_name}"
        caption = f"{who} · {_fmt_time(created_at)}"
        try:
            if file_type == "photo":
                await query.message.reply_photo(file_id, caption=caption)
            else:
                await query.message.reply_document(file_id, caption=caption)
        except Exception:
            pass
