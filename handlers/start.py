from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID
from database import upsert_user
from keyboards import main_keyboard
from subscription import is_subscribed, subscribe_keyboard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    user = update.effective_user
    await upsert_user(user.id, user.first_name, user.username)

    if not await is_subscribed(context.bot, user.id):
        await update.message.reply_text(
            "🔒 Для использования бота необходимо подписаться на наш канал.",
            reply_markup=subscribe_keyboard(),
        )
        return

    is_admin = user.id == ADMIN_ID
    await update.message.reply_text(
        f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
        "🔒 Быстрый и безопасный VPN\n"
        "⚡️ Стабильное подключение\n"
        "🌍 Доступ к популярным сервисам\n\n"
        "Выберите нужный раздел ниже 👇",
        parse_mode="HTML",
        reply_markup=main_keyboard(is_admin),
    )
