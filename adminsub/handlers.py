from telegram import Bot
from telegram.ext import ContextTypes

from config import load_config, save_config
from keyboards import back_admin


async def _notify_user(bot: Bot, tg_id: int | None, text: str):
    """Отправляет уведомление юзеру. Молча пропускает если не удалось."""
    if not tg_id:
        return
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML")
    except Exception:
        pass
from adminsub.storage import list_subs, add_sub, get_sub, delete_sub, update_sub_field
from adminsub.keyboards import (subs_list_keyboard, presets_keyboard, sub_view_keyboard,
                               sub_settings_keyboard)

_TIME_HINT = ("<blockquote>Время — в свободной форме:\n"
              "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, "
              "<code>1 месяц</code></blockquote>")


def _presets_ready(cfg: dict) -> bool:
    return all(cfg.get(k) is not None
               for k in ("preset_expire", "preset_hwid", "preset_traffic"))


def _fmt_presets(cfg: dict, squad_names: dict | None = None) -> str:
    exp = cfg.get("preset_expire", "не задан")
    hwid = cfg.get("preset_hwid", "не задан")
    traf_raw = cfg.get("preset_traffic")
    if traf_raw is None:
        traf = "не задан"
    elif traf_raw == 0:
        traf = "безлимит"
    else:
        traf = f"{traf_raw} ГБ"
    head = (f"📅 Дата окончания: <b>{exp}</b>\n"
            f"🖥 Лимит устройств: <b>{hwid}</b>\n"
            f"📶 Трафик: <b>{traf}</b>\n")
    names = squad_names or {}
    chosen = [names.get(u, u) for u in (cfg.get("rw_squads") or [])]
    return head + ("👥 Сквады: <b>{}</b>".format(", ".join(chosen)) if chosen
                   else "👥 Сквады: <b>не выбраны</b>")


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
    squad_names = {}
    if cfg.get("rw_squads"):
        import remnawave as rw
        got = await rw.list_squads()
        if got.get("ok"):
            for sq in got["squads"]:
                squad_names[sq["uuid"]] = sq["name"]
    await query.edit_message_text(
        "⚙️ <b>Настройки подписки (по умолчанию)</b>\n\n"
        + _fmt_presets(cfg, squad_names)
        + "\n\nВыбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=presets_keyboard(),
    )


async def handle_preset_expire(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PRESET_EXPIRE
    context.user_data["state"] = AWAITING_PRESET_EXPIRE
    await query.edit_message_text(
        "📅 <b>Дата окончания</b>\n\nВведи в формате <code>дд.мм.гггг</code>:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_preset_hwid(query, context: ContextTypes.DEFAULT_TYPE):
    from states import AWAITING_PRESET_HWID
    context.user_data["state"] = AWAITING_PRESET_HWID
    await query.edit_message_text(
        "🖥 <b>Лимит устройств</b>\n\nВведи число (0 = безлимит):",
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
    await reply_func("⏳ Создаю подписку…")

    from panel import create_client, build_email
    from database import get_user_info
    user_row = await get_user_info(tg_id)
    username = user_row[2] if user_row else None
    email = build_email(tg_id, username)

    result = await create_client(
        expire_date=cfg["preset_expire"],
        limit_ip=0,                      # лимита по IP в панели нет, только по устройствам
        limit_hwid=int(cfg["preset_hwid"]),
        total_gb=int(cfg["preset_traffic"]),
        email=email,
        tg_id=tg_id,
        note=f"@{username}" if username else "",
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
        limit_ip=0,
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

    # Уведомление юзеру
    bot = context.bot if hasattr(context, 'bot') else None
    if bot:
        await _notify_user(bot, tg_id,
            "🎉 <b>Вам выдана админская подписка!</b>\n\n"
            f"📅 Действует до: <b>{result['expire']}</b>\n"
            f"📶 Трафик: <b>{traffic_str}</b>\n\n"
            f"🔗 Ссылка подписки:\n<code>{result['sub_url']}</code>\n\n"
            "Скопируй ссылку и вставь в приложение (INCY, Happ и др.)"
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
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, _limit_ip, limit_hwid, total_gb, created_at = row
    traffic_limit = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    # Получаем реальный трафик и статус из панели
    from panel import get_client_traffic, get_client_info
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
    # Если есть username — ссылка через @, иначе через tg://user?id=
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
        f"🖥 Устройств: <b>{limit_hwid or 'без ограничения'}</b>\n"
        f"{traffic_line}\n"
        f"🕐 Создано: {created_at}\n"
        + (f"\n{link_line}\n" if link_line else "") +
        f"\n🔗 Ссылка:\n<code>{sub_url}</code>",
        parse_mode="HTML",
        reply_markup=sub_view_keyboard(sub_id, enabled),
        disable_web_page_preview=True,
    )


async def handle_sub_toggle(query, sub_id: int, context=None):
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    tg_id = row[1]
    email = row[2]
    from panel import get_client_info, toggle_client
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
            f"ℹ️ Ваша админская подписка <b>{status_text}</b>."
        )

    await handle_sub_view(query, sub_id)


async def handle_sub_delete(query, sub_id: int, context=None):
    row = await get_sub(sub_id)
    tg_id = row[1] if row else None
    email = row[2] if row else None

    if email:
        from panel import delete_client
        await query.edit_message_text("⏳ Удаляю из панели...")
        panel_result = await delete_client(email)
        panel_status = "✅ удалена из панели" if panel_result["success"] else f"⚠️ панель: {panel_result.get('error', '?')}"
    else:
        panel_status = "⚠️ email не найден, из панели не удалено"

    await delete_sub(sub_id)

    if context and tg_id:
        await _notify_user(context.bot, tg_id,
            "🗑 Ваша админская подписка была <b>удалена</b>."
        )

    await query.edit_message_text(
        f"🗑 Подписка удалена из базы.\n{panel_status}",
        reply_markup=back_admin(),
    )


# ── Индивидуальные настройки подписки ─────────────────────────────────────────

async def handle_sub_settings(query, sub_id: int):
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    _, tg_id, email, _, _, _, expire, _limit_ip, limit_hwid, total_gb, _ = row
    traffic = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"
    hwid_str = str(limit_hwid) if limit_hwid > 0 else "безлимит"
    await query.edit_message_text(
        f"⚙️ <b>Настройки подписки #{sub_id}</b>\n\n"
        f"📅 Дата окончания: <b>{expire}</b>\n"
        f"🖥 Лимит устройств: <b>{hwid_str}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n\n"
        "Выбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=sub_settings_keyboard(sub_id),
    )


async def handle_sub_edit_expire(query, sub_id: int, context):
    from states import AWAITING_SUB_EDIT_EXPIRE
    context.user_data["state"] = AWAITING_SUB_EDIT_EXPIRE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📅 <b>Дата окончания подписки #{sub_id}</b>\n\n"
        "Введи новую дату в формате <code>дд.мм.гггг</code>:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_sub_edit_hwid(query, sub_id: int, context):
    from states import AWAITING_SUB_EDIT_HWID
    context.user_data["state"] = AWAITING_SUB_EDIT_HWID
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🖥 <b>Лимит устройств подписки #{sub_id}</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_sub_edit_traffic(query, sub_id: int, context):
    from states import AWAITING_SUB_EDIT_TRAFFIC
    context.user_data["state"] = AWAITING_SUB_EDIT_TRAFFIC
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📶 <b>Трафик подписки #{sub_id}</b>\n\nВведи число ГБ или <code>-</code> для безлимита:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Срок: добавить и убавить ──────────────────────────────────────────────────

async def handle_sub_extend(query, sub_id: int, context):
    from states import AWAITING_SUB_EXTEND
    context.user_data["state"] = AWAITING_SUB_EXTEND
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"➕ <b>Добавить срок подписке #{sub_id}</b>\n\n" + _TIME_HINT,
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_sub_reduce(query, sub_id: int, context):
    from states import AWAITING_SUB_REDUCE
    context.user_data["state"] = AWAITING_SUB_REDUCE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"➖ <b>Убавить срок подписке #{sub_id}</b>\n\n" + _TIME_HINT,
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def shift_sub_expire(sub_id: int, seconds: int, direction: int, context) -> dict:
    """Двигает срок админской подписки и в базе, и в панели.

    Плюс — считаем от остатка, а если срок уже вышел, от сегодня: иначе
    «добавить неделю» просроченной подписке ничего бы не дало.
    """
    from datetime import datetime, timedelta
    from panel import update_client_expire, get_client_info, toggle_client
    from paidsub.time_parser import fmt_duration

    row = await get_sub(sub_id)
    if not row:
        return {"ok": False, "error": "подписка не найдена"}
    tg_id, email, expire_str = row[1], row[2], row[6]

    expire_dt = None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            expire_dt = datetime.strptime(expire_str, fmt)
            break
        except ValueError:
            continue
    if expire_dt is None:
        expire_dt = datetime.now()

    if direction > 0:
        base = expire_dt if expire_dt > datetime.now() else datetime.now()
        new_expire = base + timedelta(seconds=seconds)
    else:
        new_expire = expire_dt - timedelta(seconds=seconds)
    new_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")

    await update_sub_field(sub_id, "expire_date", new_str)
    r = await update_client_expire(email, new_str)
    if not r.get("success"):
        return {"ok": False, "error": r.get("error", "?"), "until": new_str}

    if direction > 0:
        # добавили срок — заодно вернём доступ, если он был закрыт
        info = await get_client_info(email)
        if info.get("success") and not info.get("enabled", True):
            await toggle_client(email, True)

    bot = context.bot if hasattr(context, "bot") else None
    if bot and tg_id:
        if direction > 0:
            await _notify_user(bot, tg_id,
                "🎉 <b>Подписка продлена!</b>\n\n"
                f"<blockquote>➕ Добавлено: <b>{fmt_duration(seconds)}</b>\n"
                f"📅 Действует до: <b>{new_str[:16]}</b></blockquote>")
        else:
            await _notify_user(bot, tg_id,
                "ℹ️ <b>Срок подписки изменён</b>\n\n"
                f"<blockquote>➖ Убавлено: <b>{fmt_duration(seconds)}</b>\n"
                f"📅 Действует до: <b>{new_str[:16]}</b></blockquote>")
    return {"ok": True, "until": new_str}


# ── Устройства и адреса ───────────────────────────────────────────────────────

def _when(value) -> str:
    """Время из панели: строка с датой, реже — число секунд или миллисекунд."""
    from datetime import datetime
    if value in (None, "", 0, "0"):
        return "—"
    try:
        num = int(float(value))
        if num <= 0:
            return "—"
        if num > 10 ** 12:
            num //= 1000
        return datetime.fromtimestamp(num).strftime("%d.%m %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    text = str(value).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m %H:%M")
        except ValueError:
            continue
    return "?"


async def handle_sub_devices(query, sub_id: int):
    """Устройства, которые панель запомнила по этой подписке."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from panel import get_client_hwids
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    email, limit_hwid = row[2], row[8]
    await query.edit_message_text("📱 Спрашиваю панель…")
    r = await get_client_hwids(email)

    lines = [f"📱 <b>Устройства подписки #{sub_id}</b>\n",
             f"🖥 Лимит: <b>{limit_hwid or 'без ограничения'}</b>"]
    kb = []
    if not r.get("ok"):
        lines.append(f"\n❌ Панель не ответила:\n<code>{escape(str(r.get('error')))}</code>")
    else:
        items = r["items"]
        lines.append(f"📦 Запомнено устройств: <b>{len(items)}</b>\n")
        if not items:
            lines.append("<i>Пока ни одного — человек ещё не подключался.</i>")
        for i, d in enumerate(items[:12], 1):
            name = " · ".join(str(x) for x in (d.get("deviceOs"), d.get("osVersion"),
                                               d.get("deviceModel")) if x) or "устройство"
            app = str(d.get("userAgent") or "").split()[0] if d.get("userAgent") else ""
            app_line = f" · 📲 {escape(app)}" if app else ""
            lines.append(f"{i}. {escape(name)}{app_line}\n"
                         f"     был: {_when(d.get('lastSeen'))} · с {_when(d.get('firstSeen'))}")
            kb.append([InlineKeyboardButton(
                f"🗑 Убрать {i} — {name[:24]}",
                callback_data=f"sub_hwid_del:{sub_id}:{str(d.get('id'))[:20]}")])
        if len(items) > 12:
            lines.append(f"…и ещё {len(items) - 12}")
        if items:
            kb.append([InlineKeyboardButton("🧹 Очистить все устройства",
                                            callback_data=f"sub_hwid_clear:{sub_id}")])
    kb.append([InlineKeyboardButton("🌐 IP-адреса", callback_data=f"sub_ips:{sub_id}"),
               InlineKeyboardButton("🔄 Обновить", callback_data=f"sub_devices:{sub_id}")])
    kb.append([InlineKeyboardButton("◀️ К подписке", callback_data=f"sub_view:{sub_id}")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_sub_hwid_del(query, context, sub_id: int, ref: str):
    from panel import delete_client_hwid, resolve_hwid
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    hwid_id = await resolve_hwid(row[2], ref)
    if hwid_id is None:
        await query.answer("Устройства уже нет в панели", show_alert=True)
        await handle_sub_devices(query, sub_id)
        return
    res = await delete_client_hwid(row[2], hwid_id)
    await query.answer("Устройство убрано" if res.get("success")
                       else f"Панель не приняла: {res.get('error', '?')}"[:190],
                       show_alert=not res.get("success"))
    await handle_sub_devices(query, sub_id)


async def handle_sub_hwid_clear(query, context, sub_id: int):
    from panel import clear_client_hwids
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    res = await clear_client_hwids(row[2])
    if res.get("success"):
        await query.answer("Устройства очищены")
        if row[1]:
            await _notify_user(context.bot, row[1],
                "📱 <b>Список устройств очищен</b>\n\n"
                "<blockquote>Включите VPN на нужных устройствах — "
                "они добавятся заново.</blockquote>")
    else:
        await query.answer(f"Панель не приняла: {res.get('error', '?')}"[:190], show_alert=True)
    await handle_sub_devices(query, sub_id)


async def handle_sub_ips(query, sub_id: int):
    """С каких адресов подключалась подписка."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from panel import get_client_ips
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    await query.edit_message_text("🌐 Спрашиваю панель…")
    r = await get_client_ips(row[2])

    lines = [f"🌐 <b>IP-адреса подписки #{sub_id}</b>\n"]
    if not r.get("ok"):
        lines.append(f"❌ Панель не ответила:\n<code>{escape(str(r.get('error')))}</code>")
    else:
        items = r["items"]
        lines.append(f"📍 Адресов: <b>{len(items)}</b>\n")
        if not items:
            lines.append("<i>Панель пока не записала ни одного адреса.</i>")
        for i, d in enumerate(items[:15], 1):
            tail = f" · {_when(d['ts'])}" if d.get("ts") else ""
            node = f" · {escape(str(d['node']))}" if d.get("node") else ""
            lines.append(f"{i}. <code>{escape(str(d['ip']))}</code>{tail}{node}")
        if len(items) > 15:
            lines.append(f"…и ещё {len(items) - 15}")
    lines.append("\n<i>Адреса панель держит вместе с устройствами: "
                 "чтобы забыть адрес, убери устройство.</i>")
    kb = [[InlineKeyboardButton("📱 Устройства", callback_data=f"sub_devices:{sub_id}"),
           InlineKeyboardButton("🔄 Обновить", callback_data=f"sub_ips:{sub_id}")],
          [InlineKeyboardButton("◀️ К подписке", callback_data=f"sub_view:{sub_id}")]]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


# ── Перевыпуск ключа ──────────────────────────────────────────────────────────

async def handle_sub_reissue(query, context, sub_id: int):
    """Меняет ссылку подписки. Старая перестаёт работать, поэтому спрашиваем."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from panel import reissue_subscription
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    tg_id, email = row[1], row[2]

    await query.edit_message_text("🔁 Перевыпускаю ключ…")
    result = await reissue_subscription(email)
    if not result.get("success"):
        await query.edit_message_text(
            "❌ <b>Не получилось</b>\n\n"
            f"<blockquote><code>{escape(str(result.get('error')))}</code></blockquote>\n\n"
            "<i>Старая ссылка продолжает работать.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К подписке", callback_data=f"sub_view:{sub_id}")]]),
        )
        return

    new_url = result["sub_url"]
    await update_sub_field(sub_id, "uuid", result.get("new_uuid", ""))
    await update_sub_field(sub_id, "sub_id", result.get("sub_id", ""))
    await update_sub_field(sub_id, "sub_url", new_url)

    from log_channel import send_log
    await send_log(context.bot,
                   f"🔁 Перевыпущен ключ админской подписки #{sub_id} "
                   f"(<code>{escape(email)}</code>)")
    if tg_id:
        await _notify_user(context.bot, tg_id,
            "🔁 <b>Ключ подписки перевыпущен</b>\n\n"
            f"<blockquote><code>{escape(new_url)}</code></blockquote>\n\n"
            "Удалите старую подписку в приложении и вставьте эту ссылку — "
            "старая больше не работает.")
    await query.edit_message_text(
        f"✅ <b>Ключ перевыпущен</b>\n\n<code>{escape(new_url)}</code>\n\n"
        + ("<i>Новую ссылку отправил человеку.</i>" if tg_id
           else "<i>TG у подписки не указан — ссылку передай сам.</i>"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К подписке", callback_data=f"sub_view:{sub_id}")]]),
        disable_web_page_preview=True,
    )


def save_preset(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
