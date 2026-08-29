from datetime import datetime, timedelta

from telegram import Bot
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config
from keyboards import back_admin, back_main

from paidsub.storage import (
    list_paid_subs, add_paid_sub, get_paid_sub, delete_paid_sub, get_paid_sub_by_tg_id,
    add_request, get_pending_request, resolve_request,
)
from paidsub.keyboards import (
    paid_subs_list_keyboard, paid_presets_keyboard, paid_sub_view_keyboard,
    paid_inbounds_keyboard, approve_keyboard,
)
from paidsub.time_parser import fmt_duration


async def _notify_user(bot: Bot, tg_id: int | None, text: str):
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


def _fmt_presets(cfg: dict, inbound_names: dict | None = None) -> str:
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
    email = build_email(tg_id, username)

    if trial:
        seconds = cfg.get("paid_trial_period", 86400)
    else:
        seconds = cfg.get("paid_pay_period", 2592000)

    expire_dt = datetime.now() + timedelta(seconds=seconds)
    expire_date = expire_dt.strftime("%d.%m.%Y")

    result = await create_client(
        expire_date=expire_date,
        limit_ip=int(cfg.get("paid_preset_ip", 0)),
        limit_hwid=int(cfg.get("paid_preset_hwid", 0)),
        total_gb=int(cfg.get("paid_preset_traffic", 0)),
        email=email,
    )

    if not result["success"]:
        await reply_func(
            f"❌ <b>Ошибка создания подписки</b>\n\n<code>{result['error']}</code>",
            parse_mode="HTML",
        )
        return

    await add_paid_sub(
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

    traffic_str = f"{cfg.get('paid_preset_traffic', 0)} ГБ" if int(cfg.get("paid_preset_traffic", 0)) > 0 else "безлимит"
    period_label = "пробный период" if trial else "оплаченный период"

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
            "Скопируй ссылку и вставь в приложение (Happ, v2rayNG и др.)"
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

    async def _edit(txt, **kw):
        await query.edit_message_text(txt, **kw)

    await do_create_paid_sub(query, tg_id, context, _edit, trial=True)


async def handle_reject(query, tg_id: int, context):
    """Админ отклонил запрос."""
    await resolve_request(tg_id, "rejected")
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
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at = row
    traffic_limit = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    from xui_api import get_client_traffic, get_client_info
    t = await get_client_traffic(email)
    if t["success"]:
        up = t.get("up", 0)
        down = t.get("down", 0)
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b> — ⬆ {_fmt_bytes(up)} ⬇ {_fmt_bytes(down)}"
    else:
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b>"

    info = await get_client_info(email)
    enabled = info.get("enabled", True) if info.get("success") else True
    status_icon = "🟢" if enabled else "🔴"

    tg_line = f'👤 TG: <a href="tg://user?id={tg_id}">{tg_id}</a>\n' if tg_id else ""
    from database import get_user_info
    user_info = await get_user_info(tg_id) if tg_id else None
    uname = user_info[2] if user_info and user_info[2] else None
    if tg_id and uname:
        link_line = f'⛓‍💥 <a href="https://t.me/{uname}">Написать</a>'
    elif tg_id:
        link_line = f'⛓‍💥 <a href="tg://user?id={tg_id}">Написать</a>'
    else:
        link_line = ""

    await query.edit_message_text(
        f"📄 <b>Подписка #{sub_id}</b> {status_icon}\n\n"
        + tg_line +
        f"📧 Email: <code>{email}</code>\n"
        f"🆔 UUID: <code>{uuid_val}</code>\n"
        f"📅 До: <b>{expire}</b>\n"
        f"🌐 Лимит IP: <b>{limit_ip}</b>\n"
        f"🖥 Лимит HWID: <b>{limit_hwid}</b>\n"
        f"{traffic_line}\n"
        f"🕐 Создано: {created_at}\n"
        + (f"\n{link_line}\n" if link_line else "") +
        f"\n🔗 Ссылка:\n<code>{sub_url}</code>",
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

    if context and tg_id:
        await _notify_user(context.bot, tg_id, "🗑 Ваша подписка была <b>удалена</b>.")

    await query.edit_message_text(
        f"🗑 Подписка удалена из базы.\n{panel_status}",
        reply_markup=back_admin(),
    )


def save_paid_preset(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
