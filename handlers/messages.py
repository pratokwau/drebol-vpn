from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID, load_config, save_config
from database import add_support_message, get_support_messages
from keyboards import back_admin, support_keyboard
from states import (
    AWAITING_CHANNEL, AWAITING_BROADCAST,
    AWAITING_SUPPORT_MSG, AWAITING_ADMIN_REPLY,
)
from handlers.broadcast import do_broadcast


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user = update.effective_user
    text = update.message.text.strip()
    is_admin = user.id == ADMIN_ID

    # ── Юзер пишет в поддержку ───────────────────────────────────────────────
    if state == AWAITING_SUPPORT_MSG and not is_admin:
        await add_support_message(user.id, text, from_admin=False)
        _, total_pages = await get_support_messages(user.id)
        await update.message.reply_text(
            "✅ Сообщение отправлено в поддержку! Мы ответим как можно скорее.",
            reply_markup=support_keyboard(total_pages, total_pages),
        )
        # Уведомляем админа
        uname = f"@{user.username}" if user.username else f"id{user.id}"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 Новое обращение от {user.first_name} ({uname}):\n\n{text}",
        )
        return

    # ── Админ устанавливает канал ─────────────────────────────────────────────
    if state == AWAITING_CHANNEL and is_admin:
        if not text.startswith("http"):
            await update.message.reply_text(
                "❌ Некорректная ссылка. Должна начинаться с <code>https://t.me/</code>",
                parse_mode="HTML",
                reply_markup=back_admin(),
            )
            return
        cfg = load_config()
        cfg["channel_url"] = text
        save_config(cfg)
        context.user_data.pop("state", None)
        await update.message.reply_text(
            f"✅ Канал сохранён: <code>{text}</code>",
            parse_mode="HTML",
            reply_markup=back_admin(),
        )
        return

    # ── Админ пишет рассылку ──────────────────────────────────────────────────
    if state == AWAITING_BROADCAST and is_admin:
        context.user_data.pop("state", None)
        from database import get_all_user_ids
        user_ids = await get_all_user_ids()
        msg = await update.message.reply_text(f"⏳ Отправляю рассылку {len(user_ids)} пользователям...")
        ok, fail = await do_broadcast(context.bot, text)
        await msg.edit_text(
            f"✅ Рассылка завершена.\n\n👥 В базе: {len(user_ids)}\n📨 Доставлено: {ok}\n❌ Ошибок: {fail}",
            reply_markup=back_admin(),
        )
        return

    # ── Админ отвечает на тикет ───────────────────────────────────────────────
    if state == AWAITING_ADMIN_REPLY and is_admin:
        reply_to = context.user_data.pop("reply_to", None)
        context.user_data.pop("state", None)
        if not reply_to:
            await update.message.reply_text("❌ Ошибка: пользователь не найден.", reply_markup=back_admin())
            return
        await add_support_message(reply_to, text, from_admin=True)
        try:
            await context.bot.send_message(
                chat_id=reply_to,
                text=f"🛡 <b>Ответ поддержки:</b>\n\n{text}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await update.message.reply_text(
            "✅ Ответ отправлен пользователю.",
            reply_markup=back_admin(),
        )
        return
