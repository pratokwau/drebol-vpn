from html import escape

from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID, load_config, save_config
from states import AWAITING_SUPPORT_MSG
from subscription import is_subscribed, subscribe_keyboard, subscribe_text
from handlers.user import (
    handle_buy, handle_about, handle_back_start, handle_my_sub, handle_my_paid_sub,
    handle_news, handle_how_to, handle_renew_sub, handle_i_paid, handle_referral,
    handle_copy_sub, handle_enter_promo, handle_remove_promo,
    handle_qr_code, handle_reissue_key, handle_reissue_do, handle_prices, handle_info,
    handle_pay_invoice, handle_tariff_pick, handle_my_devices, handle_dev_del,
    handle_dev_buy_menu, handle_dev_buy,
)
from handlers.admin import (
    handle_admin_panel, handle_set_channel, handle_git_update,
    handle_set_privacy_url, handle_set_terms_url, handle_documents_menu,
    handle_channel_menu, handle_dashboard, handle_healthcheck,
    handle_find_user, handle_user_profile, handle_ban_user, handle_unban_user,
    handle_log_channel_settings, handle_set_log_channel, handle_clear_log_channel,
    handle_winback_settings, handle_toggle_winback,
    handle_remind_settings, handle_toggle_remind, handle_set_remind,
    handle_set_winback_days, handle_set_winback_percent,
    handle_user_history, handle_dm_user, handle_payment_stats,
)
from fraud import (
    handle_fraud_menu, handle_fraud_toggle, handle_fraud_scan, handle_fraud_ok,
)
from remnawave import (
    handle_rw_menu, handle_rw_url, handle_rw_token, handle_rw_test,
    handle_rw_squads, handle_rw_squad_toggle, handle_rw_migrate,
    handle_rw_migrate_go, handle_rw_switch, handle_rw_notify, handle_rw_notify_go,
)
from backup import (
    handle_backup_menu, handle_backup_export, handle_backup_import,
    handle_backup_apply,
)
from site_deploy import (
    handle_site_menu, handle_site_server, handle_site_domain,
    handle_site_deploy, handle_site_cert, handle_site_delete, handle_site_logo,
    handle_site_check, handle_site_auto,
)
from handlers.support import (
    open_support, handle_support_files, show_topics, show_topic_hint,
    start_writing, handle_support_close,
)
from maintenance import (
    handle_maintenance_menu, handle_maintenance_toggle,
    handle_maintenance_text, handle_feature_toggle,
)
from handlers.control import (
    handle_control_menu, handle_activity_feed, handle_user_activity,
    handle_online, handle_traffic, handle_digest_toggle,
    handle_digest_hour_menu, handle_digest_set_hour, handle_digest_now,
    handle_connect_help_menu, handle_connect_help_toggle, handle_connect_help_set,
)
from staff import (
    is_helper, helper_can, handle_helper_panel,
    handle_helpers_menu, handle_helper_add, handle_helper_del,
)
from handlers.confirm import confirm_gate
from blacklist import (
    handle_bl_menu, handle_bl_list, handle_bl_view, handle_bl_add_start, handle_bl_add_for,
    handle_bl_check_start, handle_bl_add_apply, handle_bl_del, handle_bl_stop, handle_bl_readd,
    handle_bl_sync_now, handle_bl_remote_toggle,
)
from promos import (
    handle_promo_give_start, handle_promo_give_for, handle_promo_give_custom,
    handle_promo_give_pick, handle_promo_give_do, handle_promo_seg, handle_promo_seg_pick,
    handle_promo_seg_preview, handle_promo_seg_do, handle_promo_income,
)
from handlers.payments import (
    handle_payments_menu, handle_payment_view, handle_refund_start, handle_refund_do,
)
from handlers.tariffs import (
    handle_tariffs_menu, handle_tariff_view, handle_tariff_toggle,
    handle_tariff_delete, handle_tariff_delete_confirm, handle_tariff_add,
    handle_tariff_edit,
)
from handlers.payprovider import (
    handle_pay_provider_menu, handle_pay_provider_set,
    handle_platega_set_merchant, handle_platega_set_secret,
    handle_platega_methods, handle_platega_method_set, handle_platega_test,
)
from handlers.broadcast import (
    handle_broadcast_start, handle_broadcast_segment,
    handle_bcast_buttons_add, handle_bcast_buttons_skip,
    handle_bcast_edit_text, handle_bcast_cancel, handle_bcast_send,
    handle_bcast_photo_add, handle_bcast_photo_skip, handle_bcast_photo_del,
)
from handlers.tickets import (
    handle_ticket_list, handle_ticket_view, handle_ticket_reply_start,
    handle_ticket_files, handle_ticket_quick, handle_ticket_send_quick,
    handle_ticket_close, handle_quick_menu, handle_quick_add, handle_quick_del,
)
from handlers.xui_settings import (
    handle_xui_settings, handle_set_xui_url, handle_set_xui_token,
    handle_set_xui_sub_port, handle_set_xui_sub_path,
    handle_test_xui, handle_nodes_menu, handle_node_set,
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
    handle_paid_create_sub, handle_paid_create_type,
    handle_paid_sub_view, handle_paid_sub_delete, handle_paid_sub_toggle,
    handle_paid_inbounds_menu, handle_paid_toggle_inbound,
    handle_paid_inbounds_expire_menu, handle_paid_toggle_inbound_expire,
    handle_approve, handle_reject, handle_request_sub,
    handle_paid_sub_freeze, handle_paid_sub_extend, handle_paid_sub_reduce,
    handle_paid_bulk_menu, handle_paid_bulk_extend, handle_paid_bulk_reduce,
    handle_paid_bulk_ip, handle_paid_bulk_hwid, handle_paid_bulk_limits_apply,
    handle_paid_device_price, handle_paid_device_max,
    handle_paid_devices, handle_paid_ips, handle_paid_hwid_del,
    handle_paid_hwid_clear, handle_paid_ips_clear,
    handle_paid_fix_renew, handle_paid_fix_renew_apply,
    handle_paid_sub_settings, handle_paid_sub_edit_expire,
    handle_paid_sub_edit_ip, handle_paid_sub_edit_hwid, handle_paid_sub_edit_traffic,
    handle_paid_sub_edit_trial, handle_paid_sub_edit_pay_period,
    handle_paid_sub_edit_renew_time, handle_paid_sub_edit_price, handle_paid_sub_edit_pay_url,
    handle_confirm_payment, handle_reject_payment,
    handle_paid_history, handle_paid_history_view, handle_mute_user, handle_unmute_user, handle_muted_list,
    handle_paid_requests,
    handle_paid_auto_update_settings, handle_paid_toggle_auto_update,
    handle_paid_set_auto_update_days, handle_paid_run_sync_now,
    handle_referral_settings, handle_set_referral_bonus, handle_set_referral_invited_bonus,
    handle_promos_menu, handle_promo_view, handle_promo_create,
    handle_promo_toggle, handle_promo_delete,
    handle_toggle_auto_trial, handle_paid_bulk_apply,
)


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    adm = _is_admin(update)
    # Помощнику открыты только разделы поддержки — белым списком
    helper = not adm and is_helper(update.effective_user.id)
    staff_cb = helper and helper_can(data)

    if data == "noop":
        return

    # Опасные кнопки админки: сначала «Точно?», выполняем только после «Да»
    if adm:
        data = await confirm_gate(query, data)
        if data is None:
            return

    # Техработы и выключенные функции. На админа и на работу помощника не действуют.
    if not adm and not staff_cb:
        import maintenance as mnt
        if mnt.is_maintenance():
            context.user_data.pop("state", None)
            await mnt.show_maintenance(query=query)
            return
        feat = mnt.feature_for_callback(data)
        if data == "my_paid_sub":
            from paidsub.storage import get_paid_sub_by_tg_id
            has_sub = await get_paid_sub_by_tg_id(update.effective_user.id)
            # без подписки эта кнопка ведёт к выдаче триала
            feat = "subscription" if has_sub else "trial"
        if feat and not mnt.feature_enabled(feat):
            await mnt.show_feature_off(feat, query=query)
            return

    # Проверка бана
    if not adm and data != "check_sub":
        from database import is_banned
        if await is_banned(update.effective_user.id):
            await query.edit_message_text(
                "🚫 <b>Аккаунт заблокирован</b>\n\n"
                "<i>Если это ошибка — свяжитесь с администратором.</i>", parse_mode="HTML")
            return

    # Чёрный список: остаётся только поддержка — чтобы можно было оспорить
    if not adm and not staff_cb:
        from blacklist import entry as bl_entry, user_may, show_blocked
        if not user_may(data):
            ble = await bl_entry(update.effective_user.id)
            if ble:
                context.user_data.pop("state", None)
                await show_blocked(ble, query=query)
                return

    # Проверка подписки для не-админов
    if data != "check_sub" and not adm and not staff_cb:
        if not await is_subscribed(context.bot, update.effective_user.id):
            user = update.effective_user
            await query.edit_message_text(
                subscribe_text(user.first_name),
                parse_mode="HTML",
                reply_markup=subscribe_keyboard(),
            )
            return

    if data == "check_sub":
        user = update.effective_user
        if not await is_subscribed(context.bot, user.id):
            await query.edit_message_text(
                subscribe_text(user.first_name, retry=True),
                parse_mode="HTML",
                reply_markup=subscribe_keyboard(),
            )
            return
        # подписался на канал — сразу выдаём пробный период и показываем его
        from handlers.user import ensure_trial, start_screen
        fresh = await ensure_trial(
            user, context,
            on_start=lambda: query.edit_message_text("⏳ Готовлю ваш доступ…"))
        text, markup = await start_screen(user, fresh=fresh)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup,
                                      disable_web_page_preview=True)
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
    elif data == "pay_invoice":
        await handle_pay_invoice(query, context)
    elif data.startswith("pay_invoice:"):
        _p = data.split(":")
        await handle_pay_invoice(query, context, int(_p[1]),
                                 int(_p[2]) if len(_p) > 2 else None)
    elif data.startswith("tariff_pick:"):
        _p = data.split(":")
        await handle_tariff_pick(query, context, int(_p[1]),
                                 int(_p[2]) if len(_p) > 2 else None)
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
    elif data == "prices":
        await handle_prices(query)
    elif data == "referral":
        await handle_referral(query, context)
    elif data == "copy_sub":
        await handle_copy_sub(query, context)
    elif data == "info":
        await handle_info(query)
    elif data == "qr_code":
        await handle_qr_code(query, context)
    elif data == "reissue_key":
        await handle_reissue_key(query, context)
    elif data == "reissue_do":
        await handle_reissue_do(query, context)
    elif data == "my_devices":
        await handle_my_devices(query, context)
    elif data.startswith("dev_del:"):
        await handle_dev_del(query, context, data.split(":", 1)[1])
    elif data == "dev_buy_menu":
        await handle_dev_buy_menu(query, context)
    elif data.startswith("dev_buy:"):
        await handle_dev_buy(query, context, int(data.split(":")[1]))
    elif data == "support_open":
        context.user_data["state"] = AWAITING_SUPPORT_MSG
        await open_support(query, update.effective_user.id)
    elif data == "support_topics":
        await show_topics(query)
    elif data.startswith("support_topic:"):
        await show_topic_hint(query, context, data.split(":")[1])
    elif data.startswith("support_write:"):
        await start_writing(query, context, data.split(":")[1])
    elif data == "support_close":
        context.user_data.pop("state", None)
        await handle_support_close(query, update.effective_user.id)
    elif data == "support_files":
        context.user_data["state"] = AWAITING_SUPPORT_MSG
        await handle_support_files(query, update.effective_user.id)
    elif data.startswith("support_page:"):
        page = int(data.split(":")[1])
        context.user_data["state"] = AWAITING_SUPPORT_MSG
        await open_support(query, update.effective_user.id, page)

    # ── Только админ ─────────────────────────────────────────────────────────
    elif not adm and not staff_cb:
        await query.edit_message_text("⛔ Нет доступа.")

    elif data == "admin_panel":
        context.user_data.pop("state", None)
        if helper:
            await handle_helper_panel(query)
        else:
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
    elif data == "mnt_menu":
        await handle_maintenance_menu(query, context)
    elif data == "mnt_toggle":
        await handle_maintenance_toggle(query, context)
    elif data == "mnt_text":
        await handle_maintenance_text(query, context)
    elif data.startswith("mnt_feature:"):
        await handle_feature_toggle(query, context, data.split(":", 1)[1])
    elif data == "ctl_menu":
        await handle_control_menu(query, context)
    elif data.startswith("act_feed:"):
        _, scope, pg = data.split(":")
        await handle_activity_feed(query, scope, int(pg))
    elif data.startswith("user_activity:"):
        _, uid, pg = data.split(":")
        await handle_user_activity(query, int(uid), int(pg))
    elif data == "ctl_online":
        await handle_online(query)
    elif data == "ctl_traffic":
        await handle_traffic(query)
    elif data == "ctl_digest_toggle":
        await handle_digest_toggle(query, context)
    elif data == "ctl_digest_hour":
        await handle_digest_hour_menu(query)
    elif data.startswith("ctl_digest_set:"):
        await handle_digest_set_hour(query, context, int(data.split(":")[1]))
    elif data == "ctl_digest_now":
        await handle_digest_now(query, context)
    elif data == "ctl_ch_menu":
        await handle_connect_help_menu(query, context)
    elif data == "ctl_ch_toggle":
        await handle_connect_help_toggle(query, context)
    elif data.startswith("ctl_ch_set:"):
        await handle_connect_help_set(query, context, int(data.split(":")[1]))
    elif data == "helpers_menu":
        await handle_helpers_menu(query, context)
    elif data == "helper_add":
        await handle_helper_add(query, context)
    elif data.startswith("helper_del:"):
        await handle_helper_del(query, context, int(data.split(":")[1]))

    # Чёрный список
    elif data == "bl_menu":
        await handle_bl_menu(query, context)
    elif data.startswith("bl_list:"):
        _, scope, pg = data.split(":")
        await handle_bl_list(query, scope, int(pg))
    elif data.startswith("bl_view:"):
        await handle_bl_view(query, int(data.split(":")[1]))
    elif data == "bl_add":
        await handle_bl_add_start(query, context)
    elif data == "bl_check":
        await handle_bl_check_start(query, context)
    elif data.startswith("bl_add_for:"):
        await handle_bl_add_for(query, context, int(data.split(":")[1]))
    elif data == "bl_add_apply":
        await handle_bl_add_apply(query, context)
    elif data.startswith("bl_del:"):
        await handle_bl_del(query, context, int(data.split(":")[1]))
    elif data.startswith("bl_stop:"):
        await handle_bl_stop(query, context, int(data.split(":")[1]))
    elif data.startswith("bl_readd:"):
        await handle_bl_readd(query, context, int(data.split(":")[1]))
    elif data == "bl_sync":
        await handle_bl_sync_now(query, context)
    elif data == "bl_remote_toggle":
        await handle_bl_remote_toggle(query, context)
    elif data.startswith("payments:"):
        _, st, pg = data.split(":")
        await handle_payments_menu(query, context, st, int(pg))
    elif data.startswith("payment_view:"):
        await handle_payment_view(query, int(data.split(":")[1]))
    elif data.startswith("refund_start:"):
        await handle_refund_start(query, int(data.split(":")[1]))
    elif data.startswith("refund_do:"):
        _, pid, rv = data.split(":")
        await handle_refund_do(query, context, int(pid), rv == "1")
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
    elif data == "rw_menu":
        await handle_rw_menu(query, context)
    elif data == "rw_url":
        await handle_rw_url(query, context)
    elif data == "rw_token":
        await handle_rw_token(query, context)
    elif data == "rw_test":
        await handle_rw_test(query, context)
    elif data == "rw_squads":
        await handle_rw_squads(query, context)
    elif data.startswith("rw_squad:"):
        await handle_rw_squad_toggle(query, context, data.split(":", 1)[1])
    elif data == "rw_migrate":
        await handle_rw_migrate(query, context)
    elif data == "rw_migrate_go":
        await handle_rw_migrate_go(query, context)
    elif data == "rw_switch":
        await handle_rw_switch(query, context)
    elif data == "rw_notify":
        await handle_rw_notify(query, context)
    elif data == "rw_notify_go":
        await handle_rw_notify_go(query, context)
    elif data == "backup_menu":
        await handle_backup_menu(query, context)
    elif data == "backup_export":
        await handle_backup_export(query, context)
    elif data == "backup_import":
        await handle_backup_import(query, context)
    elif data == "backup_apply":
        await handle_backup_apply(query, context)
    elif data == "site_menu":
        context.user_data.pop("state", None)
        await handle_site_menu(query)
    elif data == "site_server":
        await handle_site_server(query, context)
    elif data == "site_domain":
        await handle_site_domain(query, context)
    elif data == "site_logo":
        await handle_site_logo(query, context)
    elif data == "site_deploy":
        await handle_site_deploy(query, context)
    elif data == "site_cert":
        await handle_site_cert(query, context)
    elif data == "site_check":
        await handle_site_check(query, context)
    elif data == "site_auto":
        await handle_site_auto(query, context)
    elif data == "site_delete":
        await handle_site_delete(query, context)
    elif data == "fraud_menu":
        await handle_fraud_menu(query)
    elif data == "fraud_toggle":
        await handle_fraud_toggle(query)
    elif data == "fraud_scan":
        await handle_fraud_scan(query, context)
    elif data.startswith("fraud_ok:"):
        _f = data.split(":")
        await handle_fraud_ok(query, int(_f[1]), int(_f[2]))
    elif data == "remind_settings":
        await handle_remind_settings(query)
    elif data == "toggle_remind":
        await handle_toggle_remind(query)
    elif data == "set_remind_first":
        await handle_set_remind(query, context, "first")
    elif data == "set_remind_second":
        await handle_set_remind(query, context, "second")
    elif data == "winback_settings":
        await handle_winback_settings(query)
    elif data == "toggle_winback":
        await handle_toggle_winback(query)
    elif data == "set_winback_days":
        await handle_set_winback_days(query, context)
    elif data == "set_winback_percent":
        await handle_set_winback_percent(query, context)
    elif data == "toggle_auto_trial":
        await handle_toggle_auto_trial(query)
    elif data == "broadcast":
        await handle_broadcast_start(query, context)
    elif data.startswith("bcast_seg:"):
        await handle_broadcast_segment(query, context, data.split(":")[1])
    elif data == "bcast_buttons_add":
        await handle_bcast_buttons_add(query, context)
    elif data == "bcast_buttons_skip":
        await handle_bcast_buttons_skip(query, context)
    elif data == "bcast_photo_add":
        await handle_bcast_photo_add(query, context)
    elif data == "bcast_photo_skip":
        await handle_bcast_photo_skip(query, context)
    elif data == "bcast_photo_del":
        await handle_bcast_photo_del(query, context)
    elif data == "bcast_edit_text":
        await handle_bcast_edit_text(query, context)
    elif data == "bcast_send":
        await handle_bcast_send(query, context)
    elif data == "bcast_cancel":
        await handle_bcast_cancel(query, context)

    # Тикеты
    elif data.startswith("ticket_list:"):
        await handle_ticket_list(query, int(data.split(":")[1]))
    elif data.startswith("ticket_tab:"):
        _t = data.split(":")
        await handle_ticket_list(query, int(_t[2]), _t[1])
    elif data.startswith("ticket_quick:"):
        await handle_ticket_quick(query, int(data.split(":")[1]))
    elif data.startswith("ticket_send:"):
        _t = data.split(":")
        await handle_ticket_send_quick(query, int(_t[1]), int(_t[2]), context)
    elif data.startswith("ticket_close:"):
        await handle_ticket_close(query, int(data.split(":")[1]), context)
    elif data == "quick_menu":
        await handle_quick_menu(query)
    elif data == "quick_add":
        await handle_quick_add(query, context)
    elif data.startswith("quick_del:"):
        await handle_quick_del(query, int(data.split(":")[1]))
    elif data.startswith("ticket_view:"):
        _, uid, page = data.split(":")
        await handle_ticket_view(query, int(uid), int(page))
    elif data.startswith("ticket_files:"):
        await handle_ticket_files(query, int(data.split(":")[1]))
    elif data.startswith("ticket_reply:"):
        await handle_ticket_reply_start(query, int(data.split(":")[1]), context)

    # 3x-UI
    elif data == "xui_settings":
        # сюда же ведёт «◀️ К серверам» из ввода адреса/токена — ввод отменяем
        context.user_data.pop("state", None)
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
    elif data == "nodes_menu":
        await handle_nodes_menu(query, context)
    elif data.startswith("node_set:"):
        await handle_node_set(query, context, data.split(":", 1)[1])

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
    elif data.startswith("paid_create_type:"):
        await handle_paid_create_type(query, context, data.split(":")[1] == "trial")
    elif data == "tariffs_menu":
        await handle_tariffs_menu(query, context)
    elif data == "tariff_add":
        await handle_tariff_add(query, context)
    elif data.startswith("tariff_view:"):
        await handle_tariff_view(query, int(data.split(":")[1]))
    elif data.startswith("tariff_toggle:"):
        await handle_tariff_toggle(query, context, int(data.split(":")[1]))
    elif data.startswith("tariff_del_ok:"):
        await handle_tariff_delete_confirm(query, context, int(data.split(":")[1]))
    elif data.startswith("tariff_del:"):
        await handle_tariff_delete(query, int(data.split(":")[1]))
    elif data.startswith("tariff_price:"):
        await handle_tariff_edit(query, context, int(data.split(":")[1]), "price")
    elif data.startswith("tariff_period:"):
        await handle_tariff_edit(query, context, int(data.split(":")[1]), "period")
    elif data.startswith("tariff_name:"):
        await handle_tariff_edit(query, context, int(data.split(":")[1]), "name")
    elif data == "pay_provider_menu":
        await handle_pay_provider_menu(query, context)
    elif data.startswith("pay_provider_set:"):
        await handle_pay_provider_set(query, context, data.split(":")[1])
    elif data == "platega_set_merchant":
        await handle_platega_set_merchant(query, context)
    elif data == "platega_set_secret":
        await handle_platega_set_secret(query, context)
    elif data == "platega_methods":
        await handle_platega_methods(query, context)
    elif data.startswith("platega_method:"):
        await handle_platega_method_set(query, context, int(data.split(":")[1]))
    elif data == "platega_test":
        await handle_platega_test(query, context)
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
    elif data.startswith("paid_devices:"):
        await handle_paid_devices(query, int(data.split(":")[1]))
    elif data.startswith("paid_ips:"):
        await handle_paid_ips(query, int(data.split(":")[1]))
    elif data.startswith("paid_hwid_del:"):
        _, sid, ref = data.split(":", 2)
        await handle_paid_hwid_del(query, context, int(sid), ref)
    elif data.startswith("paid_hwid_clear:"):
        await handle_paid_hwid_clear(query, context, int(data.split(":")[1]))
    elif data.startswith("paid_ips_clear:"):
        await handle_paid_ips_clear(query, context, int(data.split(":")[1]))
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
    elif data == "paid_device_price":
        await handle_paid_device_price(query, context)
    elif data == "paid_device_max":
        await handle_paid_device_max(query, context)
    elif data == "paid_bulk_ip":
        await handle_paid_bulk_ip(query, context)
    elif data == "paid_bulk_hwid":
        await handle_paid_bulk_hwid(query, context)
    elif data == "paid_bulk_limits_apply":
        await handle_paid_bulk_limits_apply(query, context)
    elif data == "paid_bulk_apply":
        await handle_paid_bulk_apply(query, context)
    elif data == "paid_fix_renew":
        await handle_paid_fix_renew(query, context)
    elif data == "paid_fix_renew_apply":
        await handle_paid_fix_renew_apply(query, context)
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
    elif data == "set_referral_invited_bonus":
        await handle_set_referral_invited_bonus(query, context)
    elif data == "promo_menu":
        await handle_promos_menu(query)
    elif data == "promo_create":
        await handle_promo_create(query, context)
    elif data == "promo_give":
        await handle_promo_give_start(query, context)
    elif data.startswith("promo_give_for:"):
        await handle_promo_give_for(query, context, int(data.split(":")[1]))
    elif data.startswith("promo_give_custom:"):
        await handle_promo_give_custom(query, context, int(data.split(":")[1]))
    elif data.startswith("promo_give_pick:"):
        _, uid, kind, val = data.split(":")
        await handle_promo_give_pick(query, context, int(uid), kind, int(val))
    elif data.startswith("promo_give_do:"):
        _, uid, kind, val = data.split(":")
        await handle_promo_give_do(query, context, int(uid), kind, int(val))
    elif data == "promo_seg":
        await handle_promo_seg(query, context)
    elif data.startswith("promo_seg_pick:"):
        await handle_promo_seg_pick(query, context, data.split(":")[1])
    elif data.startswith("promo_seg_val:"):
        _, kind, val, seg = data.split(":")
        await handle_promo_seg_preview(query, context, kind, int(val), seg)
    elif data == "promo_seg_do":
        await handle_promo_seg_do(query, context)
    elif data == "promo_income":
        await handle_promo_income(query)
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
