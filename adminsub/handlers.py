from html import escape

from telegram.ext import ContextTypes

from config import load_config
from core.keyboards import back_admin


from adminsub.storage import list_subs, get_sub
from paidsub import service as _svc
from adminsub.keyboards import (subs_list_keyboard, presets_keyboard, sub_view_keyboard,
                               sub_settings_keyboard)

_TIME_HINT = ("<blockquote>Время — в свободной форме:\n"
              "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, "
              "<code>1 месяц</code></blockquote>")


def _presets_ready(cfg: dict) -> bool:
    return all(cfg.get(k) is not None
               for k in ("preset_expire", "preset_hwid", "preset_traffic"))


def _fmt_presets(cfg: dict, squad_names: dict | None = None) -> str:
    """Тот же вид, что у платных подписок: сроки, лимиты, доступ."""
    exp = cfg.get("preset_expire", "не задана")
    hwid = cfg.get("preset_hwid", "не задан")
    traf_raw = cfg.get("preset_traffic")
    if traf_raw is None:
        traf = "не задан"
    elif traf_raw == 0:
        traf = "безлимит"
    else:
        traf = f"{traf_raw} ГБ"
    lte_raw = cfg.get("preset_lte")
    lte = f"{lte_raw} ГБ" if lte_raw is not None else "30 ГБ (по умолчанию)"

    names = squad_names or {}
    chosen = [names.get(u, u) for u in (cfg.get("rw_squads") or [])]
    return (
        "⏱ <b>Срок</b>\n<blockquote>"
        f"📅 Дата окончания: <b>{exp}</b>\n"
        "<i>Одна на все выдаваемые подписки</i></blockquote>\n\n"
        "📊 <b>Лимиты</b>\n<blockquote>"
        f"🖥 Устройств: <b>{hwid}</b>\n"
        f"📶 Трафик: <b>{traf}</b>\n"
        f"🌐 LTE-трафик: <b>{lte}</b></blockquote>\n\n"
        "🗂 <b>Сквады Remnawave</b>\n<blockquote>"
        + ("Выдаём: <b>{}</b>".format(", ".join(escape(str(c)) for c in chosen))
           if chosen else "Выдаём: <b>не выбраны</b>")
        + "</blockquote>"
    )


async def handle_admin_subs_menu(query, page: int = 1, scope: str = "all",
                                 sort: str = "new"):
    from adminsub.keyboards import ADMIN_TABS, ADMIN_SORT_LABELS
    from adminsub.storage import admin_counts
    if scope not in ADMIN_TABS:
        scope = "all"
    if sort not in ADMIN_SORT_LABELS:
        sort = "new"
    rows, total_pages = await list_subs(page, scope, sort)
    page = min(max(1, page), total_pages)
    counts = await admin_counts()
    cfg = load_config()
    ready = _presets_ready(cfg)
    icon, label = ADMIN_TABS[scope]
    header = "📋 <b>Админские подписки</b>"
    body = (f"\n\n{icon} <b>{label}</b> · сортировка: "
            f"<b>{ADMIN_SORT_LABELS[sort]}</b> · стр. {page} из {total_pages}")
    body += ("\n\n<blockquote>В этой вкладке пусто.</blockquote>" if not rows
             else "\n<i>Нажми на подписку, чтобы открыть</i>")
    if not ready:
        body += "\n\n⚠️ <i>Задай настройки, чтобы создавать подписки.</i>"
    await query.edit_message_text(
        header + body,
        parse_mode="HTML",
        reply_markup=subs_list_keyboard(rows, page, total_pages, ready,
                                        scope, sort, counts),
    )


async def handle_admin_search(query, context):
    from core.states import AWAITING_ADMIN_SUB_SEARCH
    context.user_data["state"] = AWAITING_ADMIN_SUB_SEARCH
    await query.edit_message_text(
        "🔎 <b>Поиск админской подписки</b>\n\n"
        "Пришли что знаешь: TG ID, email, часть UUID или Sub ID, ник или имя.",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def apply_admin_search(message, context, text: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from adminsub.storage import search_admin_subs
    rows = await search_admin_subs(text)
    if not rows:
        await message.reply_text("🔎 Ничего не нашлось.", reply_markup=back_admin())
        return
    lines = [f"🔎 <b>Нашлось подписок: {len(rows)}</b>\n"]
    kb = []
    for r in rows:
        lines.append(f"• <code>{escape(str(r[2] or ''))}</code> · до {str(r[3])[:10]} · "
                     f"TG <code>{r[1]}</code>")
        kb.append([InlineKeyboardButton(
            f"👤 {str(r[2] or r[1])} · до {str(r[3])[:10]}",
            callback_data=f"sub_view:{r[0]}")])
    kb.append([InlineKeyboardButton("◀️ К подпискам", callback_data="admin_subs")])
    await message.reply_text("\n".join(lines), parse_mode="HTML",
                             reply_markup=InlineKeyboardMarkup(kb))


async def handle_presets_menu(query):
    cfg = load_config()
    squad_names = {}
    if cfg.get("rw_squads"):
        import services.remnawave as rw
        got = await rw.list_squads()
        if got.get("ok"):
            for sq in got["squads"]:
                squad_names[sq["uuid"]] = sq["name"]
    await query.edit_message_text(
        "⚙️ <b>Настройки админских подписок</b>\n\n"
        + _fmt_presets(cfg, squad_names)
        + "\n\n<i>Применяются только к новым подпискам. У выданных условия "
          "зафиксированы при создании — меняются в самой подписке. "
          "Исключение: LTE-пресет подхватывают и старые подписки без своего лимита.</i>",
        parse_mode="HTML",
        reply_markup=presets_keyboard(),
    )


async def handle_preset_expire(query, context: ContextTypes.DEFAULT_TYPE):
    from core.states import AWAITING_PRESET_EXPIRE
    context.user_data["state"] = AWAITING_PRESET_EXPIRE
    await query.edit_message_text(
        "📅 <b>Дата окончания</b>\n\nВведи в формате <code>дд.мм.гггг</code>:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_preset_hwid(query, context: ContextTypes.DEFAULT_TYPE):
    from core.states import AWAITING_PRESET_HWID
    context.user_data["state"] = AWAITING_PRESET_HWID
    await query.edit_message_text(
        "🖥 <b>Лимит устройств</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_preset_traffic(query, context: ContextTypes.DEFAULT_TYPE):
    from core.states import AWAITING_PRESET_TRAFFIC
    context.user_data["state"] = AWAITING_PRESET_TRAFFIC
    await query.edit_message_text(
        "📶 <b>Трафик (ГБ)</b>\n\nВведи число в ГБ или <code>-</code> для безлимита:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_preset_lte(query, context: ContextTypes.DEFAULT_TYPE):
    from core.states import AWAITING_PRESET_LTE
    context.user_data["state"] = AWAITING_PRESET_LTE
    cfg = load_config()
    cur = cfg.get("preset_lte")
    cur_str = f"{cur} ГБ" if cur is not None else "30 ГБ (по умолчанию)"
    await query.edit_message_text(
        "🌐 <b>LTE-трафик новых подписок (ГБ в месяц)</b>\n\n"
        f"<blockquote>Сейчас: <b>{cur_str}</b></blockquote>\n\n"
        "Введи число в ГБ или <code>-</code>, чтобы вернуться к 30 ГБ по умолчанию. "
        "Подписки без своего лимита подхватят новый пресет автоматически, "
        "а со своим — нет, он правится в самой подписке.",
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
    from core.states import AWAITING_SUB_TG_ID
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
    """Тонкая обёртка над paidsub.service.create_admin_sub (та же работа,
    те же тексты); создание и уведомление живут в сервисе."""
    await reply_func("⏳ Создаю подписку…")
    bot = context.bot if hasattr(context, 'bot') else None
    result = await _svc.create_admin_sub(tg_id, bot=bot)
    if not result.get("ok"):
        if result["error"] == "presets_not_ready":
            await reply_func(
                "⚠️ Сначала задай все настройки (кнопка ⚙️ Настройки).",
                parse_mode="HTML",
            )
            return
        if result["error"] == "user_not_found":
            await reply_func(
                "❌ <b>Пользователь не найден</b>\n\n"
                "<i>Он должен написать боту хотя бы раз.</i>",
                parse_mode="HTML",
            )
            return
        await reply_func(
            f"❌ <b>Ошибка создания подписки</b>\n\n<code>{result['error']}</code>",
            parse_mode="HTML",
        )
        return
    await reply_func(
        "✅ <b>Подписка создана!</b>\n\n"
        f"👤 TG ID: <code>{tg_id}</code>\n"
        f"📧 Email: <code>{result['email']}</code>\n"
        f"📅 До: <b>{result['expire']}</b>\n"
        f"📶 Трафик: <b>{result['traffic_str']}</b>\n\n"
        f"🔗 Ссылка:\n<code>{result['sub_url']}</code>",
        parse_mode="HTML",
    )


def _fmt_bytes(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} КБ"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} МБ"
    return f"{b / 1024 ** 3:.2f} ГБ"


def _lte_label(row) -> str:
    from services.remnawave import lte_limit_label
    sub_lte = row[11] if len(row) > 11 else None
    return lte_limit_label(sub_lte, load_config().get("preset_lte"))


async def handle_sub_view(query, sub_id: int):
    from datetime import datetime
    from paidsub.storage import parse_sub_date
    from paidsub.time_parser import fmt_duration_precise
    NL = chr(10)

    card = await _svc.get_sub_card(sub_id, kind="admin")
    if not card.get("ok"):
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    row = card["row"]
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, _ip, limit_hwid, total_gb, created_at = row[:11]

    # расход и статус спрашиваем у панели: в базе их нет
    traffic_limit = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"
    if card["panel"]["traffic_ok"]:
        used = _fmt_bytes(int(card["panel"]["up"]) + int(card["panel"]["down"]))
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b>  ·  израсходовано {used}"
    else:
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b>"

    enabled = card["panel"]["enabled"]
    status_icon = "🟢" if enabled else "🔴"
    status_label = "активна" if enabled else "отключена"

    # кто это
    user = card["user"]
    uname = user["username"] if user else None
    shown = escape(str(user["first_name"])) if user and user["first_name"] else str(tg_id or "—")
    if tg_id and uname:
        tg_line = f'👤 <a href="https://t.me/{escape(uname)}">{shown}</a>'
    elif tg_id:
        tg_line = f'👤 <a href="tg://user?id={tg_id}">{shown}</a>'
    else:
        tg_line = "👤 <i>без привязки к Telegram</i>"
    if tg_id:
        tg_line += f"  ·  <code>{tg_id}</code>"

    # сколько осталось
    now_dt = datetime.now()
    expire_dt = parse_sub_date(expire)
    if expire_dt and now_dt < expire_dt:
        left = int((expire_dt - now_dt).total_seconds())
        time_line = ("📅 Действует до: <b>" + expire + "</b>" + NL +
                     "⏱ Осталось: <b>" + fmt_duration_precise(left) + "</b>")
    else:
        time_line = "📅 До: <b>" + expire + "</b>" + NL + "⏱ <b>Истекла</b>"

    referrer = card.get("referrer")
    ref_line = ""
    if referrer and referrer.get("tg_id"):
        ref_line = (NL + "🎁 Пригласил: <b>" + escape(str(referrer.get("first_name") or ""))
                    + "</b> · <code>" + str(referrer["tg_id"]) + "</code>")

    from config import sub_url_for_display
    display_url = sub_url_for_display(sub_url)

    text = (
        "📄 <b>Админская подписка #" + str(sub_id) + "</b>  " + status_icon + NL
        + tg_line + ref_line + NL
        + NL + "📌 <b>Срок</b>" + NL + "<blockquote>"
        + "Статус: <b>" + status_label + "</b>  ·  выдана вручную" + NL
        + time_line
        + "</blockquote>" + NL + NL
        + "📊 <b>Лимиты</b>" + NL + "<blockquote>"
        + "🖥 Устройств: <b>" + str(limit_hwid or "без ограничения") + "</b>" + NL
        + traffic_line + NL
        + "🌐 LTE-трафик в месяц: <b>" + _lte_label(row) + "</b>" + NL
        + "🕐 Создана: " + str(created_at)
        + "</blockquote>" + NL
        + NL + "🔧 <b>Технические данные</b>" + NL + "<blockquote expandable>"
        + "📧 Email: <code>" + email + "</code>" + NL
        + "🆔 UUID: <code>" + uuid_val + "</code>" + NL
        + "📋 Sub ID: <code>" + sub_id_str + "</code>"
        + "</blockquote>" + NL + NL
        + "🔗 <b>Ссылки</b>" + NL
        + "Для человека: <code>" + escape(display_url) + "</code>" + NL
        + "Прямая (key): <code>" + escape(sub_url) + "</code>"
    )
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=sub_view_keyboard(sub_id, enabled),
        disable_web_page_preview=True,
    )


async def handle_sub_toggle(query, sub_id: int, context=None):
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    await query.edit_message_text("⏳ Обновляю статус...")
    result = await _svc.toggle_sub(sub_id, kind="admin", bot=bot)
    if not result.get("ok"):
        if result.get("error") == "panel_client_not_found":
            await query.answer("❌ Клиент не найден в панели", show_alert=True)
        else:
            await query.edit_message_text(
                f"❌ Ошибка: <code>{result['error']}</code>",
                parse_mode="HTML",
                reply_markup=back_admin(),
            )
        return
    await handle_sub_view(query, sub_id)


async def handle_sub_freeze(query, sub_id: int, context=None):
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    await query.edit_message_text("🧊 Замораживаю подписку...")
    result = await _svc.freeze_sub(sub_id, kind="admin", bot=bot)
    if not result.get("ok"):
        if result.get("error") == "already_frozen":
            await query.answer("Подписка уже заморожена", show_alert=True)
        else:
            await query.edit_message_text(
                f"❌ Ошибка: <code>{result['error']}</code>",
                parse_mode="HTML", reply_markup=back_admin())
            return
    await handle_sub_view(query, sub_id)


async def handle_sub_history(query, sub_id: int, page: int = 1):
    """История событий по человеку: у админских подписок она теперь тоже
    пишется (раньше история была только у платных)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_user_history
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    if not row[1]:
        await query.answer("У подписки нет TG ID — истории нет", show_alert=True)
        return
    rows, total_pages = await get_user_history(row[1], page, 8)
    page = min(max(1, page), total_pages)
    try:
        from paidsub.handlers import _HISTORY_LABELS
    except Exception:
        _HISTORY_LABELS = {}
    lines = [f"📜 <b>История подписки #{sub_id}</b>\n"]
    if not rows:
        lines.append("<i>Событий пока не было.</i>")
    for _id, _tg, action, details, created_at in rows:
        label = _HISTORY_LABELS.get(action, action)
        lines.append(f"• <b>{escape(str(created_at)[:16])}</b> — {escape(str(label))}")
        if details:
            det = escape(str(details))
            if len(det) > 140:
                det = det[:140] + "…"
            lines.append(f"   <i>{det}</i>")
    kb = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            "⬅️", callback_data=f"sub_history:{sub_id}:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            "➡️", callback_data=f"sub_history:{sub_id}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ К подписке", callback_data=f"sub_view:{sub_id}")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_sub_delete(query, sub_id: int, context=None):
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_sub(sub_id)
    if row and row[2]:
        await query.edit_message_text("⏳ Удаляю из панели...")
    result = await _svc.delete_sub(sub_id, kind="admin", bot=bot)
    await query.edit_message_text(
        "🗑 Подписка удалена из базы." + chr(10) + result["panel_status"],
        reply_markup=back_admin(),
    )


# ── Индивидуальные настройки подписки ─────────────────────────────────────────

async def handle_sub_settings(query, sub_id: int):
    row = await get_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    _, _, _, _, _, _, expire, _limit_ip, limit_hwid, total_gb, _ = row[:11]
    traffic = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"
    hwid_str = str(limit_hwid) if limit_hwid > 0 else "безлимит"
    from services.remnawave import lte_limit_label
    sub_lte = row[11] if len(row) > 11 else None
    lte_str = lte_limit_label(sub_lte, load_config().get("preset_lte"))
    await query.edit_message_text(
        f"⚙️ <b>Настройки подписки #{sub_id}</b>\n\n"
        "<blockquote>"
        f"📅 Действует до: <b>{expire}</b>\n"
        f"🖥 Лимит устройств: <b>{hwid_str}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n"
        f"🌐 LTE-трафик в месяц: <b>{lte_str}</b></blockquote>\n\n"
        "<i>Правки уходят и в базу, и в панель. LTE-лимит — счётчик в боте, "
        "в панель он не уходит.</i>",
        parse_mode="HTML",
        reply_markup=sub_settings_keyboard(sub_id),
    )


async def handle_sub_edit_expire(query, sub_id: int, context):
    from core.states import AWAITING_SUB_EDIT_EXPIRE
    context.user_data["state"] = AWAITING_SUB_EDIT_EXPIRE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📅 <b>Дата окончания подписки #{sub_id}</b>\n\n"
        "Введи новую дату в формате <code>дд.мм.гггг</code>:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_sub_edit_hwid(query, sub_id: int, context):
    from core.states import AWAITING_SUB_EDIT_HWID
    context.user_data["state"] = AWAITING_SUB_EDIT_HWID
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🖥 <b>Лимит устройств подписки #{sub_id}</b>\n\nВведи число (0 = безлимит):",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_sub_edit_traffic(query, sub_id: int, context):
    from core.states import AWAITING_SUB_EDIT_TRAFFIC
    context.user_data["state"] = AWAITING_SUB_EDIT_TRAFFIC
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📶 <b>Трафик подписки #{sub_id}</b>\n\nВведи число ГБ или <code>-</code> для безлимита:",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_sub_edit_lte(query, sub_id: int, context):
    from core.states import AWAITING_SUB_EDIT_LTE
    context.user_data["state"] = AWAITING_SUB_EDIT_LTE
    context.user_data["edit_sub_id"] = sub_id
    row = await get_sub(sub_id)
    sub_lte = row[11] if row and len(row) > 11 else None
    from services.remnawave import lte_limit_label
    cur = lte_limit_label(sub_lte, load_config().get("preset_lte"))
    await query.edit_message_text(
        f"🌐 <b>LTE-трафик подписки #{sub_id} (ГБ в месяц)</b>\n\n"
        f"<blockquote>Сейчас: <b>{cur}</b></blockquote>\n\n"
        "Введи число в ГБ (0 — LTE закрыт для этой подписки) или "
        "<code>-</code>, чтобы вернуться к лимиту по умолчанию.",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Срок: добавить и убавить ──────────────────────────────────────────────────

async def handle_sub_extend(query, sub_id: int, context):
    from core.states import AWAITING_SUB_EXTEND
    context.user_data["state"] = AWAITING_SUB_EXTEND
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"➕ <b>Добавить срок подписке #{sub_id}</b>\n\n" + _TIME_HINT,
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_sub_reduce(query, sub_id: int, context):
    from core.states import AWAITING_SUB_REDUCE
    context.user_data["state"] = AWAITING_SUB_REDUCE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"➖ <b>Убавить срок подписке #{sub_id}</b>\n\n" + _TIME_HINT,
        parse_mode="HTML", reply_markup=back_admin(),
    )


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
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    email, limit_hwid = row[2], row[8]
    await query.edit_message_text("📱 Спрашиваю панель…")
    r = await _svc.list_devices(sub_id, kind="admin")

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
    bot = context.bot if hasattr(context, "bot") else None
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    res = await _svc.delete_device(sub_id, ref, kind="admin", bot=bot)
    if res.get("ok"):
        await query.answer("Устройство убрано")
    elif res.get("error") == "gone":
        await query.answer("Устройства уже нет в панели", show_alert=True)
    else:
        await query.answer(f"Панель не приняла: {res.get('error', '?')}"[:190], show_alert=True)
    await handle_sub_devices(query, sub_id)


async def handle_sub_hwid_clear(query, context, sub_id: int):
    bot = context.bot if hasattr(context, "bot") else None
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    res = await _svc.clear_hwid(sub_id, kind="admin", bot=bot)
    if res.get("ok"):
        await query.answer("Устройства очищены")
    else:
        await query.answer(f"Панель не приняла: {res.get('error', '?')}"[:190], show_alert=True)
    await handle_sub_devices(query, sub_id)


async def handle_sub_ips(query, sub_id: int):
    """С каких адресов подключалась подписка."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    await query.edit_message_text("🌐 Спрашиваю панель…")
    r = await _svc.list_ips(sub_id, kind="admin")

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
    row = await get_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    tg_id, email = row[1], row[2]

    await query.edit_message_text("🔁 Перевыпускаю ключ…")
    bot = context.bot if hasattr(context, "bot") else None
    result = await _svc.reissue_sub(sub_id, kind="admin", bot=bot)
    if not result.get("ok"):
        await query.edit_message_text(
            "❌ <b>Не получилось</b>" + chr(10) + chr(10)
            + "<blockquote><code>" + escape(str(result.get("error"))) + "</code></blockquote>" + chr(10) + chr(10)
            + "<i>Старая ссылка продолжает работать.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К подписке", callback_data=f"sub_view:{sub_id}")]]),
        )
        return

    new_url = result["new_url"]
    from core.log_channel import send_log
    await send_log(context.bot,
                   f"🔁 Перевыпущен ключ админской подписки #{sub_id} "
                   f"(<code>{escape(email)}</code>)")
    await query.edit_message_text(
        "✅ <b>Ключ перевыпущен</b>" + chr(10) + chr(10)
        + "<code>" + escape(new_url) + "</code>" + chr(10) + chr(10)
        + ("<i>Новую ссылку отправил человеку.</i>" if tg_id
           else "<i>TG у подписки не указан — ссылку передай сам.</i>"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К подписке", callback_data=f"sub_view:{sub_id}")]]),
        disable_web_page_preview=True,
    )


# ── Ники в панели ─────────────────────────────────────────────────────────────

async def refresh_panel_names(context=None) -> dict:
    """Приводит подписи админских клиентов в панели к текущим никам
    из Telegram — тот же единый формат, что и общая актуализация
    (см. panel.refresh_panel_descriptions).

    Имя клиента и ссылку подписки не трогаем: они связаны, и переименование
    сломало бы ключ у человека. Обновляем описание и TG ID — то, по чему
    клиента узнаёшь в панели. Если есть доступ к боту, ники проверяются
    живой проверкой в Telegram, а не берутся из базы.
    """
    from services.panel import refresh_panel_descriptions, tg_chat_resolver
    bot = getattr(context, "bot", None) if context else None
    resolver = await tg_chat_resolver(bot) if bot else None
    res = await refresh_panel_descriptions(("admin_subs",),
                                           resolve_chat=resolver)
    return {"ok": True, "checked": res["checked"], "updated": res["updated"],
            "errors": res["errors"]}


async def handle_subs_names_sync(query, context):
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import services.remnawave as rw
    if not rw.is_configured():
        await query.answer("Сначала задай адрес панели и токен", show_alert=True)
        return

    await query.edit_message_text("🔄 Проверяю ники в Telegram и сверяю с панелью…")
    res = await refresh_panel_names(context)
    errors = res.get("errors") or []
    lines = ["🔄 <b>Ники в панели</b>", "",
             "<blockquote>"
             f"Проверено подписок: <b>{res['checked']}</b>\n"
             f"Обновлено подписей: <b>{res['updated']}</b>\n"
             f"С ошибкой: <b>{len(errors)}</b></blockquote>"]
    if errors:
        shown = "\n".join(escape(e[:120]) for e in errors[:5])
        lines += ["", "⚠️ <b>Не получилось</b>", f"<blockquote>{shown}</blockquote>"]
        if len(errors) > 5:
            lines.append(f"<i>…и ещё {len(errors) - 5}</i>")
    lines += ["", "<i>Имя клиента и ссылка подписки не менялись — они связаны, "
              "и переименование сломало бы ключ. Ник и TG ID лежат в описании.</i>"]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К настройкам", callback_data="sub_presets")]]),
    )
