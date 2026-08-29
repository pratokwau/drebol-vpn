from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID, load_config, save_config
from states import AWAITING_SUPPORT_MSG
from subscription import is_subscribed, subscribe_keyboard
from keyboards import main_keyboard
from handlers.user import handle_buy, handle_about, handle_back_start, handle_my_sub, handle_news, handle_how_to
from handlers.admin import handle_admin_panel, handle_set_channel, handle_git_update, handle_set_privacy_url, handle_set_terms_url
from handlers.support import open_support
from handlers.broadcast import handle_broadcast_start
from handlers.tickets import handle_ticket_list, handle_ticket_view, handle_ticket_reply_start
from handlers.xui_settings import (
    handle_xui_settings, handle_set_xui_url, handle_set_xui_token,
    handle_set_xui_sub_port, handle_set_xui_sub_path,
    handle_test_xui,
)
from adminsub.handlers import (
    handle_admin_subs_menu, handle_presets_menu,
    handle_preset_expire, handle_preset_ip, handle_preset_hwid, handle_preset_traffic,
    handle_create_sub, handle_sub_view, handle_sub_delete,
    handle_inbounds_menu, handle_toggle_inbound,
    handle_auto_update_settings, handle_toggle_auto_update,
    handle_set_auto_update_days, handle_run_sync_now,
)


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    adm = _is_admin(update)

    if data == "noop":
        return

    # Проверка подписки для не-админов
    if data != "check_sub" and not adm:
        if not await is_subscribed(context.bot, update.effective_user.id):
            await query.edit_message_text(
                f"👋 Привет, {update.effective_user.first_name}!\n\n"
                "Добро пожаловать в <b>Drebol VPN</b>.\n\n"
                "🔒 Чтобы пользоваться ботом, необходимо подписаться на наш канал.\n\n"
                "После подписки нажми кнопку <b>✅ Я подписался</b>.",
                parse_mode="HTML",
                reply_markup=subscribe_keyboard(),
            )
            return

    if data == "check_sub":
        user = update.effective_user
        if not await is_subscribed(context.bot, user.id):
            await query.edit_message_text(
                f"👋 Привет, {user.first_name}!\n\n"
                "Добро пожаловать в <b>Drebol VPN</b>.\n\n"
                "❌ Вы не подписаны на канал.\n\n"
                "Подпишитесь и снова нажмите <b>✅ Я подписался</b>.",
                parse_mode="HTML",
                reply_markup=subscribe_keyboard(),
            )
            return
        from adminsub.storage import get_sub_by_tg_id
        has_sub = bool(await get_sub_by_tg_id(user.id))
        await query.edit_message_text(
            f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
            "🔒 Быстрый и безопасный VPN\n"
            "⚡️ Стабильное подключение\n"
            "🌍 Доступ к популярным сервисам\n\n"
            "Выберите нужный раздел ниже 👇",
            parse_mode="HTML",
            reply_markup=main_keyboard(adm, has_sub),
        )
        return

    # ── Юзер ─────────────────────────────────────────────────────────────────
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

    # ── Только админ ─────────────────────────────────────────────────────────
    elif not adm:
        await query.edit_message_text("⛔ Нет доступа.")

    elif data == "admin_panel":
        context.user_data.pop("state", None)
        await handle_admin_panel(query)
    elif data == "toggle_force_sub":
        cfg = load_config()
        cfg["force_subscribe"] = not cfg.get("force_subscribe", False)
        save_config(cfg)
        await handle_admin_panel(query)
    elif data == "set_channel":
        await handle_set_channel(query, context)
    elif data == "set_privacy_url":
        await handle_set_privacy_url(query, context)
    elif data == "set_terms_url":
        await handle_set_terms_url(query, context)
    elif data == "git_update":
        await handle_git_update(query)
    elif data == "broadcast":
        await handle_broadcast_start(query, context)

    # Тикеты
    elif data.startswith("ticket_list:"):
        await handle_ticket_list(query, int(data.split(":")[1]))
    elif data.startswith("ticket_view:"):
        _, uid, page = data.split(":")
        await handle_ticket_view(query, int(uid), int(page))
    elif data.startswith("ticket_reply:"):
        await handle_ticket_reply_start(query, int(data.split(":")[1]), context)

    # 3x-UI
    elif data == "xui_settings":
        await handle_xui_settings(query)
    elif data == "set_xui_url":
        await handle_set_xui_url(query, context)
    elif data == "set_xui_token":
        await handle_set_xui_token(query, context)
    elif data == "set_xui_sub_port":
        await handle_set_xui_sub_port(query, context)
    elif data == "set_xui_sub_path":
        await handle_set_xui_sub_path(query, context)
    elif data == "test_xui":
        await handle_test_xui(query)

    # Админские подписки
    elif data == "admin_subs":
        await handle_admin_subs_menu(query)
    elif data.startswith("subs_page:"):
        await handle_admin_subs_menu(query, int(data.split(":")[1]))
    elif data == "create_sub":
        await handle_create_sub(query, context)
    elif data == "sub_presets":
        await handle_presets_menu(query)
    elif data == "preset_expire":
        await handle_preset_expire(query, context)
    elif data == "preset_ip":
        await handle_preset_ip(query, context)
    elif data == "preset_hwid":
        await handle_preset_hwid(query, context)
    elif data == "preset_traffic":
        await handle_preset_traffic(query, context)
    elif data.startswith("sub_view:"):
        await handle_sub_view(query, int(data.split(":")[1]))
    elif data.startswith("sub_delete:"):
        await handle_sub_delete(query, int(data.split(":")[1]))
    elif data == "inbounds_menu":
        await handle_inbounds_menu(query)
    elif data.startswith("toggle_inbound:"):
        await handle_toggle_inbound(query, int(data.split(":")[1]))
    elif data == "auto_update_settings":
        await handle_auto_update_settings(query)
    elif data == "toggle_auto_update":
        await handle_toggle_auto_update(query)
    elif data == "set_auto_update_days":
        await handle_set_auto_update_days(query, context)
    elif data == "run_sync_now":
        await handle_run_sync_now(query)
