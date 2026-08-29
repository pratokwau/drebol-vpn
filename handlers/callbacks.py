from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID, load_config, save_config
from states import AWAITING_SUPPORT_MSG
from subscription import is_subscribed, subscribe_keyboard
from keyboards import main_keyboard
from handlers.user import handle_buy, handle_about, handle_back_start, handle_my_sub, handle_news, handle_how_to
from handlers.admin import handle_admin_panel, handle_set_channel, handle_git_update
from handlers.support import open_support
from handlers.broadcast import handle_broadcast_start
from handlers.tickets import handle_ticket_list, handle_ticket_view, handle_ticket_reply_start


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    adm = _is_admin(update)

    # Ничего не делать (кнопка-счётчик страниц)
    if data == "noop":
        return

    # ── Проверка подписки после нажатия "Я подписался" ───────────────────────
    if data == "check_sub":
        user = update.effective_user
        if not await is_subscribed(context.bot, user.id):
            await query.answer("❌ Вы всё ещё не подписаны на канал.", show_alert=True)
            return
        is_admin = adm
        await query.edit_message_text(
            f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
            "🔒 Быстрый и безопасный VPN\n"
            "⚡️ Стабильное подключение\n"
            "🌍 Доступ к популярным сервисам\n\n"
            "Выберите нужный раздел ниже 👇",
            parse_mode="HTML",
            reply_markup=main_keyboard(is_admin),
        )
        return

    # ── Пользовательские ─────────────────────────────────────────────────────
    if data == "back_start":
        context.user_data.pop("state", None)
        await handle_back_start(query, update.effective_user)

    elif data == "my_sub":
        await handle_my_sub(query)

    elif data == "news":
        await handle_news(query)

    elif data == "news_no_channel":
        await query.answer("Канал пока не настроен.", show_alert=True)

    elif data == "how_to":
        await handle_how_to(query)

    elif data == "buy":
        await handle_buy(query)

    elif data == "about":
        await handle_about(query)

    elif data.startswith("support_page:"):
        page = int(data.split(":")[1])
        context.user_data["state"] = AWAITING_SUPPORT_MSG
        await open_support(query, update.effective_user.id, page)

    # ── Админские ────────────────────────────────────────────────────────────
    elif data == "admin_panel":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        context.user_data.pop("state", None)
        await handle_admin_panel(query)

    elif data == "toggle_force_sub":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        cfg = load_config()
        cfg["force_subscribe"] = not cfg.get("force_subscribe", False)
        save_config(cfg)
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

    elif data == "broadcast":
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await handle_broadcast_start(query, context)

    elif data.startswith("ticket_list:"):
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        page = int(data.split(":")[1])
        await handle_ticket_list(query, page)

    elif data.startswith("ticket_view:"):
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        _, user_id, page = data.split(":")
        await handle_ticket_view(query, int(user_id), int(page))

    elif data.startswith("ticket_reply:"):
        if not adm:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        user_id = int(data.split(":")[1])
        await handle_ticket_reply_start(query, user_id, context)
