from telegram import Bot
from telegram.ext import ContextTypes

from config import load_config, save_config
from keyboards import back_admin

from paidsub.storage import list_paid_subs, add_paid_sub, get_paid_sub, delete_paid_sub
from paidsub.keyboards import paid_subs_list_keyboard, paid_presets_keyboard, paid_sub_view_keyboard, paid_inbounds_keyboard


async def _notify_user(bot: Bot, tg_id: int | None, text: str):
    if not tg_id:
        return
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML")
    except Exception:
        pass


def _paid_presets_ready(cfg: dict) -> bool:
    return all(cfg.get(k) is not None for k in ("paid_preset_expire", "paid_preset_ip", "paid_preset_hwid", "paid_preset_traffic"))


def _fmt_presets(cfg: dict, inbound_names: dict | None = None) -> str:
    exp = cfg.get("paid_preset_expire", "не задан")
    ip = cfg.get("paid_preset_ip", "не задан")
    hwid = cfg.get("paid_preset_hwid", "не задан")
    traf_raw = cfg.get("paid_preset_traffic")
    if traf_raw is None:
        traf = "не задан"
    elif traf_raw == 0:
        traf = "безлимит"
    else:
        traf = f"{traf_raw} ГБ"
    inbound_ids = cfg.get("paid_preset_inbound_ids") or []
    if inbound_ids and inbound_names:
        names = [inbound_names.get(i, f"#{i}") for i in inbound_ids]
        inb_label = ", ".join(names)
    elif inbound_ids:
        inb_label = ", ".join(str(i) for i in inbound_ids)
    else:
        inb_label = "авто (первый VLESS)"
    return (
        f"📅 Дата окончания: <b>{exp}</b>\n"
        f"🌐 Лимит IP: <b>{ip}</b>\n"
        f"🖥 Лимит HWID: <b>{hwid}</b>\n"
        f"📶 Трафик: <b>{traf}</b>\n"
        f"📡 Инбаунды: <b>{inb_label}</b>"
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
    inbound_ids = cfg.get("paid_preset_inbound_ids") or []
    if inbound_ids:
        from xui_api import get_inbounds
        result = await get_inbounds()
        if result["success"]:
            for inb in result["inbounds"]:
                name = inb.get("tag") or inb.get("remark") or f"#{inb.get('id')}"
                inbound_names[inb.get("id")] = name
    await query.edit_message_text(
        "⚙️ <b>Настройки платной подписки</b>\n\n"
        + _fmt_presets(cfg, inbound_names)
        + "\n\nВыбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=paid_presets_keyboard(),
    )


async def handle_paid_preset_expire(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PAID_PRESET_EXPIRE
    context.user_data["state"] = AWAITING_PAID_PRESET_EXPIRE
    await query.edit_message_text(
        "📅 <b>Дата окончания</b>\n\nВведи в формате <code>дд.мм.гггг</code>:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_ip(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PAID_PRESET_IP
    context.user_data["state"] = AWAITING_PAID_PRESET_IP
    await query.edit_message_text(
        "🌐 <b>Лимит IP</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_hwid(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PAID_PRESET_HWID
    context.user_data["state"] = AWAITING_PAID_PRESET_HWID
    await query.edit_message_text(
        "🖥 <b>Лимит HWID</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_traffic(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PAID_PRESET_TRAFFIC
    context.user_data["state"] = AWAITING_PAID_PRESET_TRAFFIC
    await query.edit_message_text(
        "📶 <b>Трафик (ГБ)</b>\n\nВведи число в ГБ или <code>-</code> для безлимита:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Инбаунды ──────────────────────────────────────────────────────────────────

async def handle_paid_inbounds_menu(query):
    from xui_api import get_inbounds
    await query.edit_message_text("⏳ Загружаю инбаунды из панели...")
    result = await get_inbounds()
    if not result["success"]:
        await query.edit_message_text(
            f"❌ Не удалось загрузить инбаунды:\n<code>{result['error']}</code>",
            parse_mode="HTML",
            reply_markup=back_admin(),
        )
        return
    inbounds = result["inbounds"]
    if not inbounds:
        await query.edit_message_text("❌ На панели нет инбаундов.", reply_markup=back_admin())
        return
    cfg = load_config()
    selected = cfg.get("paid_preset_inbound_ids") or []
    await query.edit_message_text(
        "📡 <b>Инбаунды платной подписки</b>\n\n"
        "Нажми на инбаунд чтобы выбрать/снять.\n"
        "✅ — выбран, 🔘 — не выбран\n\n"
        "Если ничего не выбрано — автоматически берётся первый VLESS.",
        parse_mode="HTML",
        reply_markup=paid_inbounds_keyboard(inbounds, selected),
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
        await query.answer("Список инбаундов обновить не удалось", show_alert=True)
        return
    await query.edit_message_text(
        "📡 <b>Инбаунды платной подписки</b>\n\n"
        "Нажми на инбаунд чтобы выбрать/снять.\n"
        "✅ — выбран, 🔘 — не выбран\n\n"
        "Если ничего не выбрано — автоматически берётся первый VLESS.",
        parse_mode="HTML",
        reply_markup=paid_inbounds_keyboard(result["inbounds"], selected),
    )


# ── Создание подписки ─────────────────────────────────────────────────────────

async def handle_paid_create_sub(query, context: ContextTypes.DEFAULT_TYPE):
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
        "Пользователь должен написать боту хотя бы раз.\n"
        "ID можно узнать через @userinfobot\n\n"
        "Введи числовой ID:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def do_create_paid_sub(query_or_msg, tg_id: int, context: ContextTypes.DEFAULT_TYPE, reply_func):
    cfg = load_config()
    await reply_func("⏳ Создаю подписку в 3x-UI...")

    from xui_api import create_client, build_email
    from database import get_user_info
    user_row = await get_user_info(tg_id)
    username = user_row[2] if user_row else None
    email = build_email(tg_id, username)

    result = await create_client(
        expire_date=cfg["paid_preset_expire"],
        limit_ip=int(cfg["paid_preset_ip"]),
        limit_hwid=int(cfg["paid_preset_hwid"]),
        total_gb=int(cfg["paid_preset_traffic"]),
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
        limit_ip=int(cfg["paid_preset_ip"]),
        limit_hwid=int(cfg["paid_preset_hwid"]),
        total_gb=int(cfg["paid_preset_traffic"]),
    )

    traffic_str = f"{cfg['paid_preset_traffic']} ГБ" if int(cfg["paid_preset_traffic"]) > 0 else "безлимит"
    await reply_func(
        "✅ <b>Подписка создана!</b>\n\n"
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
            "🎉 <b>Вам выдана VPN подписка!</b>\n\n"
            f"📅 Действует до: <b>{result['expire']}</b>\n"
            f"📶 Трафик: <b>{traffic_str}</b>\n\n"
            f"🔗 Ссылка подписки:\n<code>{result['sub_url']}</code>\n\n"
            "Скопируй ссылку и вставь в приложение (Happ, v2rayNG и др.)"
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
    link_line = f'⛓‍💥 <a href="tg://user?id={tg_id}">Написать</a>' if tg_id else ""

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
            parse_mode="HTML",
            reply_markup=back_admin(),
        )
        return

    if context and tg_id:
        status_text = "✅ включена" if new_state else "⏸ приостановлена"
        await _notify_user(context.bot, tg_id,
            f"ℹ️ Ваша подписка <b>{status_text}</b>."
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

    if context and tg_id:
        await _notify_user(context.bot, tg_id,
            "🗑 Ваша подписка была <b>удалена</b>."
        )

    await query.edit_message_text(
        f"🗑 Подписка удалена из базы.\n{panel_status}",
        reply_markup=back_admin(),
    )


def save_paid_preset(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
