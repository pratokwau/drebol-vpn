from datetime import datetime, timedelta

from telegram import Bot
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config
from keyboards import back_admin, back_main

from paidsub.storage import (
    list_paid_subs, add_paid_sub, get_paid_sub, delete_paid_sub, get_paid_sub_by_tg_id,
    add_request, get_pending_request, resolve_request,
    update_paid_sub_field, get_expired_paid_subs,
    add_history, list_history, get_history_entry,
    get_muted_until, set_mute, clear_mute, list_muted,
    list_pending_requests, list_pending_payments,
    get_referrer, mark_referral_rewarded, get_all_referral_stats,
)
from paidsub.keyboards import (
    paid_subs_list_keyboard, paid_presets_keyboard, paid_sub_view_keyboard,
    paid_inbounds_keyboard, approve_keyboard, paid_sub_settings_keyboard,
    paid_history_keyboard, payment_approve_keyboard, muted_list_keyboard,
)
from paidsub.time_parser import fmt_duration


async def _notify_user(bot: Bot, tg_id, text: str):
    if not tg_id:
        return
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML")
    except Exception:
        pass


def _paid_presets_ready(cfg: dict) -> bool:
    return all([
        cfg.get("paid_trial_period") is not None,
        cfg.get("paid_pay_period") is not None,
        cfg.get("paid_renew_time") is not None,
        cfg.get("paid_preset_ip") is not None,
        cfg.get("paid_preset_hwid") is not None,
        cfg.get("paid_preset_traffic") is not None,
        cfg.get("paid_price") is not None,
    ])


def _fmt_presets(cfg: dict, inbound_names=None) -> str:
    trial = cfg.get("paid_trial_period")
    trial_str = fmt_duration(trial) if trial else "не задан"

    pay_period = cfg.get("paid_pay_period")
    pay_str = fmt_duration(pay_period) if pay_period else "не задан"

    renew = cfg.get("paid_renew_time")
    renew_str = fmt_duration(renew) if renew else "не задан"

    price = cfg.get("paid_price")
    price_str = f"{price} ₽" if price is not None else "не задана"

    pay_url = cfg.get("paid_pay_url") or "не задана"

    ip = cfg.get("paid_preset_ip", "не задан")
    hwid = cfg.get("paid_preset_hwid", "не задан")
    traf_raw = cfg.get("paid_preset_traffic")
    if traf_raw is None:
        traf = "не задан"
    elif traf_raw == 0:
        traf = "безлимит"
    else:
        traf = f"{traf_raw} ГБ"

    create_ids = cfg.get("paid_preset_inbound_ids") or []
    if create_ids and inbound_names:
        create_label = ", ".join(inbound_names.get(i, f"#{i}") for i in create_ids)
    elif create_ids:
        create_label = ", ".join(str(i) for i in create_ids)
    else:
        create_label = "авто (первый VLESS)"

    expire_ids = cfg.get("paid_expire_inbound_ids") or []
    if expire_ids and inbound_names:
        expire_label = ", ".join(inbound_names.get(i, f"#{i}") for i in expire_ids)
    elif expire_ids:
        expire_label = ", ".join(str(i) for i in expire_ids)
    else:
        expire_label = "не заданы"

    return (
        f"🆓 Пробный период: <b>{trial_str}</b>\n"
        f"💰 Период оплаты: <b>{pay_str}</b>\n"
        f"⏳ Время на продление: <b>{renew_str}</b>\n"
        f"💵 Сумма: <b>{price_str}</b>\n"
        f"🔗 Ссылка на оплату: <b>{pay_url}</b>\n"
        f"🌐 Лимит IP: <b>{ip}</b>\n"
        f"🖥 Лимит HWID: <b>{hwid}</b>\n"
        f"📶 Трафик: <b>{traf}</b>\n"
        f"📡 Инбаунды создания: <b>{create_label}</b>\n"
        f"📡 Инбаунды окончания: <b>{expire_label}</b>"
    )


# ── Список подписок ──────────────────────────────────────────────────────────

async def handle_paid_subs_menu(query, page: int = 1):
    rows, total_pages = await list_paid_subs(page)
    cfg = load_config()
    ready = _paid_presets_ready(cfg)
    header = "💳 <b>Платные подписки</b>\n"
    body = "\n\nПодписок пока нет." if not rows else f"\n\nСтр. {page}/{total_pages}"
    if not ready:
        body += "\n\n⚠️ Задай настройки, чтобы создавать подписки."
    await query.edit_message_text(
        header + body,
        parse_mode="HTML",
        reply_markup=paid_subs_list_keyboard(rows, page, total_pages, ready),
    )


# ── Настройки ─────────────────────────────────────────────────────────────────

async def handle_paid_presets_menu(query):
    cfg = load_config()
    inbound_names = {}
    all_ids = list(cfg.get("paid_preset_inbound_ids") or []) + list(cfg.get("paid_expire_inbound_ids") or [])
    if all_ids:
        from xui_api import get_inbounds
        result = await get_inbounds()
        if result["success"]:
            for inb in result["inbounds"]:
                inbound_names[inb.get("id")] = inb.get("tag") or inb.get("remark") or f"#{inb.get('id')}"
    await query.edit_message_text(
        "⚙️ <b>Настройки платной подписки</b>\n\n"
        + _fmt_presets(cfg, inbound_names)
        + "\n\nВыбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=paid_presets_keyboard(),
    )


_TIME_HINT = (
    "Введи время в свободной форме:\n"
    "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, "
    "<code>44 минуты</code>, <code>3 месяца</code>"
)


async def handle_paid_preset_trial(query, context):
    from states import AWAITING_PAID_TRIAL_PERIOD
    context.user_data["state"] = AWAITING_PAID_TRIAL_PERIOD
    cfg = load_config()
    current = cfg.get("paid_trial_period")
    cur_str = fmt_duration(current) if current else "не задан"
    await query.edit_message_text(
        f"🆓 <b>Пробный период</b>\n\nСейчас: <b>{cur_str}</b>\n\n{_TIME_HINT}",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_pay_period(query, context):
    from states import AWAITING_PAID_PAY_PERIOD
    context.user_data["state"] = AWAITING_PAID_PAY_PERIOD
    cfg = load_config()
    current = cfg.get("paid_pay_period")
    cur_str = fmt_duration(current) if current else "не задан"
    await query.edit_message_text(
        f"💰 <b>Период оплаты</b>\n\nВремя действия подписки после оплаты.\n"
        f"Сейчас: <b>{cur_str}</b>\n\n{_TIME_HINT}",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_renew(query, context):
    from states import AWAITING_PAID_RENEW_TIME
    context.user_data["state"] = AWAITING_PAID_RENEW_TIME
    cfg = load_config()
    current = cfg.get("paid_renew_time")
    cur_str = fmt_duration(current) if current else "не задан"
    await query.edit_message_text(
        f"⏳ <b>Время на продление</b>\n\nПосле окончания пробного или оплаченного периода "
        f"у пользователя будет это время чтобы продлить.\n"
        f"Сейчас: <b>{cur_str}</b>\n\n{_TIME_HINT}",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_price(query, context):
    from states import AWAITING_PAID_PRICE
    context.user_data["state"] = AWAITING_PAID_PRICE
    cfg = load_config()
    current = cfg.get("paid_price")
    cur_str = f"{current} ₽" if current is not None else "не задана"
    await query.edit_message_text(
        f"💵 <b>Сумма подписки</b>\n\nСейчас: <b>{cur_str}</b>\n\nВведи сумму в рублях (число):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_pay_url(query, context):
    from states import AWAITING_PAID_PAY_URL
    context.user_data["state"] = AWAITING_PAID_PAY_URL
    cfg = load_config()
    current = cfg.get("paid_pay_url") or "не задана"
    await query.edit_message_text(
        f"🔗 <b>Ссылка на оплату</b>\n\nСейчас: <b>{current}</b>\n\nВведи URL:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_ip(query, context):
    from states import AWAITING_PAID_PRESET_IP
    context.user_data["state"] = AWAITING_PAID_PRESET_IP
    await query.edit_message_text(
        "🌐 <b>Лимит IP</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_hwid(query, context):
    from states import AWAITING_PAID_PRESET_HWID
    context.user_data["state"] = AWAITING_PAID_PRESET_HWID
    await query.edit_message_text(
        "🖥 <b>Лимит HWID</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_traffic(query, context):
    from states import AWAITING_PAID_PRESET_TRAFFIC
    context.user_data["state"] = AWAITING_PAID_PRESET_TRAFFIC
    await query.edit_message_text(
        "📶 <b>Трафик (ГБ)</b>\n\nВведи число в ГБ или <code>-</code> для безлимита:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Инбаунды создания ────────────────────────────────────────────────────────

async def handle_paid_inbounds_menu(query):
    from xui_api import get_inbounds
    await query.edit_message_text("⏳ Загружаю инбаунды из панели...")
    result = await get_inbounds()
    if not result["success"]:
        await query.edit_message_text(
            f"❌ Не удалось загрузить инбаунды:\n<code>{result['error']}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    if not result["inbounds"]:
        await query.edit_message_text("❌ На панели нет инбаундов.", reply_markup=back_admin())
        return
    cfg = load_config()
    selected = cfg.get("paid_preset_inbound_ids") or []
    await query.edit_message_text(
        "📡 <b>Инбаунды создания</b>\n\n"
        "Эти инбаунды будут использоваться при создании подписки.\n"
        "✅ — выбран, 🔘 — не выбран",
        parse_mode="HTML",
        reply_markup=paid_inbounds_keyboard(result["inbounds"], selected, "create"),
    )


async def handle_paid_toggle_inbound(query, inbound_id: int):
    from xui_api import get_inbounds
    cfg = load_config()
    selected = list(cfg.get("paid_preset_inbound_ids") or [])
    if inbound_id in selected:
        selected.remove(inbound_id)
    else:
        selected.append(inbound_id)
    cfg["paid_preset_inbound_ids"] = selected
    save_config(cfg)
    result = await get_inbounds()
    if not result["success"]:
        await query.answer("Не удалось обновить", show_alert=True)
        return
    await query.edit_message_text(
        "📡 <b>Инбаунды создания</b>\n\n"
        "Эти инбаунды будут использоваться при создании подписки.\n"
        "✅ — выбран, 🔘 — не выбран",
        parse_mode="HTML",
        reply_markup=paid_inbounds_keyboard(result["inbounds"], selected, "create"),
    )


# ── Инбаунды окончания ───────────────────────────────────────────────────────

async def handle_paid_inbounds_expire_menu(query):
    from xui_api import get_inbounds
    await query.edit_message_text("⏳ Загружаю инбаунды из панели...")
    result = await get_inbounds()
    if not result["success"]:
        await query.edit_message_text(
            f"❌ Не удалось загрузить инбаунды:\n<code>{result['error']}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    if not result["inbounds"]:
        await query.edit_message_text("❌ На панели нет инбаундов.", reply_markup=back_admin())
        return
    cfg = load_config()
    selected = cfg.get("paid_expire_inbound_ids") or []
    await query.edit_message_text(
        "📡 <b>Инбаунды окончания</b>\n\n"
        "Бот переключит подписку на эти инбаунды если не продлили.\n"
        "✅ — выбран, 🔘 — не выбран",
        parse_mode="HTML",
        reply_markup=paid_inbounds_keyboard(result["inbounds"], selected, "expire"),
    )


async def handle_paid_toggle_inbound_expire(query, inbound_id: int):
    from xui_api import get_inbounds
    cfg = load_config()
    selected = list(cfg.get("paid_expire_inbound_ids") or [])
    if inbound_id in selected:
        selected.remove(inbound_id)
    else:
        selected.append(inbound_id)
    cfg["paid_expire_inbound_ids"] = selected
    save_config(cfg)
    result = await get_inbounds()
    if not result["success"]:
        await query.answer("Не удалось обновить", show_alert=True)
        return
    await query.edit_message_text(
        "📡 <b>Инбаунды окончания</b>\n\n"
        "Бот переключит подписку на эти инбаунды если не продлили.\n"
        "✅ — выбран, 🔘 — не выбран",
        parse_mode="HTML",
        reply_markup=paid_inbounds_keyboard(result["inbounds"], selected, "expire"),
    )


# ── Ручное создание подписки (админ) ─────────────────────────────────────────

async def handle_paid_create_sub(query, context):
    cfg = load_config()
    if not _paid_presets_ready(cfg):
        await query.edit_message_text(
            "⚠️ Сначала задай все настройки (кнопка ⚙️ Настройки).",
            reply_markup=back_admin(),
        )
        return
    from states import AWAITING_PAID_SUB_TG_ID
    context.user_data["state"] = AWAITING_PAID_SUB_TG_ID
    await query.edit_message_text(
        "👤 <b>Введи Telegram ID пользователя</b>\n\n"
        "Введи числовой ID:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def do_create_paid_sub(query_or_msg, tg_id: int, context, reply_func, trial: bool = False):
    """Создаёт платную подписку. trial=True — пробный период."""
    cfg = load_config()
    await reply_func("⏳ Создаю подписку в 3x-UI...")

    from xui_api import create_client, build_email
    from database import get_user_info
    user_row = await get_user_info(tg_id)
    username = user_row[2] if user_row else None
    email = build_email(tg_id, username, prefix="paid_")

    renew_seconds = cfg.get("paid_renew_time", 86400)
    if trial:
        period_seconds = cfg.get("paid_trial_period", 86400)
    else:
        period_seconds = cfg.get("paid_pay_period", 2592000)

    total_seconds = period_seconds + renew_seconds
    expire_dt = datetime.now() + timedelta(seconds=total_seconds)
    expire_date = expire_dt.strftime("%d.%m.%Y %H:%M:%S")

    paid_inbound_ids = cfg.get("paid_preset_inbound_ids") or []
    result = await create_client(
        expire_date=expire_date,
        limit_ip=int(cfg.get("paid_preset_ip", 0)),
        limit_hwid=int(cfg.get("paid_preset_hwid", 0)),
        total_gb=int(cfg.get("paid_preset_traffic", 0)),
        email=email,
        preset_inbound_ids_override=paid_inbound_ids if paid_inbound_ids else None,
    )

    if not result["success"]:
        await reply_func(
            f"❌ <b>Ошибка создания подписки</b>\n\n<code>{result['error']}</code>",
            parse_mode="HTML",
        )
        return

    new_sub_id = await add_paid_sub(
        tg_id=tg_id,
        email=result["email"],
        uuid_val=result["uuid"],
        sub_id=result["sub_id"],
        sub_url=result["sub_url"],
        expire_date=result["expire"],
        limit_ip=int(cfg.get("paid_preset_ip", 0)),
        limit_hwid=int(cfg.get("paid_preset_hwid", 0)),
        total_gb=int(cfg.get("paid_preset_traffic", 0)),
    )

    if not trial:
        await update_paid_sub_field(new_sub_id, "times_renewed", 1)

    traffic_str = f"{cfg.get('paid_preset_traffic', 0)} ГБ" if int(cfg.get("paid_preset_traffic", 0)) > 0 else "безлимит"
    period_label = "пробный период" if trial else "оплаченный период"

    await add_history(
        tg_id, "sub_created",
        f"Подписка #{new_sub_id} ({period_label})\nEmail: {result['email']}\nДо: {result['expire']}",
    )

    await reply_func(
        f"✅ <b>Подписка создана ({period_label})!</b>\n\n"
        f"👤 TG ID: <code>{tg_id}</code>\n"
        f"📧 Email: <code>{result['email']}</code>\n"
        f"📅 До: <b>{result['expire']}</b>\n"
        f"📶 Трафик: <b>{traffic_str}</b>\n\n"
        f"🔗 Ссылка:\n<code>{result['sub_url']}</code>",
        parse_mode="HTML",
    )

    bot = context.bot if hasattr(context, 'bot') else None
    if bot:
        await _notify_user(bot, tg_id,
            f"🎉 <b>Вам выдана VPN подписка ({period_label})!</b>\n\n"
            f"📅 Действует до: <b>{result['expire']}</b>\n"
            f"📶 Трафик: <b>{traffic_str}</b>\n\n"
            f"🔗 Ссылка подписки:\n<code>{result['sub_url']}</code>\n\n"
            "Скопируй ссылку и вставь в приложение (Happ или INCY)"
        )


# ── Запрос на одобрение подписки (от юзера) ──────────────────────────────────

async def handle_request_sub(query, context):
    """Юзер нажал '👤 Моя подписка' и у него нет подписки — отправляем запрос админу."""
    user = query.from_user
    cfg = load_config()
    if not _paid_presets_ready(cfg):
        await query.edit_message_text(
            "👤 <b>Моя подписка</b>\n\nПодписки пока недоступны. Попробуйте позже.",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return

    muted = await get_muted_until(user.id)
    if muted:
        muted_dt = None
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                muted_dt = datetime.strptime(muted, fmt)
                break
            except ValueError:
                continue
        if muted_dt and datetime.now() < muted_dt:
            await query.edit_message_text(
                "👤 <b>Моя подписка</b>\n\n"
                f"🔇 Запросы заблокированы до <b>{muted}</b>.\n"
                "Обратитесь к администратору.",
                parse_mode="HTML",
                reply_markup=back_main(),
            )
            return

    pending = await get_pending_request(user.id)
    if pending:
        await query.edit_message_text(
            "👤 <b>Моя подписка</b>\n\n"
            "⏳ Вы уже отправили запрос. Ожидайте ответа администратора.",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return

    await add_request(user.id)

    uname = f"@{user.username}" if user.username else f"id{user.id}"
    trial_sec = cfg.get("paid_trial_period", 86400)
    pay_sec = cfg.get("paid_pay_period", 2592000)
    renew_sec = cfg.get("paid_renew_time", 86400)
    ip = cfg.get("paid_preset_ip", 0)
    hwid = cfg.get("paid_preset_hwid", 0)
    traf_raw = cfg.get("paid_preset_traffic", 0)
    traf_str = f"{traf_raw} ГБ" if traf_raw > 0 else "безлимит"
    price = cfg.get("paid_price", 0)
    ip_str = str(ip) if ip > 0 else "безлимит"
    hwid_str = str(hwid) if hwid > 0 else "безлимит"

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🆕 <b>Запрос на подписку</b>\n\n"
            f'👤 <a href="tg://user?id={user.id}">{user.first_name}</a> ({uname})\n'
            f"🆔 TG ID: <code>{user.id}</code>\n\n"
            f"<b>Параметры подписки:</b>\n"
            f"🆓 Пробный период: <b>{fmt_duration(trial_sec)}</b>\n"
            f"💰 После оплаты: <b>{fmt_duration(pay_sec)}</b>\n"
            f"⏳ На продление: <b>{fmt_duration(renew_sec)}</b>\n"
            f"💵 Сумма: <b>{price} ₽</b>\n"
            f"🌐 Лимит IP: <b>{ip_str}</b>\n"
            f"🖥 Лимит HWID: <b>{hwid_str}</b>\n"
            f"📶 Трафик: <b>{traf_str}</b>\n\n"
            "Одобрить пробную подписку?"
        ),
        parse_mode="HTML",
        reply_markup=approve_keyboard(user.id),
    )

    await query.edit_message_text(
        "👤 <b>Моя подписка</b>\n\n"
        "📨 Ваш запрос отправлен администратору.\n"
        "Ожидайте одобрения — вам придёт уведомление.",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def _process_referral_bonus(invited_tg_id: int, context):
    """Начисляет бонус рефереру если у него активная подписка."""
    cfg = load_config()
    bonus_seconds = cfg.get("referral_bonus")
    if not bonus_seconds:
        return
    referrer_id = await get_referrer(invited_tg_id)
    if not referrer_id:
        return
    referrer_sub = await get_paid_sub_by_tg_id(referrer_id)
    if not referrer_sub:
        return
    ref_status = referrer_sub[11] if len(referrer_sub) > 11 else "active"
    if ref_status not in ("active", "renewal"):
        return

    ref_sub_id = referrer_sub[0]
    ref_email = referrer_sub[2]
    ref_expire = referrer_sub[6]

    for fmt_e in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            expire_dt = datetime.strptime(ref_expire, fmt_e)
            break
        except ValueError:
            continue
    else:
        expire_dt = datetime.now()
    if expire_dt < datetime.now():
        expire_dt = datetime.now()

    new_expire = expire_dt + timedelta(seconds=bonus_seconds)
    new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")

    full_row = await get_paid_sub(ref_sub_id)
    await update_paid_sub_field(ref_sub_id, "expire_date", new_expire_str)

    from xui_api import update_client_expire
    await update_client_expire(ref_email, new_expire_str)

    await mark_referral_rewarded(invited_tg_id, bonus_seconds)

    await add_history(
        referrer_id, "referral_bonus",
        f"За приглашение <code>{invited_tg_id}</code>\n"
        f"Начислено: {fmt_duration(bonus_seconds)}\nДо: {new_expire_str}",
    )

    bot = context.bot if hasattr(context, 'bot') else None
    if bot:
        await _notify_user(bot, referrer_id,
            f"🎉 <b>Реферальный бонус!</b>\n\n"
            f"Ваш друг активировал подписку.\n"
            f"➕ Вам начислено: <b>{fmt_duration(bonus_seconds)}</b>\n"
            f"📅 Подписка до: <b>{new_expire_str}</b>"
        )


async def handle_approve(query, tg_id: int, context):
    """Админ одобрил подписку — создаём пробный период."""
    existing = await get_paid_sub_by_tg_id(tg_id)
    if existing:
        await resolve_request(tg_id, "approved")
        await query.edit_message_text(
            f"⚠️ У пользователя <code>{tg_id}</code> уже есть подписка.",
            parse_mode="HTML",
        )
        return

    await resolve_request(tg_id, "approved")
    await add_history(tg_id, "trial_approved")

    async def _edit(txt, **kw):
        await query.edit_message_text(txt, **kw)

    await do_create_paid_sub(query, tg_id, context, _edit, trial=True)

    # Реферальный бонус
    await _process_referral_bonus(tg_id, context)


async def handle_reject(query, tg_id: int, context):
    """Админ отклонил запрос."""
    await resolve_request(tg_id, "rejected")
    await add_history(tg_id, "trial_rejected")
    await query.edit_message_text(
        f"❌ Запрос от <code>{tg_id}</code> отклонён.",
        parse_mode="HTML",
    )
    await _notify_user(context.bot, tg_id,
        "❌ Ваш запрос на подписку был <b>отклонён</b> администратором."
    )


# ── Просмотр подписки ─────────────────────────────────────────────────────────

def _fmt_bytes(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} КБ"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} МБ"
    return f"{b / 1024 ** 3:.2f} ГБ"


async def handle_paid_sub_view(query, sub_id: int):
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    # row: id(0),tg_id(1),email(2),uuid(3),sub_id(4),sub_url(5),expire(6),
    #      ip(7),hwid(8),traffic(9),created(10),status(11),payment_pending(12),
    #      ind_trial(13),ind_pay(14),ind_renew(15),ind_price(16),ind_pay_url(17)
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at = row[:11]
    status = row[11] if len(row) > 11 else "active"
    payment_pending = row[12] if len(row) > 12 else 0
    ind_trial = row[13] if len(row) > 13 else None
    ind_pay = row[14] if len(row) > 14 else None
    ind_renew = row[15] if len(row) > 15 else None
    ind_price = row[16] if len(row) > 16 else None
    ind_pay_url = row[17] if len(row) > 17 else None

    traffic_limit = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    from xui_api import get_client_traffic, get_client_info
    t = await get_client_traffic(email)
    if t["success"]:
        up = t.get("up", 0)
        down = t.get("down", 0)
        total_used = up + down
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b> — ⬆ {_fmt_bytes(up)} ⬇ {_fmt_bytes(down)} (всего {_fmt_bytes(total_used)})"
    else:
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b>"

    info = await get_client_info(email)
    enabled = info.get("enabled", True) if info.get("success") else True
    status_icon = "🟢" if enabled else "🔴"

    # Статус подписки
    status_labels = {"active": "активна", "renewal": "ожидает продления", "expired": "истекла"}
    status_label = status_labels.get(status, status)

    # Оплата ожидает
    payment_line = ""
    if payment_pending:
        payment_line = "💳 Оплата: <b>ожидает проверки</b>\n"

    # Количество продлений
    from paidsub.storage import get_paid_sub_by_tg_id
    tg_row = await get_paid_sub_by_tg_id(tg_id) if tg_id else None
    times_renewed = tg_row[12] if tg_row and len(tg_row) > 12 else 0
    sub_type = "оплаченная" if times_renewed > 0 else "пробная"

    # Юзер инфо
    from database import get_user_info
    user_info = await get_user_info(tg_id) if tg_id else None
    uname = user_info[2] if user_info and user_info[2] else None
    first_name = user_info[1] if user_info and user_info[1] else None

    if tg_id and uname:
        tg_line = f'👤 <a href="tg://user?id={tg_id}">{first_name or tg_id}</a> (@{uname})\n'
        link_line = f'⛓‍💥 <a href="https://t.me/{uname}">Написать</a>'
    elif tg_id:
        tg_line = f'👤 <a href="tg://user?id={tg_id}">{first_name or tg_id}</a>\n'
        link_line = f'⛓‍💥 <a href="tg://user?id={tg_id}">Написать</a>'
    else:
        tg_line = ""
        link_line = ""

    if tg_id:
        tg_line += f"🆔 TG ID: <code>{tg_id}</code>\n"

    # Мьют
    mute_line = ""
    if tg_id:
        muted_until = await get_muted_until(tg_id)
        if muted_until:
            muted_dt = None
            for fmt_m in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                try:
                    muted_dt = datetime.strptime(muted_until, fmt_m)
                    break
                except ValueError:
                    continue
            if muted_dt and datetime.now() < muted_dt:
                mute_line = f"🔇 Заглушен до: <b>{muted_until}</b>\n"

    # Индивидуальные настройки
    cfg = load_config()
    ind_lines = []
    if ind_trial:
        ind_lines.append(f"🆓 Пробный: <b>{fmt_duration(ind_trial)}</b>")
    if ind_pay:
        ind_lines.append(f"💰 Период оплаты: <b>{fmt_duration(ind_pay)}</b>")
    if ind_renew:
        ind_lines.append(f"⏳ На продление: <b>{fmt_duration(ind_renew)}</b>")
    if ind_price is not None:
        ind_lines.append(f"💵 Сумма: <b>{ind_price} ₽</b>")
    if ind_pay_url:
        ind_lines.append(f"🔗 Ссылка оплаты: <b>{ind_pay_url}</b>")
    ind_block = ""
    if ind_lines:
        ind_block = "\n<b>Инд. настройки:</b>\n" + "\n".join(ind_lines) + "\n"

    # Реферал
    referral_line = ""
    if tg_id:
        referrer_id = await get_referrer(tg_id)
        if referrer_id:
            ref_info = await get_user_info(referrer_id)
            ref_name = ref_info[1] if ref_info else str(referrer_id)
            referral_line = f"👥 Приглашён: <b>{ref_name}</b> (<code>{referrer_id}</code>)\n"

    # Оставшееся время
    time_left_line = ""
    for fmt_e in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            expire_dt = datetime.strptime(expire, fmt_e)
            break
        except ValueError:
            continue
    else:
        expire_dt = None
    if expire_dt:
        delta = expire_dt - datetime.now()
        if delta.total_seconds() > 0:
            time_left_line = f"⏱ Осталось: <b>{fmt_duration(int(delta.total_seconds()))}</b>\n"
        else:
            time_left_line = "⏱ Осталось: <b>истекла</b>\n"

    await query.edit_message_text(
        f"📄 <b>Подписка #{sub_id}</b> {status_icon}\n\n"
        + tg_line
        + f"📧 Email: <code>{email}</code>\n"
        f"🆔 UUID: <code>{uuid_val}</code>\n"
        f"📋 Sub ID: <code>{sub_id_str}</code>\n\n"
        f"📌 Статус: <b>{status_label}</b>\n"
        f"🏷 Тип: <b>{sub_type}</b> (продлений: {times_renewed})\n"
        + payment_line
        + f"📅 До: <b>{expire}</b>\n"
        + time_left_line
        + f"🌐 Лимит IP: <b>{limit_ip}</b>\n"
        f"🖥 Лимит HWID: <b>{limit_hwid}</b>\n"
        f"{traffic_line}\n"
        f"🕐 Создано: {created_at}\n"
        + mute_line
        + referral_line
        + ind_block
        + (f"\n{link_line}\n" if link_line else "")
        + f"\n🔗 Ссылка:\n<code>{sub_url}</code>",
        parse_mode="HTML",
        reply_markup=paid_sub_view_keyboard(sub_id, enabled),
        disable_web_page_preview=True,
    )


# ── Вкл/Выкл ─────────────────────────────────────────────────────────────────

async def handle_paid_sub_toggle(query, sub_id: int, context=None):
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    tg_id = row[1]
    email = row[2]
    from xui_api import get_client_info, toggle_client
    info = await get_client_info(email)
    if not info.get("success"):
        await query.answer("❌ Клиент не найден в панели", show_alert=True)
        return
    new_state = not info.get("enabled", True)
    await query.edit_message_text("⏳ Обновляю статус...")
    result = await toggle_client(email, new_state)
    if not result["success"]:
        await query.edit_message_text(
            f"❌ Ошибка: <code>{result['error']}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if context and tg_id:
        status_text = "✅ включена" if new_state else "⏸ приостановлена"
        await _notify_user(context.bot, tg_id, f"ℹ️ Ваша подписка <b>{status_text}</b>.")

    await add_history(
        tg_id, "sub_enabled" if new_state else "sub_disabled",
        f"Подписка #{sub_id} ({email})",
    )

    await handle_paid_sub_view(query, sub_id)


# ── Удаление ──────────────────────────────────────────────────────────────────

async def handle_paid_sub_delete(query, sub_id: int, context=None):
    row = await get_paid_sub(sub_id)
    tg_id = row[1] if row else None
    email = row[2] if row else None

    if email:
        from xui_api import delete_client
        await query.edit_message_text("⏳ Удаляю из панели...")
        panel_result = await delete_client(email)
        panel_status = "✅ удалена из панели" if panel_result["success"] else f"⚠️ панель: {panel_result.get('error', '?')}"
    else:
        panel_status = "⚠️ email не найден, из панели не удалено"

    await delete_paid_sub(sub_id)

    if tg_id:
        await add_history(tg_id, "sub_deleted", f"Подписка #{sub_id} ({email}) · {panel_status}")

    if context and tg_id:
        await _notify_user(context.bot, tg_id, "🗑 Ваша подписка была <b>удалена</b>.")

    await query.edit_message_text(
        f"🗑 Подписка удалена из базы.\n{panel_status}",
        reply_markup=back_admin(),
    )


# ── Заморозка ─────────────────────────────────────────────────────────────────

async def handle_paid_sub_freeze(query, sub_id: int, context=None):
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    tg_id = row[1]
    email = row[2]
    from xui_api import get_client_info, toggle_client
    info = await get_client_info(email)
    enabled = info.get("enabled", True) if info.get("success") else True
    if not enabled:
        await query.answer("Подписка уже заморожена", show_alert=True)
        return
    await query.edit_message_text("🧊 Замораживаю подписку...")
    result = await toggle_client(email, False)
    if not result["success"]:
        await query.edit_message_text(
            f"❌ Ошибка: <code>{result['error']}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if context and tg_id:
        await _notify_user(context.bot, tg_id,
            "🧊 Ваша подписка <b>заморожена</b>. Время действия приостановлено."
        )

    await add_history(tg_id, "sub_frozen", f"Подписка #{sub_id} ({email})")

    await handle_paid_sub_view(query, sub_id)


# ── Продление срока ──────────────────────────────────────────────────────────

async def handle_paid_sub_extend(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EXTEND
    context.user_data["state"] = AWAITING_PAID_SUB_EXTEND
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"➕ <b>Добавить срок к подписке #{sub_id}</b>\n\n"
        "Введи время в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_sub_reduce(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_REDUCE
    context.user_data["state"] = AWAITING_PAID_SUB_REDUCE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"➖ <b>Убавить срок у подписки #{sub_id}</b>\n\n"
        "Введи время в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Массовые действия ─────────────────────────────────────────────────────────

async def handle_paid_bulk_menu(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM paid_subs") as cur:
            total = (await cur.fetchone())[0]
    await query.edit_message_text(
        "⚡ <b>Массовые действия</b>\n\n"
        f"Всего платных подписок: <b>{total}</b>\n\n"
        "Выбери действие — оно применится ко <b>всем</b> платным подпискам сразу:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить срок всем", callback_data="paid_bulk_extend")],
            [InlineKeyboardButton("➖ Убавить срок всем", callback_data="paid_bulk_reduce")],
            [InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")],
        ]),
    )


async def handle_paid_bulk_extend(query, context):
    from states import AWAITING_PAID_BULK_EXTEND
    context.user_data["state"] = AWAITING_PAID_BULK_EXTEND
    await query.edit_message_text(
        "➕ <b>Добавить срок всем подпискам</b>\n\n"
        "Введи время в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_bulk_reduce(query, context):
    from states import AWAITING_PAID_BULK_REDUCE
    context.user_data["state"] = AWAITING_PAID_BULK_REDUCE
    await query.edit_message_text(
        "➖ <b>Убавить срок всем подпискам</b>\n\n"
        "Введи время в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def bulk_shift_expire(seconds: int, direction: int, context) -> dict:
    """Сдвигает дату окончания у всех платных подписок.
    direction = +1 (добавить) или -1 (убавить). Возвращает отчёт."""
    from xui_api import update_client_expire, get_client_info, toggle_client, move_client_inbound
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM paid_subs") as cur:
            all_ids = [r[0] for r in await cur.fetchall()]

    cfg = load_config()
    create_inbound_ids = cfg.get("paid_preset_inbound_ids") or []
    updated = 0
    errors = 0

    for sid in all_ids:
        row = await get_paid_sub(sid)
        if not row:
            continue
        email = row[2]
        tg_id = row[1]
        expire_str = row[6]
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                expire_dt = datetime.strptime(expire_str, fmt)
                break
            except ValueError:
                continue
        else:
            expire_dt = datetime.now()

        if direction > 0:
            base = expire_dt if expire_dt > datetime.now() else datetime.now()
            new_expire = base + timedelta(seconds=seconds)
        else:
            new_expire = expire_dt - timedelta(seconds=seconds)

        new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")
        try:
            await update_paid_sub_field(sid, "expire_date", new_expire_str)
            await update_client_expire(email, new_expire_str)
            if direction > 0:
                # при добавлении — активируем и возвращаем инбаунды
                await update_paid_sub_field(sid, "status", "active")
                info = await get_client_info(email)
                if info.get("success") and not info.get("enabled", True):
                    await toggle_client(email, True)
                if create_inbound_ids:
                    await move_client_inbound(email, create_inbound_ids)
            updated += 1

            # уведомление пользователю
            if tg_id:
                bot = context.bot if hasattr(context, 'bot') else None
                if bot:
                    if direction > 0:
                        await _notify_user(bot, tg_id,
                            f"🎉 <b>Ваша подписка продлена!</b>\n\n"
                            f"➕ Добавлено: <b>{fmt_duration(seconds)}</b>\n"
                            f"📅 Действует до: <b>{new_expire_str}</b>"
                        )
                    else:
                        await _notify_user(bot, tg_id,
                            f"ℹ️ <b>Срок вашей подписки изменён.</b>\n\n"
                            f"➖ Убавлено: <b>{fmt_duration(seconds)}</b>\n"
                            f"📅 Действует до: <b>{new_expire_str}</b>"
                        )
                # запись в историю
                await add_history(
                    tg_id, "bulk_extended" if direction > 0 else "bulk_reduced",
                    f"Подписка #{sid} ({email})\n"
                    f"{'Добавлено' if direction > 0 else 'Убавлено'}: {fmt_duration(seconds)}\n"
                    f"Новая дата: {new_expire_str}",
                )
        except Exception:
            errors += 1

    return {"updated": updated, "errors": errors, "total": len(all_ids)}


# ── Индивидуальные настройки платной подписки ─────────────────────────────────

async def handle_paid_sub_settings(query, sub_id: int):
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    # row: id,tg_id,email,uuid,sub_id,sub_url,expire,ip,hwid,traffic,created,status,payment_pending,
    #       ind_trial,ind_pay_period,ind_renew,ind_price,ind_pay_url
    expire = row[6]
    limit_ip = row[7]
    limit_hwid = row[8]
    total_gb = row[9]
    ind_trial = row[13] if len(row) > 13 else None
    ind_pay = row[14] if len(row) > 14 else None
    ind_renew = row[15] if len(row) > 15 else None
    ind_price = row[16] if len(row) > 16 else None
    ind_pay_url = row[17] if len(row) > 17 else None

    traffic = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"
    ip_str = str(limit_ip) if limit_ip > 0 else "безлимит"
    hwid_str = str(limit_hwid) if limit_hwid > 0 else "безлимит"

    trial_str = fmt_duration(ind_trial) if ind_trial else "общие"
    pay_str = fmt_duration(ind_pay) if ind_pay else "общие"
    renew_str = fmt_duration(ind_renew) if ind_renew else "общие"
    price_str = f"{ind_price} ₽" if ind_price is not None else "общие"
    pay_url_str = ind_pay_url if ind_pay_url else "общие"

    await query.edit_message_text(
        f"⚙️ <b>Настройки подписки #{sub_id}</b>\n\n"
        f"📅 Дата окончания: <b>{expire}</b>\n"
        f"🌐 Лимит IP: <b>{ip_str}</b>\n"
        f"🖥 Лимит HWID: <b>{hwid_str}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n"
        f"🆓 Пробный период: <b>{trial_str}</b>\n"
        f"💰 Период оплаты: <b>{pay_str}</b>\n"
        f"⏳ На продление: <b>{renew_str}</b>\n"
        f"💵 Сумма: <b>{price_str}</b>\n"
        f"🔗 Ссылка на оплату: <b>{pay_url_str}</b>\n\n"
        "Выбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=paid_sub_settings_keyboard(sub_id),
    )


async def handle_paid_sub_edit_expire(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_EXPIRE
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_EXPIRE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📅 <b>Дата окончания подписки #{sub_id}</b>\n\n"
        "Введи новую дату:\n"
        "<code>дд.мм.гггг</code>, <code>дд.мм.гггг чч:мм</code> или <code>дд.мм.гггг чч:мм:сс</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_ip(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_IP
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_IP
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🌐 <b>Лимит IP подписки #{sub_id}</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_hwid(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_HWID
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_HWID
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🖥 <b>Лимит HWID подписки #{sub_id}</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_traffic(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_TRAFFIC
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_TRAFFIC
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📶 <b>Трафик подписки #{sub_id}</b>\n\nВведи число ГБ или <code>-</code> для безлимита:",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_trial(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_TRIAL
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_TRIAL
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🆓 <b>Пробный период подписки #{sub_id}</b>\n\n{_TIME_HINT}",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_pay_period(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_PAY_PERIOD
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_PAY_PERIOD
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"💰 <b>Период оплаты подписки #{sub_id}</b>\n\n{_TIME_HINT}",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_renew_time(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_RENEW_TIME
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_RENEW_TIME
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"⏳ <b>Время на продление подписки #{sub_id}</b>\n\n{_TIME_HINT}",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_price(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_PRICE
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_PRICE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"💵 <b>Сумма подписки #{sub_id}</b>\n\nВведи сумму в рублях (число):",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_pay_url(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_PAY_URL
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_PAY_URL
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🔗 <b>Ссылка на оплату подписки #{sub_id}</b>\n\nВведи URL:",
        parse_mode="HTML", reply_markup=back_admin(),
    )


# ── Job: проверка истечения подписок ──────────────────────────────────────────

async def check_expired_subs(context):
    """Проверяет подписки: уведомляет при смене статуса, отключает и меняет инбаунды."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cfg = load_config()
    global_renew_seconds = cfg.get("paid_renew_time", 86400)
    expire_inbound_ids = cfg.get("paid_expire_inbound_ids") or []

    subs = await get_expired_paid_subs()
    now = datetime.now()

    for row in subs:
        sub_id, tg_id, email, uuid_val, sub_id_str, sub_url, expire_str, status, times_renewed, ind_renew_time = row
        renew_seconds = ind_renew_time if ind_renew_time else global_renew_seconds
        try:
            for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                try:
                    expire_dt = datetime.strptime(expire_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                continue
        except Exception:
            continue

        # expire_date = creation + period + renew_time
        # main_period_end = expire_date - renew_time (конец пробного/оплаченного)
        # expire_date = конец времени на оплату
        main_period_end = expire_dt - timedelta(seconds=renew_seconds)

        if now < main_period_end:
            # Основной период ещё идёт — статус active
            if status != "active":
                await update_paid_sub_field(sub_id, "status", "active")
            continue

        if now < expire_dt:
            # Основной период кончился, идёт время на оплату
            if status == "active":
                # Переход active → renewal: одноразовое уведомление
                await update_paid_sub_field(sub_id, "status", "renewal")
                if tg_id:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")]
                    ])
                    try:
                        if times_renewed > 0:
                            period_text = "Подписка истекла"
                        else:
                            period_text = "Пробный период окончился"
                        await context.bot.send_message(
                            chat_id=tg_id,
                            text=(
                                f"⚠️ <b>{period_text}!</b>\n\n"
                                f"У вас есть <b>{fmt_duration(renew_seconds)}</b> на продление.\n"
                                f"Продлите подписку, чтобы не потерять доступ."
                            ),
                            parse_mode="HTML",
                            reply_markup=kb,
                        )
                    except Exception:
                        pass
        else:
            # Время на оплату вышло
            if status != "expired":
                # Переход → expired: одноразовое уведомление + отключение + смена инбаунда
                await update_paid_sub_field(sub_id, "status", "expired")

                from xui_api import get_client_info, toggle_client
                info = await get_client_info(email)
                enabled = info.get("enabled", True) if info.get("success") else False
                if enabled:
                    await toggle_client(email, False)

                if tg_id:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")]
                    ])
                    try:
                        await context.bot.send_message(
                            chat_id=tg_id,
                            text=(
                                "🔴 Ваша подписка <b>отключена</b>.\n"
                                "Время на продление истекло.\n\n"
                                "Нажмите кнопку ниже, чтобы продлить подписку."
                            ),
                            parse_mode="HTML",
                            reply_markup=kb,
                        )
                    except Exception:
                        pass

                if expire_inbound_ids:
                    from xui_api import move_client_inbound
                    await move_client_inbound(email, expire_inbound_ids)


async def handle_confirm_payment(query, tg_id: int, context):
    """Админ подтвердил оплату — продлеваем подписку на оплаченный период."""
    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        await query.edit_message_text(
            f"❌ Подписка для <code>{tg_id}</code> не найдена.",
            parse_mode="HTML",
        )
        return

    sub_id = row[0]
    email = row[2]
    expire_str = row[6]

    full_row = await get_paid_sub(sub_id)
    cfg = load_config()
    ind_pay = full_row[14] if full_row and full_row[14] else None
    ind_renew = full_row[15] if full_row and full_row[15] else None
    pay_seconds = ind_pay if ind_pay else cfg.get("paid_pay_period", 2592000)
    renew_seconds = ind_renew if ind_renew else cfg.get("paid_renew_time", 86400)
    total_seconds = pay_seconds + renew_seconds

    new_expire = datetime.now() + timedelta(seconds=total_seconds)
    new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")

    await update_paid_sub_field(sub_id, "expire_date", new_expire_str)
    await update_paid_sub_field(sub_id, "status", "active")
    await update_paid_sub_field(sub_id, "payment_pending", 0)
    cur_renewed = row[12] if len(row) > 12 else 0
    await update_paid_sub_field(sub_id, "times_renewed", cur_renewed + 1)

    from xui_api import get_client_info, toggle_client, update_client_expire
    info = await get_client_info(email)
    if info.get("success") and not info.get("enabled", True):
        await toggle_client(email, True)

    # Обновляем expire в панели 3x-UI
    await update_client_expire(email, new_expire_str)

    # Возвращаем на основные инбаунды если были переключены
    create_inbound_ids = cfg.get("paid_preset_inbound_ids") or []
    if create_inbound_ids:
        from xui_api import move_client_inbound
        await move_client_inbound(email, create_inbound_ids)

    await add_history(tg_id, "payment_confirmed")

    await query.edit_message_text(
        f"✅ Оплата подтверждена для <code>{tg_id}</code>!\n\n"
        f"📅 Новая дата: <b>{new_expire_str}</b>",
        parse_mode="HTML",
    )

    await _notify_user(context.bot, tg_id,
        f"🎉 <b>Оплата подтверждена!</b>\n\n"
        f"Ваша подписка продлена до <b>{new_expire_str}</b>.\n"
        "Спасибо за использование Drebol VPN!"
    )


async def handle_reject_payment(query, tg_id: int, context):
    """Админ отклонил заявку на оплату."""
    await add_history(tg_id, "payment_rejected")
    row = await get_paid_sub_by_tg_id(tg_id)
    if row:
        await update_paid_sub_field(row[0], "payment_pending", 0)
    await query.edit_message_text(
        f"❌ Заявка на оплату от <code>{tg_id}</code> отклонена.",
        parse_mode="HTML",
    )
    await _notify_user(context.bot, tg_id,
        "❌ Ваша заявка на оплату <b>отклонена</b> администратором.\n"
        "Если вы считаете это ошибкой, обратитесь в поддержку."
    )


# ── Запросы ──────────────────────────────────────────────────────────────────

async def handle_paid_requests(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import get_user_info
    trial_rows = await list_pending_requests()
    payment_rows = await list_pending_payments()

    if not trial_rows and not payment_rows:
        await query.edit_message_text(
            "📬 <b>Запросы</b>\n\nНет ожидающих запросов.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")]
            ]),
        )
        return

    kb = []
    lines = []

    if trial_rows:
        lines.append("<b>🆓 Запросы на пробный период:</b>\n")
        for tg_id, created_at in trial_rows:
            user_info = await get_user_info(tg_id)
            name = user_info[1] if user_info else str(tg_id)
            uname = f"@{user_info[2]}" if user_info and user_info[2] else f"id{tg_id}"
            ts = created_at[:16] if created_at else "?"
            lines.append(f"👤 {name} ({uname}) · <code>{ts}</code>")
            kb.append([
                InlineKeyboardButton(f"✅ {tg_id}", callback_data=f"paid_approve:{tg_id}"),
                InlineKeyboardButton(f"❌ {tg_id}", callback_data=f"paid_reject:{tg_id}"),
                InlineKeyboardButton(f"🔇", callback_data=f"paid_mute_user:{tg_id}"),
            ])
        lines.append("")

    if payment_rows:
        lines.append("<b>💰 Запросы на проверку оплаты:</b>\n")
        for tg_id, email, expire in payment_rows:
            user_info = await get_user_info(tg_id)
            name = user_info[1] if user_info else str(tg_id)
            uname = f"@{user_info[2]}" if user_info and user_info[2] else f"id{tg_id}"
            lines.append(f"👤 {name} ({uname}) · до {expire}")
            kb.append([
                InlineKeyboardButton(f"✅ {tg_id}", callback_data=f"confirm_payment:{tg_id}"),
                InlineKeyboardButton(f"❌ {tg_id}", callback_data=f"reject_payment:{tg_id}"),
                InlineKeyboardButton(f"🔇", callback_data=f"paid_mute_user:{tg_id}"),
            ])

    kb.append([InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")])

    await query.edit_message_text(
        "📬 <b>Запросы</b>\n\n" + "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ── История ──────────────────────────────────────────────────────────────────

_ACTION_LABELS = {
    "trial_approved": "✅ Пробный одобрен",
    "trial_rejected": "❌ Пробный отклонён",
    "payment_confirmed": "✅ Оплата подтверждена",
    "payment_rejected": "❌ Оплата отклонена",
    "sub_created": "🆕 Подписка создана",
    "sub_extended": "➕ Срок добавлен",
    "sub_reduced": "➖ Срок убавлен",
    "sub_frozen": "🧊 Заморожена",
    "sub_enabled": "▶️ Включена",
    "sub_disabled": "⏸ Отключена",
    "sub_deleted": "🗑 Удалена",
    "bulk_extended": "⚡➕ Массово: срок добавлен",
    "bulk_reduced": "⚡➖ Массово: срок убавлен",
    "settings_changed": "⚙️ Изменены настройки",
    "referral_bonus": "🎁 Реферальный бонус",
    "user_muted": "🔇 Заглушён",
    "user_unmuted": "🔊 Разглушён",
}


async def handle_paid_history(query, page: int = 1):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows, total_pages = await list_history(page)
    if not rows:
        await query.edit_message_text(
            "📜 <b>История</b>\n\nПока нет записей.",
            parse_mode="HTML",
            reply_markup=paid_history_keyboard(1, 1),
        )
        return
    kb = []
    for entry_id, tg_id, action, details, created_at in rows:
        label = _ACTION_LABELS.get(action, action)
        ts = created_at[5:16] if created_at else "?"  # MM-DD HH:MM
        kb.append([InlineKeyboardButton(
            f"{label} · {tg_id} · {ts}",
            callback_data=f"paid_history_view:{entry_id}",
        )])
    # навигация
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"paid_history_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"paid_history_page:{page + 1}"))
    if total_pages > 1:
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")])

    await query.edit_message_text(
        f"📜 <b>История действий</b>\n\n"
        f"Всего показано: стр. {page}/{total_pages}\n"
        "Нажми на запись, чтобы посмотреть детали 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_paid_history_view(query, entry_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import get_user_info
    entry = await get_history_entry(entry_id)
    if not entry:
        await query.answer("Запись не найдена", show_alert=True)
        return
    _, tg_id, action, details, created_at = entry
    label = _ACTION_LABELS.get(action, action)

    user_info = await get_user_info(tg_id) if tg_id else None
    name = user_info[1] if user_info else str(tg_id)
    uname = f"@{user_info[2]}" if user_info and user_info[2] else f"id{tg_id}"

    text = (
        f"📋 <b>Детали действия</b>\n\n"
        f"🎬 Действие: <b>{label}</b>\n"
        f"👤 Пользователь: <b>{name}</b> ({uname})\n"
        f"🆔 TG ID: <code>{tg_id}</code>\n"
        f"🕐 Время: <b>{created_at}</b>\n"
    )
    if details:
        text += f"\n📝 Подробности:\n{details}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ К истории", callback_data="paid_history")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


# ── Мьют / Размьют ──────────────────────────────────────────────────────────

async def handle_mute_user(query, tg_id: int, context):
    from states import AWAITING_PAID_MUTE_USER
    context.user_data["state"] = AWAITING_PAID_MUTE_USER
    context.user_data["mute_tg_id"] = tg_id
    await query.edit_message_text(
        f"🔇 <b>Заглушить пользователя {tg_id}</b>\n\n"
        "Введи время блокировки запросов:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_unmute_user(query, tg_id: int):
    await clear_mute(tg_id)
    await add_history(tg_id, "user_unmuted", "Снята блокировка запросов")
    await query.answer(f"🔊 Пользователь {tg_id} разглушён", show_alert=True)
    await handle_muted_list(query)


async def handle_muted_list(query):
    from datetime import datetime as dt
    rows = await list_muted()
    active = [(tg_id, mu) for tg_id, mu in rows if _is_mute_active(mu)]
    if not active:
        await query.edit_message_text(
            "🔇 <b>Заглушённые</b>\n\nНет заглушённых пользователей.",
            parse_mode="HTML",
            reply_markup=muted_list_keyboard([]),
        )
        return
    await query.edit_message_text(
        "🔇 <b>Заглушённые</b>\n\n"
        "Нажми на пользователя, чтобы разглушить:",
        parse_mode="HTML",
        reply_markup=muted_list_keyboard(active),
    )


def _is_mute_active(muted_until: str) -> bool:
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.now() < datetime.strptime(muted_until, fmt)
        except ValueError:
            continue
    return False


# ── Авто-обновление ников ────────────────────────────────────────────────────

async def handle_paid_auto_update_settings(query):
    cfg = load_config()
    enabled = cfg.get("paid_auto_update_usernames", False)
    days = cfg.get("paid_auto_update_days", 2)
    last_run = cfg.get("paid_auto_update_last_run")
    last_line = f"\n🕐 Последний запуск: {last_run}" if last_run else ""
    from paidsub.keyboards import paid_auto_update_keyboard
    await query.edit_message_text(
        "⏰ <b>Авто-обновление ников (платные)</b>\n\n"
        "Бот проверяет, изменился ли юзернейм у пользователей с платными подписками, "
        "и обновляет email в панели.\n"
        + last_line,
        parse_mode="HTML",
        reply_markup=paid_auto_update_keyboard(enabled, days),
    )


async def handle_paid_toggle_auto_update(query):
    cfg = load_config()
    cfg["paid_auto_update_usernames"] = not cfg.get("paid_auto_update_usernames", False)
    save_config(cfg)
    await handle_paid_auto_update_settings(query)


async def handle_paid_set_auto_update_days(query, context):
    from states import AWAITING_PAID_AUTO_UPDATE_DAYS
    context.user_data["state"] = AWAITING_PAID_AUTO_UPDATE_DAYS
    cfg = load_config()
    current = cfg.get("paid_auto_update_days", 2)
    await query.edit_message_text(
        f"📝 <b>Интервал проверки (платные)</b>\n\n"
        f"Сейчас: <b>{current} дн.</b>\n\n"
        "Введи новое значение (целое число дней, минимум 1):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_run_sync_now(query):
    await query.edit_message_text("⏳ Запускаю синхронизацию ников...")
    result = await paid_sync_usernames()
    lines = [f"🔄 <b>Синхронизация завершена</b>\n"]
    lines.append(f"📊 Всего подписок с TG ID: <b>{result['total']}</b>")
    lines.append(f"🔍 Нужно обновить: <b>{result['need_update']}</b>")
    lines.append(f"✅ Успешно обновлено: <b>{result['updated']}</b>")
    if result["errors"]:
        lines.append(f"❌ Ошибки: <b>{len(result['errors'])}</b>")
        for err in result["errors"][:5]:
            lines.append(f"  • <code>{err}</code>")
    if result["skipped"]:
        lines.append(f"⏭ Юзер не в базе: <b>{result['skipped']}</b>")
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def paid_sync_usernames(context=None) -> dict:
    from xui_api import update_client_email, build_email
    from database import get_user_info
    from paidsub.storage import get_all_paid_subs_with_tg, update_paid_sub_email

    subs = await get_all_paid_subs_with_tg()
    updated = 0
    need_update = 0
    skipped = 0
    errors = []

    for row in subs:
        sub_id, tg_id, old_email, uuid_val, sub_id_str, expire_date, limit_ip, limit_hwid, total_gb = row
        user_row = await get_user_info(tg_id)
        if not user_row:
            skipped += 1
            continue
        username = user_row[2]
        new_email = build_email(tg_id, username, prefix="paid_")
        if new_email == old_email:
            continue
        need_update += 1
        result = await update_client_email(
            old_email=old_email,
            new_email=new_email,
            client_uuid=uuid_val,
            sub_id=sub_id_str,
            expire_date=expire_date,
            limit_ip=limit_ip,
            limit_hwid=limit_hwid,
            total_gb=total_gb,
        )
        if result["success"]:
            await update_paid_sub_email(sub_id, new_email)
            updated += 1
        else:
            errors.append(f"{old_email} → {new_email}: {result['error'][:100]}")

    cfg = load_config()
    cfg["paid_auto_update_last_run"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    save_config(cfg)
    if updated:
        print(f"[paid_sync_usernames] обновлено {updated} email(ов)")
    return {"total": len(subs), "need_update": need_update, "updated": updated, "skipped": skipped, "errors": errors}


# ── Реферальная система (админ) ──────────────────────────────────────────────

async def handle_referral_settings(query):
    cfg = load_config()
    bonus = cfg.get("referral_bonus")
    bonus_str = fmt_duration(bonus) if bonus else "не задан"
    stats = await get_all_referral_stats()

    from database import get_user_info
    top_lines = []
    for ref_id, cnt in stats["top_referrers"]:
        u = await get_user_info(ref_id)
        name = u[1] if u else str(ref_id)
        uname = f"@{u[2]}" if u and u[2] else f"id{ref_id}"
        top_lines.append(f"  {name} ({uname}) — <b>{cnt}</b>")

    lines = [
        "👥 <b>Реферальная система</b>\n",
        f"🎁 Бонус за реферала: <b>{bonus_str}</b>",
        f"👤 Всего рефералов: <b>{stats['total']}</b>",
        f"✅ С бонусом: <b>{stats['rewarded']}</b>",
    ]
    if stats['total_bonus'] > 0:
        lines.append(f"⏱ Всего начислено: <b>{fmt_duration(stats['total_bonus'])}</b>")
    if top_lines:
        lines.append("\n<b>Топ пригласивших:</b>")
        lines.extend(top_lines)

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Изменить бонус", callback_data="set_referral_bonus")],
        [InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")],
    ])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb,
    )


async def handle_set_referral_bonus(query, context):
    from states import AWAITING_REFERRAL_BONUS
    context.user_data["state"] = AWAITING_REFERRAL_BONUS
    cfg = load_config()
    bonus = cfg.get("referral_bonus")
    cur_str = fmt_duration(bonus) if bonus else "не задан"
    await query.edit_message_text(
        f"🎁 <b>Бонус за реферала</b>\n\n"
        f"Сейчас: <b>{cur_str}</b>\n\n"
        "Введи время бонуса:\n"
        "<code>1 день</code>, <code>3 дня</code>, <code>12 часов</code>, <code>1 неделя</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


def save_paid_preset(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
