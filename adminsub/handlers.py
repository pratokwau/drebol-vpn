from telegram.ext import ContextTypes
from keyboards import admin_subs_keyboard, cancel_admin
from states import AWAITING_SUB_EXPIRE


async def handle_admin_subs_menu(query):
    await query.edit_message_text(
        "📋 <b>Админские подписки</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_subs_keyboard(),
    )


async def handle_create_sub_start(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_SUB_EXPIRE
    context.user_data["new_sub"] = {}
    await query.edit_message_text(
        "➕ <b>Создание подписки</b>\n\n"
        "<b>Шаг 1/4</b> — Дата окончания\n\n"
        "Введи дату в формате <code>дд.мм.гггг</code>\n"
        "Например: <code>31.12.2025</code>",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )
