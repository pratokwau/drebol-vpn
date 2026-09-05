from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID, load_config, save_config
from states import AWAITING_SUPPORT_MSG
from subscription import is_subscribed, subscribe_keyboard
from keyboards import main_keyboard
from handlers.user import (
    handle_buy, handle_about, handle_back_start, handle_my_sub, handle_my_paid_sub,
    handle_news, handle_how_to, handle_renew_sub, handle_i_paid, handle_referral,
    handle_copy_sub, handle_enter_promo, handle_remove_promo,
    handle_rate_service, handle_rate, handle_rate_skip,
    handle_qr_code, handle_reissue_key,
)
from handlers.admin import (
    handle_admin_panel, handle_set_channel, handle_git_update,
    handle_set_privacy_url, handle_set_terms_url, handle_documents_menu,
    handle_channel_menu, handle_dashboard, handle_healthcheck,
    handle_find_user, handle_user_profile, handle_ban_user, handle_unban_user,
    handle_log_channel_settings, handle_set_log_channel, handle_clear_log_channel,
    handle_winback_settings, handle_toggle_winback, handle_set_winback_days, handle_set_winback_percent,
    handle_reviews_menu, handle_review_view, handle_set_review_days,
    handle_user_history, handle_dm_user, handle_payment_stats,
)
from handlers.support import open_support
from handlers.broadcast import handle_broadcast_start, handle_broadcast_segment
from handlers.tickets import (
    handle_ticket_list, handle_ticket_view, handle_ticket_reply_start,
)
from handlers.xui_settings import (
    handle_xui_settings, handle_set_xui_url, handle_set_xui_token,
    handle_set_xui_sub_port, handle_set_xui_sub_path,
    handle_test_xui,
)
from adminsub.handlers import (
    handle_admin_subs_menu, handle_presets_menu,
    handle_preset_expire, handle_preset_ip, handle_preset_hwid, handle_preset_traffic,
    handle_create_sub, handle_sub_view, handle_sub_delete, handle_sub_toggle,
    handle_inbounds_menu, handle_toggle_inbound,
    handle_auto_update_settings, handle_toggle_auto_update,
    handle_set_auto_update_days, handle_run_sync_now,
    handle_sub_settings, handle_sub_edit_expire, handle_sub_edit_ip,
    handle_sub_edit_hwid, handle_sub_edit_traffic,
)
from paidsub.handlers import (
    handle_paid_subs_menu, handle_paid_presets_menu,
    handle_paid_preset_ip, handle_paid_preset_hwid, handle_paid_preset_traffic,
    handle_paid_preset_trial, handle_paid_preset_pay_period, handle_paid_preset_renew,
    handle_paid_preset_price, handle_paid_preset_pay_url,
    handle_paid_create_sub, handle_paid_sub_view, handle_paid_sub_delete, handle_paid_sub_toggle,
    handle_paid_inbounds_menu, handle_paid_toggle_inbound,
    handle_paid_inbounds_expire_menu, handle_paid_toggle_inbound_expire,
    handle_approve, handle_reject, handle_request_sub,
    handle_paid_sub_freeze, handle_paid_sub_extend, handle_paid_sub_reduce,
    handle_paid_bulk_menu, handle_paid_bulk_extend, handle_paid_bulk_reduce,
    handle_paid_sub_settings, handle_paid_sub_edit_expire,
    handle_paid_sub_edit_ip, handle_paid_sub_edit_hwid, handle_paid_sub_edit_traffic,
    handle_paid_sub_edit_trial, handle_paid_sub_edit_pay_period,
    handle_paid_sub_edit_renew_time, handle_paid_sub_edit_price, handle_paid_sub_edit_pay_url,
    handle_confirm_payment, handle_reject_payment,
    handle_paid_history, handle_paid_history_view, handle_mute_user, handle_unmute_user, handle_muted_list,
    handle_paid_requests,
    handle_paid_auto_update_settings, handle_paid_toggle_auto_update,
    handle_paid_set_auto_update_days, handle_paid_run_sync_now,
    handle_referral_settings, handle_set_referral_bonus,
    handle_promos_menu, handle_promo_view, handle_promo_create,
    handle_promo_toggle, handle_promo_delete,
    handle_toggle_auto_trial,
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

    # Проверка бана
    if not adm and data != "check_sub":
        from database import is_banned
        if await is_banned(update.effective_user.id):
            await query.edit_message_text("🚫 Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

    # Проверка подписки для не-админов
    if data != "check_sub" and not adm:
        if not await is_subscribed(context.bot, update.effective_user.id):
            user = update.effective_user
            await query.edit_message_text(
                f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
                "🔒 Быстрый и безопасный VPN\n"
                "⚡️ Стабильное подключение\n"
                "🌍 Доступ к популярным сервисам\n\n"
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
                f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
                "🔒 Быстрый и безопасный VPN\n"
                "⚡️ Стабильное подключение\n"
                "🌍 Доступ к популярным сервисам\n\n"
                "❌ Вы не подписаны на канал.\n\n"
                "Подпишитесь и снова нажмите <b>✅ Я подписался</b>.",
                parse_mode="HTML",
                reply_markup=subscribe_keyboard(),
            )
            return
        from adminsub.storage import get_sub_by_tg_id
        from paidsub.storage import get_paid_sub_status
        has_sub = bool(await get_sub_by_tg_id(user.id))
        paid_status = await get_paid_sub_status(user.id)
        await query.edit_message_text(
            f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
            "🔒 Быстрый и безопасный VPN\n"
            "⚡️ Стабильное подключение\n"
            "🌍 Доступ к популярным сервисам\n\n"
            "Выберите нужный раздел ниже 👇",
            parse_mode="HTML",
            reply_markup=main_keyboard(adm, has_sub, paid_status),
        )
        return

    # ── Юзер ─────────────────────────────────────────────────────────────────
    if data == "back_start":
        context.user_data.pop("state", None)
        await handle_back_start(query, update.effective_user)
    elif data == "my_paid_sub":
        from paidsub.storage import get_paid_sub_by_tg_id
        if await get_paid_sub_by_tg_id(update.effective_user.id):
            await handle_my_paid_sub(query)
        else:
            await handle_request_sub(query, context)
    elif data == "renew_sub":
        await handle_renew_sub(query)
    elif data == "enter_promo":
        await handle_enter_promo(query, context)
    elif data == "remove_promo":
        await handle_remove_promo(query, context)
    elif data == "i_paid":
        await handle_i_paid(query, context)
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
    elif data == "referral":
        await handle_referral(query, context)
    elif data == "copy_sub":
        await handle_copy_sub(query, context)
    elif data == "rate_service":
        await handle_rate_service(query, context)
    elif data.startswith("rate:"):
        await handle_rate(query, context, int(data.split(":")[1]))
    elif data == "rate_skip":
        await handle_rate_skip(query, context)
    elif data == "qr_code":
        await handle_qr_code(query, context)
    elif data == "reissue_key":
        await handle_reissue_key(query, context)
    elif data == "support_open":
        context.user_data["state"] = AWAITING_SUPPORT_MSG
        await open_support(query, update.effective_user.id)
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
    elif data == "channel_menu":
        await handle_channel_menu(query)
    elif data == "toggle_force_sub":
        cfg = load_config()
        cfg["force_subscribe"] = not cfg.get("force_subscribe", False)
        save_config(cfg)
        await handle_channel_menu(query)
    elif data == "set_channel":
        await handle_set_channel(query, context)
    elif data == "documents_menu":
        await handle_documents_menu(query)
    elif data == "set_privacy_url":
        await handle_set_privacy_url(query, context)
    elif data == "set_terms_url":
        await handle_set_terms_url(query, context)
    elif data == "git_update":
        await handle_git_update(query)
    elif data == "dashboard":
        await handle_dashboard(query)
    elif data == "healthcheck":
        await handle_healthcheck(query)
    elif data == "find_user":
        await handle_find_user(query, context)
    elif data.startswith("user_profile:"):
        await handle_user_profile(query, int(data.split(":")[1]))
    elif data.startswith("ban_user:"):
        await handle_ban_user(query, int(data.split(":")[1]))
    elif data.startswith("unban_user:"):
        await handle_unban_user(query, int(data.split(":")[1]))
    elif data.startswith("user_history:"):
        parts = data.split(":")
        await handle_user_history(query, int(parts[1]), int(parts[2]))
    elif data.startswith("dm_user:"):
        await handle_dm_user(query, int(data.split(":")[1]), context)
    elif data.startswith("payment_stats:"):
        await handle_payment_stats(query, int(data.split(":")[1]))
    elif data == "log_channel_settings":
        await handle_log_channel_settings(query)
    elif data == "set_log_channel":
        await handle_set_log_channel(query, context)
    elif data == "clear_log_channel":
        await handle_clear_log_channel(query)
    elif data == "winback_settings":
        await handle_winback_settings(query)
    elif data == "toggle_winback":
        await handle_toggle_winback(query)
    elif data == "set_winback_days":
        await handle_set_winback_days(query, context)
    elif data == "set_winback_percent":
        await handle_set_winback_percent(query, context)
    elif data == "reviews_menu":
        await handle_reviews_menu(query)
    elif data.startswith("reviews_page:"):
        await handle_reviews_menu(query, int(data.split(":")[1]))
    elif data.startswith("review_view:"):
        await handle_review_view(query, int(data.split(":")[1]))
    elif data == "set_review_days":
        await handle_set_review_days(query, context)
    elif data == "toggle_auto_trial":
        await handle_toggle_auto_trial(query)
    elif data == "broadcast":
        await handle_broadcast_start(query, context)
    elif data.startswith("bcast_seg:"):
        await handle_broadcast_segment(query, context, data.split(":")[1])

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
    elif data.startswith("sub_toggle:"):
        await handle_sub_toggle(query, int(data.split(":")[1]), context)
    elif data.startswith("sub_delete:"):
        await handle_sub_delete(query, int(data.split(":")[1]), context)
    elif data.startswith("sub_settings:"):
        await handle_sub_settings(query, int(data.split(":")[1]))
    elif data.startswith("sub_edit_expire:"):
        await handle_sub_edit_expire(query, int(data.split(":")[1]), context)
    elif data.startswith("sub_edit_ip:"):
        await handle_sub_edit_ip(query, int(data.split(":")[1]), context)
    elif data.startswith("sub_edit_hwid:"):
        await handle_sub_edit_hwid(query, int(data.split(":")[1]), context)
    elif data.startswith("sub_edit_traffic:"):
        await handle_sub_edit_traffic(query, int(data.split(":")[1]), context)
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

    # Платные подписки
    elif data == "paid_subs":
        await handle_paid_subs_menu(query)
    elif data.startswith("paid_subs_page:"):
        await handle_paid_subs_menu(query, int(data.split(":")[1]))
    elif data == "paid_create_sub":
        await handle_paid_create_sub(query, context)
    elif data == "paid_sub_presets":
        await handle_paid_presets_menu(query)
    elif data == "paid_preset_trial":
        await handle_paid_preset_trial(query, context)
    elif data == "paid_preset_pay_period":
        await handle_paid_preset_pay_period(query, context)
    elif data == "paid_preset_renew":
        await handle_paid_preset_renew(query, context)
    elif data == "paid_preset_price":
        await handle_paid_preset_price(query, context)
    elif data == "paid_preset_pay_url":
        await handle_paid_preset_pay_url(query, context)
    elif data == "paid_preset_ip":
        await handle_paid_preset_ip(query, context)
    elif data == "paid_preset_hwid":
        await handle_paid_preset_hwid(query, context)
    elif data == "paid_preset_traffic":
        await handle_paid_preset_traffic(query, context)
    elif data.startswith("paid_sub_view:"):
        await handle_paid_sub_view(query, int(data.split(":")[1]))
    elif data.startswith("paid_sub_toggle:"):
        await handle_paid_sub_toggle(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_delete:"):
        await handle_paid_sub_delete(query, int(data.split(":")[1]), context)
    elif data == "paid_inbounds_menu":
        await handle_paid_inbounds_menu(query)
    elif data.startswith("paid_toggle_inbound:"):
        await handle_paid_toggle_inbound(query, int(data.split(":")[1]))
    elif data == "paid_inbounds_expire_menu":
        await handle_paid_inbounds_expire_menu(query)
    elif data.startswith("paid_toggle_inbound_expire:"):
        await handle_paid_toggle_inbound_expire(query, int(data.split(":")[1]))
    elif data.startswith("paid_sub_freeze:"):
        await handle_paid_sub_freeze(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_extend:"):
        await handle_paid_sub_extend(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_reduce:"):
        await handle_paid_sub_reduce(query, int(data.split(":")[1]), context)
    elif data == "paid_bulk_menu":
        await handle_paid_bulk_menu(query)
    elif data == "paid_bulk_extend":
        await handle_paid_bulk_extend(query, context)
    elif data == "paid_bulk_reduce":
        await handle_paid_bulk_reduce(query, context)
    elif data.startswith("paid_sub_settings:"):
        await handle_paid_sub_settings(query, int(data.split(":")[1]))
    elif data.startswith("paid_sub_edit_expire:"):
        await handle_paid_sub_edit_expire(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_ip:"):
        await handle_paid_sub_edit_ip(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_hwid:"):
        await handle_paid_sub_edit_hwid(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_traffic:"):
        await handle_paid_sub_edit_traffic(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_trial:"):
        await handle_paid_sub_edit_trial(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_pay_period:"):
        await handle_paid_sub_edit_pay_period(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_renew:"):
        await handle_paid_sub_edit_renew_time(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_price:"):
        await handle_paid_sub_edit_price(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_sub_edit_pay_url:"):
        await handle_paid_sub_edit_pay_url(query, int(data.split(":")[1]), context)
    elif data == "paid_history":
        await handle_paid_history(query)
    elif data.startswith("paid_history_page:"):
        await handle_paid_history(query, int(data.split(":")[1]))
    elif data.startswith("paid_history_view:"):
        await handle_paid_history_view(query, int(data.split(":")[1]))
    elif data == "referral_settings":
        await handle_referral_settings(query)
    elif data == "set_referral_bonus":
        await handle_set_referral_bonus(query, context)
    elif data == "promo_menu":
        await handle_promos_menu(query)
    elif data == "promo_create":
        await handle_promo_create(query, context)
    elif data.startswith("promo_view:"):
        await handle_promo_view(query, int(data.split(":")[1]))
    elif data.startswith("promo_toggle:"):
        await handle_promo_toggle(query, int(data.split(":")[1]))
    elif data.startswith("promo_delete:"):
        await handle_promo_delete(query, int(data.split(":")[1]))
    elif data == "paid_auto_update_settings":
        await handle_paid_auto_update_settings(query)
    elif data == "paid_toggle_auto_update":
        await handle_paid_toggle_auto_update(query)
    elif data == "paid_set_auto_update_days":
        await handle_paid_set_auto_update_days(query, context)
    elif data == "paid_run_sync_now":
        await handle_paid_run_sync_now(query)
    elif data == "paid_requests":
        await handle_paid_requests(query)
    elif data == "paid_muted_list":
        await handle_muted_list(query)
    elif data.startswith("paid_mute_user:"):
        await handle_mute_user(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_unmute_user:"):
        await handle_unmute_user(query, int(data.split(":")[1]))
    elif data.startswith("paid_approve:"):
        await handle_approve(query, int(data.split(":")[1]), context)
    elif data.startswith("paid_reject:"):
        await handle_reject(query, int(data.split(":")[1]), context)
    elif data.startswith("confirm_payment:"):
        await handle_confirm_payment(query, int(data.split(":")[1]), context)
    elif data.startswith("reject_payment:"):
        await handle_reject_payment(query, int(data.split(":")[1]), context)
