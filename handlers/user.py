from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID
from keyboards import main_keyboard, back_main


async def handle_buy(query):
    await query.edit_message_text(
        "🛒 <b>Покупка VPN</b>\n\nРаздел в разработке.",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def handle_about(query):
    await query.edit_message_text(
        "ℹ️ <b>О сервисе</b>\n\nDrebol VPN — быстрый и надёжный VPN-сервис.",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def handle_back_start(query, user):
    is_admin = user.id == ADMIN_ID
    await query.edit_message_text(
        f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
        "🔒 Быстрый и безопасный VPN\n"
        "⚡️ Стабильное подключение\n"
        "🌍 Доступ к популярным сервисам\n\n"
        "Выберите нужный раздел ниже 👇",
        parse_mode="HTML",
        reply_markup=main_keyboard(is_admin),
    )
