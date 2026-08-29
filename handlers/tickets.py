from datetime import datetime
from telegram.ext import ContextTypes
from database import get_ticket_users, get_support_messages, get_user_info, add_support_message
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
    if not rows:
        await query.edit_message_text(
            "🎫 <b>Тикеты</b>\n\nОбращений пока нет.",
            parse_mode="HTML",
            reply_markup=ticket_list_keyboard([], 1, 1),
        )
        return
    await query.edit_message_text(
        f"🎫 <b>Тикеты</b> — стр. {page}/{total_pages}\n\nВыберите пользователя:",
        parse_mode="HTML",
        reply_markup=ticket_list_keyboard(rows, page, total_pages),
    )


async def handle_ticket_view(query, user_id: int, page: int = 1):
    user_info = await get_user_info(user_id)
    first_name = user_info[1] if user_info else str(user_id)
    username = f" (@{user_info[2]})" if user_info and user_info[2] else ""

    msgs, total_pages = await get_support_messages(user_id, page)
    lines = [f"👤 <b>{first_name}{username}</b> — стр. {page}/{total_pages}\n"]
    for text, from_admin, created_at in msgs:
        who = "🛡 <b>Поддержка</b>" if from_admin else "👤 <b>Юзер</b>"
        lines.append(f"{who}: {text}\n🕐 {_fmt_time(created_at)}")

    await query.edit_message_text(
        "\n\n".join(lines),
        parse_mode="HTML",
        reply_markup=ticket_view_keyboard(user_id, page, total_pages),
    )


async def handle_ticket_reply_start(query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_ADMIN_REPLY
    context.user_data["reply_to"] = user_id
    user_info = await get_user_info(user_id)
    name = user_info[1] if user_info else str(user_id)
    await query.edit_message_text(
        f"✏️ <b>Ответ пользователю {name}</b>\n\nНапишите ответ:",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )
