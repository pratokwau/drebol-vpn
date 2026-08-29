from telegram import Bot
from telegram.ext import ContextTypes
from database import get_all_user_ids
from keyboards import cancel_admin
from states import AWAITING_BROADCAST


async def handle_broadcast_start(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_BROADCAST
    await query.edit_message_text(
        "📣 <b>Рассылка</b>\n\nНапишите текст сообщения для рассылки всем пользователям.\n\n"
        "Поддерживается HTML-разметка: <code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def do_broadcast(bot: Bot, text: str) -> tuple[int, int]:
    user_ids = await get_all_user_ids()
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1
    return ok, fail
