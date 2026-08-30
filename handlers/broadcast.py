from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_users_by_segment
from keyboards import cancel_admin
from states import AWAITING_BROADCAST


SEGMENTS = {
    "all": "🌍 Все пользователи",
    "active": "🟢 Активные подписки",
    "expired": "🔴 Истёкшие подписки",
    "trial": "🆓 Только триал",
    "paying": "⭐️ Платящие",
    "no_sub": "🚫 Без подписки",
    "pending_pay": "⏳ Ожидают оплаты",
}


async def handle_broadcast_start(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    kb = [[InlineKeyboardButton(label, callback_data=f"bcast_seg:{key}")]
          for key, label in SEGMENTS.items()]
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text(
        "📣 <b>Рассылка</b>\n\nВыберите, кому отправить сообщение:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_broadcast_segment(query, context: ContextTypes.DEFAULT_TYPE, segment: str):
    if segment not in SEGMENTS:
        segment = "all"
    context.user_data["state"] = AWAITING_BROADCAST
    context.user_data["bcast_segment"] = segment
    count = len(await get_users_by_segment(segment))
    await query.edit_message_text(
        f"📣 <b>Рассылка · {SEGMENTS[segment]}</b>\n\n"
        f"👥 Получателей: <b>{count}</b>\n\n"
        "Напишите текст сообщения.\n"
        "Поддерживается HTML: <code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def do_broadcast(bot: Bot, text: str, segment: str = "all") -> tuple[int, int]:
    user_ids = await get_users_by_segment(segment)
    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1
    return ok, fail
