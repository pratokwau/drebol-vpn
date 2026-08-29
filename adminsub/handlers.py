from telegram.ext import ContextTypes

from config import load_config, save_config
from keyboards import back_admin
from adminsub.storage import list_subs, add_sub, get_sub, delete_sub, get_all_subs_with_tg, update_sub_email
from adminsub.keyboards import subs_list_keyboard, presets_keyboard, sub_view_keyboard, inbounds_keyboard, auto_update_keyboard


def _presets_ready(cfg: dict) -> bool:
    return all(cfg.get(k) is not None for k in ("preset_expire", "preset_ip", "preset_hwid", "preset_traffic"))


def _fmt_presets(cfg: dict, inbound_names: dict | None = None) -> str:
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
    inbound_names = {}
    inbound_ids = cfg.get("preset_inbound_ids") or []
    if inbound_ids:
        from xui_api import get_inbounds
        result = await get_inbounds()
        if result["success"]:
            for inb in result["inbounds"]:
                name = inb.get("tag") or inb.get("remark") or f"#{inb.get('id')}"
                inbound_names[inb.get("id")] = name
    await query.edit_message_text(
        "⚙️ <b>Настройки подписки (по умолчанию)</b>\n\n"
        + _fmt_presets(cfg, inbound_names)
        + "\n\nВыбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=presets_keyboard(),
    )


async def handle_auto_update_settings(query):
    cfg = load_config()
    enabled = cfg.get("auto_update_usernames", False)
    days = cfg.get("auto_update_days", 2)
    last_run = cfg.get("auto_update_last_run")
    last_line = f"\n🕐 Последний запуск: {last_run}" if last_run else ""
    await query.edit_message_text(
        "⏰ <b>Авто-обновление ников</b>\n\n"
        "Бот проверяет, изменился ли юзернейм у пользователей с подписками, "
        "и обновляет email в панели.\n"
        + last_line,
        parse_mode="HTML",
        reply_markup=auto_update_keyboard(enabled, days),
    )


async def handle_toggle_auto_update(query):
    cfg = load_config()
    cfg["auto_update_usernames"] = not cfg.get("auto_update_usernames", False)
    save_config(cfg)
    await handle_auto_update_settings(query)


async def handle_set_auto_update_days(query, context):
    from states import AWAITING_AUTO_UPDATE_DAYS
    context.user_data["state"] = AWAITING_AUTO_UPDATE_DAYS
    cfg = load_config()
    current = cfg.get("auto_update_days", 2)
    await query.edit_message_text(
        f"📝 <b>Интервал проверки</b>\n\n"
        f"Сейчас: <b>{current} дн.</b>\n\n"
        "Введи новое значение (целое число дней, минимум 1):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_run_sync_now(query):
    await query.edit_message_text("⏳ Запускаю синхронизацию ников...")
    result = await sync_usernames()
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


async def sync_usernames(context=None) -> dict:
    """Обновляет email в панели если юзернейм изменился. Возвращает отчёт."""
    from xui_api import update_client_email, build_email
    from database import get_user_info
    from datetime import datetime

    subs = await get_all_subs_with_tg()
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
        new_email = build_email(tg_id, username)
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
            await update_sub_email(sub_id, new_email)
            updated += 1
        else:
            errors.append(f"{old_email} → {new_email}: {result['error'][:100]}")

    cfg = load_config()
    cfg["auto_update_last_run"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    save_config(cfg)
    if updated:
        print(f"[sync_usernames] обновлено {updated} email(ов)")
    return {"total": len(subs), "need_update": need_update, "updated": updated, "skipped": skipped, "errors": errors}


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


def _fmt_bytes(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} КБ"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} МБ"
    return f"{b / 1024 ** 3:.2f} ГБ"


async def handle_sub_view(query, sub_id: int):
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at = row
    traffic_limit = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    # Получаем реальный трафик и статус из панели
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
        reply_markup=sub_view_keyboard(sub_id, enabled),
        disable_web_page_preview=True,
    )


async def handle_sub_toggle(query, sub_id: int):
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
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
    await handle_sub_view(query, sub_id)


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
