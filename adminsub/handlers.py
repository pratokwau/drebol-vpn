from telegram.ext import ContextTypes

from config import load_config, save_config
from keyboards import back_admin
from adminsub.storage import list_subs, add_sub, get_sub, delete_sub, get_all_subs_with_tg, update_sub_email
from adminsub.keyboards import subs_list_keyboard, presets_keyboard, sub_view_keyboard, inbounds_keyboard


def _presets_ready(cfg: dict) -> bool:
    return all(cfg.get(k) is not None for k in ("preset_expire", "preset_ip", "preset_hwid", "preset_traffic"))


def _fmt_presets(cfg: dict) -> str:
    exp = cfg.get("preset_expire", "не задан")
    ip = cfg.get("preset_ip", "не задан")
    hwid = cfg.get("preset_hwid", "не задан")
    traf_raw = cfg.get("preset_traffic")
    if traf_raw is None:
        traf = "не задан"
    elif traf_raw == 0:
        traf = "безлимит"
    else:
        traf = f"{traf_raw} ГБ"
    inbound_ids = cfg.get("preset_inbound_ids") or []
    inb_label = ", ".join(str(i) for i in inbound_ids) if inbound_ids else "авто (первый VLESS)"
    return (
        f"📅 Дата окончания: <b>{exp}</b>\n"
        f"🌐 Лимит IP: <b>{ip}</b>\n"
        f"🖥 Лимит HWID: <b>{hwid}</b>\n"
        f"📶 Трафик: <b>{traf}</b>\n"
        f"📡 Инбаунды: <b>{inb_label}</b>"
    )


async def handle_admin_subs_menu(query, page: int = 1):
    rows, total_pages = await list_subs(page)
    cfg = load_config()
    ready = _presets_ready(cfg)
    header = "📋 <b>Админские подписки</b>\n"
    body = "\n\nПодписок пока нет." if not rows else f"\n\nСтр. {page}/{total_pages}"
    if not ready:
        body += "\n\n⚠️ Задай настройки, чтобы создавать подписки в один клик."
    await query.edit_message_text(
        header + body,
        parse_mode="HTML",
        reply_markup=subs_list_keyboard(rows, page, total_pages, ready),
    )


async def handle_presets_menu(query):
    cfg = load_config()
    auto_update = cfg.get("auto_update_usernames", False)
    await query.edit_message_text(
        "⚙️ <b>Настройки подписки (по умолчанию)</b>\n\n"
        + _fmt_presets(cfg)
        + "\n\nВыбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=presets_keyboard(auto_update),
    )


async def handle_toggle_auto_update(query):
    cfg = load_config()
    cfg["auto_update_usernames"] = not cfg.get("auto_update_usernames", False)
    save_config(cfg)
    await handle_presets_menu(query)


async def sync_usernames(context=None):
    """Фоновая задача: обновляет email в панели если юзернейм изменился."""
    from xui_api import update_client_email, build_email
    from database import get_user_info

    subs = await get_all_subs_with_tg()
    updated = 0
    for row in subs:
        sub_id, tg_id, old_email, uuid_val, sub_id_str, expire_date, limit_ip, limit_hwid, total_gb = row
        user_row = await get_user_info(tg_id)
        if not user_row:
            continue
        username = user_row[2]
        new_email = build_email(tg_id, username)
        if new_email == old_email:
            continue
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
            await update_sub_email(sub_id, new_email)
            updated += 1
    if updated:
        print(f"[sync_usernames] обновлено {updated} email(ов)")


async def handle_preset_expire(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PRESET_EXPIRE
    context.user_data["state"] = AWAITING_PRESET_EXPIRE
    await query.edit_message_text(
        "📅 <b>Дата окончания</b>\n\nВведи в формате <code>дд.мм.гггг</code>:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_preset_ip(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PRESET_IP
    context.user_data["state"] = AWAITING_PRESET_IP
    await query.edit_message_text(
        "🌐 <b>Лимит IP</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_preset_hwid(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PRESET_HWID
    context.user_data["state"] = AWAITING_PRESET_HWID
    await query.edit_message_text(
        "🖥 <b>Лимит HWID</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_preset_traffic(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PRESET_TRAFFIC
    context.user_data["state"] = AWAITING_PRESET_TRAFFIC
    await query.edit_message_text(
        "📶 <b>Трафик (ГБ)</b>\n\nВведи число в ГБ или <code>-</code> для безлимита:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_inbounds_menu(query):
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
        await query.edit_message_text(
            "❌ На панели нет инбаундов.",
            reply_markup=back_admin(),
        )
        return
    cfg = load_config()
    selected = cfg.get("preset_inbound_ids") or []
    await query.edit_message_text(
        "📡 <b>Инбаунды подписки</b>\n\n"
        "Нажми на инбаунд чтобы выбрать/снять.\n"
        "✅ — выбран, 🔘 — не выбран\n\n"
        "Если ничего не выбрано — автоматически берётся первый VLESS.",
        parse_mode="HTML",
        reply_markup=inbounds_keyboard(inbounds, selected),
    )


async def handle_toggle_inbound(query, inbound_id: int):
    from xui_api import get_inbounds
    cfg = load_config()
    selected = list(cfg.get("preset_inbound_ids") or [])
    if inbound_id in selected:
        selected.remove(inbound_id)
    else:
        selected.append(inbound_id)
    cfg["preset_inbound_ids"] = selected
    save_config(cfg)

    # перезагрузить список
    result = await get_inbounds()
    if not result["success"]:
        await query.answer("Список инбаундов обновить не удалось", show_alert=True)
        return
    inbounds = result["inbounds"]
    await query.edit_message_text(
        "📡 <b>Инбаунды подписки</b>\n\n"
        "Нажми на инбаунд чтобы выбрать/снять.\n"
        "✅ — выбран, 🔘 — не выбран\n\n"
        "Если ничего не выбрано — автоматически берётся первый VLESS.",
        parse_mode="HTML",
        reply_markup=inbounds_keyboard(inbounds, selected),
    )


async def handle_create_sub(query, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    if not _presets_ready(cfg):
        await query.edit_message_text(
            "⚠️ Сначала задай все настройки (кнопка ⚙️ Настройки).",
            reply_markup=back_admin(),
        )
        return
    from states import AWAITING_SUB_TG_ID
    context.user_data["state"] = AWAITING_SUB_TG_ID
    await query.edit_message_text(
        "👤 <b>Введи Telegram ID пользователя</b>\n\n"
        "Пользователь должен написать боту хотя бы раз.\n"
        "ID можно узнать через @userinfobot\n\n"
        "Введи числовой ID:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def do_create_sub(query_or_msg, tg_id: int, context: ContextTypes.DEFAULT_TYPE, reply_func):
    cfg = load_config()
    await reply_func("⏳ Создаю подписку в 3x-UI...")

    from xui_api import create_client, build_email
    from database import get_user_info
    user_row = await get_user_info(tg_id)
    username = user_row[2] if user_row else None
    email = build_email(tg_id, username)

    result = await create_client(
        expire_date=cfg["preset_expire"],
        limit_ip=int(cfg["preset_ip"]),
        limit_hwid=int(cfg["preset_hwid"]),
        total_gb=int(cfg["preset_traffic"]),
        email=email,
    )

    if not result["success"]:
        await reply_func(
            f"❌ <b>Ошибка создания подписки</b>\n\n<code>{result['error']}</code>",
            parse_mode="HTML",
        )
        return

    await add_sub(
        email=result["email"],
        uuid_val=result["uuid"],
        sub_id=result["sub_id"],
        sub_url=result["sub_url"],
        expire_date=result["expire"],
        limit_ip=int(cfg["preset_ip"]),
        limit_hwid=int(cfg["preset_hwid"]),
        total_gb=int(cfg["preset_traffic"]),
        tg_id=tg_id,
    )

    traffic_str = f"{cfg['preset_traffic']} ГБ" if int(cfg["preset_traffic"]) > 0 else "безлимит"
    await reply_func(
        "✅ <b>Подписка создана!</b>\n\n"
        f"👤 TG ID: <code>{tg_id}</code>\n"
        f"📧 Email: <code>{result['email']}</code>\n"
        f"📅 До: <b>{result['expire']}</b>\n"
        f"📶 Трафик: <b>{traffic_str}</b>\n\n"
        f"🔗 Ссылка:\n<code>{result['sub_url']}</code>",
        parse_mode="HTML",
    )


async def handle_sub_view(query, sub_id: int):
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at = row
    traffic = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"
    tg_line = f"👤 TG ID: <code>{tg_id}</code>\n" if tg_id else ""
    await query.edit_message_text(
        f"📄 <b>Подписка #{sub_id}</b>\n\n"
        + tg_line +
        f"📧 Email: <code>{email}</code>\n"
        f"🆔 UUID: <code>{uuid_val}</code>\n"
        f"📅 До: <b>{expire}</b>\n"
        f"🌐 Лимит IP: <b>{limit_ip}</b>\n"
        f"🖥 Лимит HWID: <b>{limit_hwid}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n"
        f"🕐 Создано: {created_at}\n\n"
        f"🔗 Ссылка:\n<code>{sub_url}</code>",
        parse_mode="HTML",
        reply_markup=sub_view_keyboard(sub_id),
    )


async def handle_sub_delete(query, sub_id: int):
    row = await get_sub(sub_id)
    email = row[2] if row else None  # row: id, tg_id, email, ...

    if email:
        from xui_api import delete_client
        await query.edit_message_text("⏳ Удаляю из панели...")
        panel_result = await delete_client(email)
        panel_status = "✅ удалена из панели" if panel_result["success"] else f"⚠️ панель: {panel_result.get('error', '?')}"
    else:
        panel_status = "⚠️ email не найден, из панели не удалено"

    await delete_sub(sub_id)
    await query.edit_message_text(
        f"🗑 Подписка удалена из базы.\n{panel_status}",
        reply_markup=back_admin(),
    )


def save_preset(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
