from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID
from handlers.user import handle_buy, handle_about, handle_back_start
from handlers.admin import handle_admin_panel, handle_set_channel, handle_git_update


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    adm = _is_admin(update)

    # --- Пользовательские ---
    if data == "back_start":
        context.user_data.pop("state", None)
        await handle_back_start(query, update.effective_user)

    elif data == "buy":
        await handle_buy(query)

    elif data == "about":
        await handle_about(query)

    # --- Админские ---
    elif data == "admin_panel":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await handle_admin_panel(query)

    elif data == "set_channel":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await handle_set_channel(query, context)

    elif data == "git_update":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await handle_git_update(query)
