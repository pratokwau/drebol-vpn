from datetime import datetime, timedelta

from telegram import Bot
from telegram.ext import ContextTypes

from config import ADMIN_ID, load_config, save_config
from keyboards import back_admin, back_main

from paidsub.storage import (
    add_paid_sub, get_paid_sub, delete_paid_sub, get_paid_sub_by_tg_id,
    add_request, get_pending_request, resolve_request,
    update_paid_sub_field, get_expired_paid_subs, set_expire_date,
    add_history,
    get_referrer, mark_referral_rewarded, get_all_referral_stats,
    get_promo, promo_used_by, record_promo_use, promo_use_count, get_pending_promo,
)
from paidsub.keyboards import (
    paid_subs_list_keyboard, paid_presets_keyboard, paid_sub_view_keyboard,
    approve_keyboard, paid_sub_settings_keyboard,
)
from paidsub.time_parser import fmt_duration, fmt_duration_precise


def _esc_name(value, fallback="") -> str:
    """Имя или @username человека для сообщения с разметкой.

    Без экранирования имя вида «<b>Иван» срывает отправку уведомления целиком,
    и админ просто не узнаёт о заявке.
    """
    from html import escape
    return escape(str(value if value not in (None, "") else fallback))


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
        cfg.get("paid_preset_hwid") is not None,
        cfg.get("paid_preset_traffic") is not None,
    ])


def _fmt_presets(cfg: dict, squad_names=None) -> str:
    trial = cfg.get("paid_trial_period")
    trial_str = fmt_duration(trial) if trial else "не задан"

    from handlers.payprovider import provider_line

    hwid = cfg.get("paid_preset_hwid", "не задан")
    traf_raw = cfg.get("paid_preset_traffic")
    if traf_raw is None:
        traf = "не задан"
    elif traf_raw == 0:
        traf = "безлимит"
    else:
        traf = f"{traf_raw} ГБ"

    # Доступ к серверам в Remnawave даёт сквад, а с истёкшими подписками
    # панель разбирается сама.
    names = squad_names or {}
    chosen = [names.get(u, u) for u in (cfg.get("rw_squads") or [])]
    panel_block = (
        "👥 <b>Сквады Remnawave</b>\n<blockquote>"
        + ("Выдаём: <b>{}</b>".format(_esc_name(", ".join(chosen)))
           if chosen else "Выдаём: <b>не выбраны</b>")
        + "</blockquote>"
    )
    return _presets_text(trial_str, provider_line(), hwid, traf, panel_block)


def _presets_text(trial_str, pay_line, hwid, traf, panel_block) -> str:
    """Общий вид экрана настроек: сроки, оплата, лимиты, доступ."""
    return (
        "⏱ <b>Сроки</b>\n<blockquote>"
        f"🆓 Пробный период: <b>{trial_str}</b>\n"
        "<i>Сроки платных периодов задают тарифы</i></blockquote>\n\n"
        "💳 <b>Оплата</b>\n<blockquote>"
        f"{pay_line}\n"
        "<i>Цену платного периода задают тарифы</i></blockquote>\n\n"
        "📊 <b>Лимиты</b>\n<blockquote>"
        f"🖥 Устройств: <b>{hwid}</b>\n"
        f"📶 Трафик: <b>{traf}</b></blockquote>\n\n"
        + panel_block
    )


# ── Список подписок ──────────────────────────────────────────────────────────

# Состояния клиентов в панели меняются редко, а список листают часто —
# держим ответ панели минуту, чтобы не дёргать её на каждой странице
_PANEL_STATES = {"at": 0.0, "states": {}, "ok": False}
STATES_TTL = 60


async def panel_states(force: bool = False) -> dict:
    import time
    from panel import get_client_states
    if not force and _PANEL_STATES["ok"] and time.time() - _PANEL_STATES["at"] < STATES_TTL:
        return _PANEL_STATES
    got = await get_client_states()
    if got.get("ok"):
        _PANEL_STATES.update(at=time.time(), states=got["states"], ok=True)
    else:
        _PANEL_STATES.update(ok=False, states={})
    return _PANEL_STATES


def _sub_mark(row, states: dict) -> str:
    """Значок подписки в списке: что с ней прямо сейчас."""
    from paidsub.storage import SOON_DAYS, parse_sub_date
    email, status = row[2], (row[6] if len(row) > 6 else "active")
    if states.get(email) == "DISABLED":
        return "⏸"
    if status == "expired":
        return "🔴"
    end = parse_sub_date(row[3])
    if end and (end - datetime.now()).total_seconds() <= SOON_DAYS * 86400:
        return "⏳"
    return "🟢"


async def handle_paid_subs_menu(query, page: int = 1, scope: str = "all", sort: str = "new"):
    """Список подписок с вкладками: активные, скоро, истёкшие, выключенные и прочие."""
    from paidsub.keyboards import PAID_TABS, SORT_LABELS
    from paidsub.storage import SUBS_PER_PAGE, all_paid_subs, list_paid_subs, paid_counts
    if scope not in PAID_TABS:
        scope = "all"
    if sort not in SORT_LABELS:
        sort = "new"

    counts = await paid_counts()
    panel = await panel_states()
    states = panel["states"]
    off_emails = {e for e, st in states.items() if st == "DISABLED"}

    if scope == "off":
        # выключенных знает только панель: фильтруем уже выбранные строки
        picked = [r for r in await all_paid_subs("all", sort) if r[2] in off_emails]
        total_pages = max(1, (len(picked) + SUBS_PER_PAGE - 1) // SUBS_PER_PAGE)
        page = min(max(1, page), total_pages)
        rows = picked[(page - 1) * SUBS_PER_PAGE:page * SUBS_PER_PAGE]
        counts["off"] = len(picked)
    else:
        rows, total_pages = await list_paid_subs(page, scope, sort)
        page = min(max(1, page), total_pages)
        counts["off"] = (sum(1 for r in await all_paid_subs("all", "new") if r[2] in off_emails)
                         if panel["ok"] else None)

    marks = {r[0]: _sub_mark(r, states) for r in rows}
    cfg = load_config()
    ready = _paid_presets_ready(cfg)
    icon, label = PAID_TABS[scope]

    lines = ["💳 <b>Платные подписки</b>", "",
             "<blockquote>🟢 работает · ⏳ скоро кончится · 🔴 истекла · ⏸ выключена в панели\n"
             "🆓 пробные · ⭐ платящие · 📋 все</blockquote>",
             f"\n{icon} <b>{label}</b> · сортировка: <b>{SORT_LABELS[sort]}</b> · "
             f"стр. {page} из {total_pages}"]
    lines.append("<blockquote>Здесь пусто.</blockquote>" if not rows
                 else "<i>Нажми на подписку, чтобы открыть.</i>")
    if not panel["ok"]:
        lines.append("\n⚠️ <i>Панель не ответила — не знаю, кто выключен.</i>")
    if not ready:
        lines.append("\n⚠️ <i>Задай настройки, чтобы создавать подписки.</i>")

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=paid_subs_list_keyboard(rows, page, total_pages, ready,
                                             scope, sort, counts, marks),
    )


# ── Настройки ─────────────────────────────────────────────────────────────────

async def handle_paid_presets_menu(query):
    cfg = load_config()
    squad_names = {}
    if cfg.get("rw_squads"):
        import remnawave as rw
        got = await rw.list_squads()
        if got.get("ok"):
            for sq in got["squads"]:
                squad_names[sq["uuid"]] = sq["name"]
    await query.edit_message_text(
        "⚙️ <b>Настройки подписок</b>\n\n"
        + _fmt_presets(cfg, squad_names)
        + "\n\n<i>Применяются только к новым подпискам. У выданных условия "
          "зафиксированы при создании — меняются в самой подписке.</i>",
        parse_mode="HTML",
        reply_markup=paid_presets_keyboard(),
    )


_TIME_HINT = (
    "<blockquote>Время — в свободной форме:\n"
    "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, "
    "<code>44 минуты</code>, <code>3 месяца</code></blockquote>"
)


async def handle_paid_preset_trial(query, context):
    from states import AWAITING_PAID_TRIAL_PERIOD
    context.user_data["state"] = AWAITING_PAID_TRIAL_PERIOD
    cfg = load_config()
    current = cfg.get("paid_trial_period")
    cur_str = fmt_duration(current) if current else "не задан"
    await query.edit_message_text(
        f"🆓 <b>Пробный период</b>\n\n<blockquote>Сейчас: <b>{cur_str}</b></blockquote>\n\n{_TIME_HINT}",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )










async def handle_paid_preset_hwid(query, context):
    from states import AWAITING_PAID_PRESET_HWID
    context.user_data["state"] = AWAITING_PAID_PRESET_HWID
    await query.edit_message_text(
        "🖥 <b>Лимит HWID</b>\n\n<i>Пришли число (0 = безлимит).</i>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_traffic(query, context):
    from states import AWAITING_PAID_PRESET_TRAFFIC
    context.user_data["state"] = AWAITING_PAID_PRESET_TRAFFIC
    await query.edit_message_text(
        "📶 <b>Трафик (ГБ)</b>\n\n<i>Пришли число в ГБ или <code>-</code> для безлимита.</i>",
        parse_mode="HTML",
        reply_markup=back_admin(),
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
    context.user_data.pop("state", None)
    context.user_data.pop("create_trial", None)

    trial_period = cfg.get("paid_trial_period", 86400)
    from database import list_tariffs
    tariffs = await list_tariffs(only_active=True)

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = [[InlineKeyboardButton(f"🆓 Пробный · {fmt_duration(trial_period)}",
                                callback_data="paid_create_type:trial")]]
    for t_id, name, period, price, _a, _s in tariffs:
        kb.append([InlineKeyboardButton(
            f"💳 {name} · {fmt_duration(period)}",
            callback_data=f"paid_create_type:{t_id}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="paid_subs")])

    await query.edit_message_text(
        "➕ <b>Создание подписки</b>\n\n"
        "<blockquote>🆓 <b>Пробная</b> — дальше обычный сценарий: "
        "напоминания, оплата, продление.\n"
        "💳 <b>По тарифу</b> — сразу засчитывается как оплаченный "
        "период на срок тарифа.</blockquote>\n\n"
        + ("<i>Выбери, что выдать.</i>" if tariffs else
           "⚠️ <i>Тарифов нет — можно выдать только пробную. "
           "Тарифы добавляются в «🏷 Тарифы».</i>"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_paid_create_type(query, context, kind: str):
    """Админ выбрал, что выдать: пробную или конкретный тариф."""
    from states import AWAITING_PAID_SUB_TG_ID
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cfg = load_config()
    context.user_data["state"] = AWAITING_PAID_SUB_TG_ID

    if kind == "trial":
        context.user_data["create_trial"] = True
        context.user_data.pop("create_period", None)
        label = "🆓 <b>Пробная подписка</b>"
        period = fmt_duration(cfg.get("paid_trial_period", 86400))
    else:
        from database import get_tariff
        tariff = await get_tariff(int(kind))
        if not tariff:
            await query.answer("Тариф не найден", show_alert=True)
            return
        context.user_data["create_trial"] = False
        context.user_data["create_period"] = int(tariff[2])
        label = f"💳 <b>{_esc_name(tariff[1])}</b>"
        period = fmt_duration(int(tariff[2]))

    await query.edit_message_text(
        f"{label} · <b>{period}</b>\n\n"
        "👤 Введи Telegram ID пользователя (числом):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="paid_create_sub")],
        ]),
    )


async def do_create_paid_sub(query_or_msg, tg_id: int, context, reply_func,
                             trial: bool = False, for_user: bool = False,
                             period_override: int | None = None):
    """Создаёт платную подписку. trial=True — пробный период."""
    cfg = load_config()
    await reply_func("⏳ Создаю подписку…")

    from panel import create_client, build_email
    from database import get_user_info
    user_row = await get_user_info(tg_id)
    username = user_row[2] if user_row else None
    email = build_email(tg_id, username, prefix="paid_")

    # срок платной подписки приходит из тарифа, пробной — из настроек
    if trial:
        period_seconds = int(cfg.get("paid_trial_period", 86400))
    else:
        period_seconds = int(period_override or cfg.get("paid_trial_period", 86400))

    period_end_dt = datetime.now() + timedelta(seconds=period_seconds)
    expire_date = period_end_dt.strftime("%d.%m.%Y %H:%M:%S")
    period_end_str = expire_date

    result = await create_client(
        expire_date=expire_date,
        limit_ip=0,
        limit_hwid=int(cfg.get("paid_preset_hwid", 0)),
        total_gb=int(cfg.get("paid_preset_traffic", 0)),
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

    new_sub_id = await add_paid_sub(
        tg_id=tg_id,
        email=result["email"],
        uuid_val=result["uuid"],
        sub_id=result["sub_id"],
        sub_url=result["sub_url"],
        expire_date=result["expire"],
        limit_ip=0,
        limit_hwid=int(cfg.get("paid_preset_hwid", 0)),
        total_gb=int(cfg.get("paid_preset_traffic", 0)),
    )

    # Фиксируем действующие условия за подпиской: последующая правка общих
    # настроек не должна менять условия уже выданной подписки
    from paidsub.storage import snapshot_sub_settings
    await snapshot_sub_settings(new_sub_id)
    await update_paid_sub_field(new_sub_id, "period_end", period_end_str)

    if not trial:
        await update_paid_sub_field(new_sub_id, "times_renewed", 1)

    traffic_str = f"{cfg.get('paid_preset_traffic', 0)} ГБ" if int(cfg.get("paid_preset_traffic", 0)) > 0 else "безлимит"
    period_label = "пробный период" if trial else "оплаченный период"

    await add_history(
        tg_id, "sub_created",
        f"Подписка #{new_sub_id} ({period_label})\nEmail: {result['email']}\nДо: {result['expire']}",
    )

    user_text = (
        "🎉 <b>Подписка готова!</b>\n\n"
        f"<blockquote>📅 Действует до: <b>{result['expire'][:16]}</b></blockquote>\n\n"
        "🔑 <b>Ссылка для подключения</b>\n"
        f"<code>{result['sub_url']}</code>\n\n"
        "<i>Нажмите на ссылку — она скопируется — и вставьте её в INCY.</i>"
    )

    if for_user:
        # экран открыт у самого клиента (авто-триал): служебные поля вроде
        # TG ID и email ему не нужны, и второе уведомление было бы дублем
        await reply_func(user_text, parse_mode="HTML")
        return

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
        await _notify_user(bot, tg_id, user_text)


# ── Запрос на одобрение подписки (от юзера) ──────────────────────────────────

async def handle_request_sub(query, context):
    """Юзер нажал '👤 Моя подписка' и у него нет подписки — отправляем запрос админу."""
    user = query.from_user
    cfg = load_config()
    if not _paid_presets_ready(cfg):
        await query.edit_message_text(
            "⚙️ <b>Моя подписка</b>\n\n"
            "<blockquote>Оформление подписок временно недоступно.</blockquote>\n\n"
            "<i>Загляните чуть позже.</i>",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return

    pending = await get_pending_request(user.id)
    if pending:
        await query.edit_message_text(
            "⚙️ <b>Моя подписка</b>\n\n"
            "<blockquote>⏳ Запрос уже у нас — пришлём уведомление, как только одобрим.</blockquote>",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return

    # Мгновенный триал без одобрения
    cfg_auto = load_config()
    if cfg_auto.get("auto_approve_trial", False):
        existing = await get_paid_sub_by_tg_id(user.id)
        if not existing:
            await add_request(user.id)
            await resolve_request(user.id, "approved")
            await add_history(user.id, "trial_approved", "Авто-одобрение")

            async def _edit(txt, **kw):
                await query.edit_message_text(txt, **kw)

            await do_create_paid_sub(query, user.id, context, _edit, trial=True, for_user=True)
            await _process_referral_bonus(user.id, context)
            from html import escape
            from log_channel import send_log
            uname_a = escape(f"@{user.username}" if user.username else f"id{user.id}")
            await send_log(context.bot,
                f"⚡ Авто-триал выдан: {escape(str(user.first_name or user.id))} "
                f"({uname_a}) · <code>{user.id}</code>"
            )
            return

    await add_request(user.id)

    uname = f"@{user.username}" if user.username else f"id{user.id}"
    trial_sec = cfg.get("paid_trial_period", 86400)
    hwid = cfg.get("paid_preset_hwid", 0)
    traf_raw = cfg.get("paid_preset_traffic", 0)
    traf_str = f"{traf_raw} ГБ" if traf_raw > 0 else "безлимит"
    hwid_str = str(hwid) if hwid > 0 else "безлимит"

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🆕 <b>Запрос на подписку</b>\n\n"
            f'👤 <a href="tg://user?id={user.id}">{_esc_name(user.first_name, user.id)}</a> '
            f"({_esc_name(uname, user.id)})\n"
            f"🆔 TG ID: <code>{user.id}</code>\n\n"
            f"<b>Параметры подписки:</b>\n"
            f"🆓 Пробный период: <b>{fmt_duration(trial_sec)}</b>\n"
            f"🖥 Лимит устройств: <b>{hwid_str}</b>\n"
            f"📶 Трафик: <b>{traf_str}</b>\n\n"
            "Одобрить пробную подписку?"
        ),
        parse_mode="HTML",
        reply_markup=approve_keyboard(user.id),
    )

    await query.edit_message_text(
        "📨 <b>Запрос отправлен</b>\n\n"
        "<blockquote>Пришлём уведомление сюда, как только одобрим.</blockquote>",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def _process_referral_bonus(invited_tg_id: int, context):
    """Начисляет бонус рефереру и приглашённому, если настроено."""
    cfg = load_config()
    bonus_seconds = cfg.get("referral_bonus")
    invited_bonus = cfg.get("referral_invited_bonus")
    referrer_id = await get_referrer(invited_tg_id)

    if not referrer_id:
        return
    if not bonus_seconds and not invited_bonus:
        return

    from panel import update_client_expire
    bot = context.bot if hasattr(context, 'bot') else None

    # ── Бонус рефереру ──────────────────────────────────────────────────────
    if bonus_seconds:
        referrer_sub = await get_paid_sub_by_tg_id(referrer_id)
        if referrer_sub:
            ref_status = referrer_sub[11] if len(referrer_sub) > 11 else "active"
            if ref_status in ("active", "renewal"):
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

                await set_expire_date(ref_sub_id, new_expire_str)
                ref_panel = await update_client_expire(ref_email, new_expire_str)
                if not ref_panel.get("success"):
                    from log_channel import send_log as _log
                    await _log(context.bot,
                        f"⚠️ Бонус за друга: срок не применился в панели у "
                        f"<code>{ref_email}</code> — {ref_panel.get('error', '?')}")

                await add_history(
                    referrer_id, "referral_bonus",
                    f"За приглашение <code>{invited_tg_id}</code>\n"
                    f"Начислено: {fmt_duration(bonus_seconds)}\nДо: {new_expire_str}",
                )

                if bot:
                    await _notify_user(bot, referrer_id,
                        f"🎁 <b>Бонус за друга!</b>\n\n"
                        f"Ваш друг активировал подписку — спасибо, что рассказали о нас.\n\n"
                        f"<blockquote>➕ Начислено: <b>{fmt_duration(bonus_seconds)}</b>\n"
                        f"📅 Подписка до: <b>{new_expire_str[:16]}</b></blockquote>"
                    )

    await mark_referral_rewarded(invited_tg_id, bonus_seconds or 0)

    # ── Бонус приглашённому ─────────────────────────────────────────────────
    if invited_bonus:
        invited_sub = await get_paid_sub_by_tg_id(invited_tg_id)
        if invited_sub:
            inv_status = invited_sub[11] if len(invited_sub) > 11 else "active"
            if inv_status in ("active", "renewal"):
                inv_sub_id = invited_sub[0]
                inv_email = invited_sub[2]
                inv_expire = invited_sub[6]

                for fmt_e in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                    try:
                        expire_dt = datetime.strptime(inv_expire, fmt_e)
                        break
                    except ValueError:
                        continue
                else:
                    expire_dt = datetime.now()
                if expire_dt < datetime.now():
                    expire_dt = datetime.now()

                new_inv_expire = expire_dt + timedelta(seconds=invited_bonus)
                new_inv_str = new_inv_expire.strftime("%d.%m.%Y %H:%M:%S")

                await set_expire_date(inv_sub_id, new_inv_str)
                inv_panel = await update_client_expire(inv_email, new_inv_str)
                if not inv_panel.get("success"):
                    from log_channel import send_log as _log
                    await _log(context.bot,
                        f"⚠️ Приветственный бонус: срок не применился в панели у "
                        f"<code>{inv_email}</code> — {inv_panel.get('error', '?')}")

                await add_history(
                    invited_tg_id, "referral_invited_bonus",
                    f"Бонус за регистрацию по реферальной ссылке\n"
                    f"Начислено: {fmt_duration(invited_bonus)}\nДо: {new_inv_str}",
                )

                if bot:
                    await _notify_user(bot, invited_tg_id,
                        f"🎁 <b>Приветственный бонус!</b>\n\n"
                        f"Вы пришли по приглашению друга — держите подарок.\n\n"
                        f"<blockquote>➕ Начислено: <b>{fmt_duration(invited_bonus)}</b>\n"
                        f"📅 Подписка до: <b>{new_inv_str[:16]}</b></blockquote>"
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

    from log_channel import send_log
    from database import get_user_info
    u = await get_user_info(tg_id)
    u_name = _esc_name(u[1] if u else None, tg_id)
    await send_log(context.bot, f"✅ Триал одобрен: {u_name} (<code>{tg_id}</code>)")

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
        "😕 <b>Запрос на подписку отклонён</b>\n\n"
        "<i>Если это ошибка — напишите в поддержку, разберёмся.</i>"
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
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, _limit_ip, limit_hwid, total_gb, created_at = row[:11]
    status = row[11] if len(row) > 11 else "active"
    ind_trial = row[13] if len(row) > 13 else None

    traffic_limit = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    from panel import get_client_traffic, get_client_info
    t = await get_client_traffic(email)
    if t["success"]:
        up = t.get("up", 0)
        down = t.get("down", 0)
        total_used = up + down
        traffic_line = (f"📶 Трафик: <b>{_fmt_bytes(total_used)}</b> из {traffic_limit}  "
                        f"(⬆ {_fmt_bytes(up)} · ⬇ {_fmt_bytes(down)})")
    else:
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b>"

    info = await get_client_info(email)
    enabled = info.get("enabled", True) if info.get("success") else True
    status_icon = "🟢" if enabled else "🔴"

    # Статус подписки
    status_labels = {"active": "активна", "expired": "истекла"}
    status_label = status_labels.get(status, status)

    payment_line = ""

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

    # имя человек задаёт сам — без экранирования «<» в имени ломает карточку
    shown = _esc_name(first_name, tg_id)
    if tg_id and uname:
        tg_line = (f'👤 <a href="tg://user?id={tg_id}">{shown}</a>  ·  '
                   f'<a href="https://t.me/{uname}">@{_esc_name(uname)}</a>')
    elif tg_id:
        tg_line = f'👤 <a href="tg://user?id={tg_id}">{shown}</a>'
    else:
        tg_line = ""

    if tg_id:
        tg_line += f"  ·  <code>{tg_id}</code>\n"

    # Индивидуальные настройки
    ind_lines = []
    # период оплаты, сумму и окно продления задают тарифы — в подписке
    # их больше не переопределяем, своим остался только пробный период
    if ind_trial:
        ind_lines.append(f"🆓 Пробный: <b>{fmt_duration(ind_trial)}</b>")
    ind_block = ""
    if ind_lines:
        ind_block = ("\n⚙️ <b>Свои условия</b>\n<blockquote>"
                     + "\n".join(ind_lines) + "</blockquote>\n")

    # Реферал
    referral_line = ""
    if tg_id:
        referrer_id = await get_referrer(tg_id)
        if referrer_id:
            ref_info = await get_user_info(referrer_id)
            ref_name = ref_info[1] if ref_info else str(referrer_id)
            referral_line = (f"👥 Пришёл от: <b>{_esc_name(ref_name, referrer_id)}</b> "
                             f"(<code>{referrer_id}</code>)\n")

    # Оставшееся время: период и доступ кончаются в один момент — окна нет
    from paidsub.storage import parse_sub_date
    now_dt = datetime.now()
    expire_dt = parse_sub_date(expire)
    period_label = "Пробный период" if times_renewed == 0 else "Оплаченный период"

    if expire_dt and now_dt < expire_dt:
        left = int((expire_dt - now_dt).total_seconds())
        time_left_line = (f"📅 {period_label} до: <b>{expire}</b>\n"
                          f"⏱ Осталось: <b>{fmt_duration_precise(left)}</b>\n")
    else:
        time_left_line = f"📅 До: <b>{expire}</b>\n⏱ <b>Истекла</b>\n"

    extra_lines = referral_line.strip()
    await query.edit_message_text(
        f"📄 <b>Подписка #{sub_id}</b>  {status_icon}\n"
        + tg_line
        + "\n📌 <b>Срок</b>\n<blockquote>"
        f"Статус: <b>{status_label}</b>  ·  {sub_type} (продлений: {times_renewed})\n"
        + payment_line
        + time_left_line.rstrip("\n")
        + "</blockquote>\n\n"
        "📊 <b>Лимиты</b>\n<blockquote>"
        f"🖥 Устройств: <b>{limit_hwid or 'без ограничения'}</b>\n"
        f"{traffic_line}\n"
        f"🕐 Создана: {created_at}"
        "</blockquote>\n"
        + (f"\n{extra_lines}\n" if extra_lines else "")
        + ind_block
        + "\n🔧 <b>Технические данные</b>\n<blockquote expandable>"
        f"📧 Email: <code>{email}</code>\n"
        f"🆔 UUID: <code>{uuid_val}</code>\n"
        f"📋 Sub ID: <code>{sub_id_str}</code>"
        "</blockquote>\n\n"
        f"🔗 <b>Ссылка</b>\n<code>{sub_url}</code>",
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
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return

    if context and tg_id:
        if new_state:
            note = "✅ <b>Подписка снова включена</b>\n\n<i>VPN работает — можно подключаться.</i>"
        else:
            note = ("⏸ <b>Подписка приостановлена</b>\n\n"
                    "<i>Вопросы — в поддержку, ответим в боте.</i>")
        await _notify_user(context.bot, tg_id, note)

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
        from panel import delete_client
        await query.edit_message_text("⏳ Удаляю из панели...")
        panel_result = await delete_client(email)
        panel_status = "✅ удалена из панели" if panel_result["success"] else f"⚠️ панель: {panel_result.get('error', '?')}"
    else:
        panel_status = "⚠️ email не найден, из панели не удалено"

    await delete_paid_sub(sub_id)

    if tg_id:
        await add_history(tg_id, "sub_deleted", f"Подписка #{sub_id} ({email}) · {panel_status}")

    if context and tg_id:
        await _notify_user(context.bot, tg_id,
            "🗑 <b>Подписка удалена</b>\n\n"
            "<i>Чтобы оформить новую, откройте /start.</i>")

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
    from panel import get_client_info, toggle_client
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
            "❄️ <b>Подписка заморожена</b>\n\n"
            "<blockquote>Срок на паузе — оставшиеся дни никуда не денутся.</blockquote>"
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
        "<blockquote>Время — в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code></blockquote>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_sub_reduce(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_REDUCE
    context.user_data["state"] = AWAITING_PAID_SUB_REDUCE
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"➖ <b>Убавить срок у подписки #{sub_id}</b>\n\n"
        "<blockquote>Время — в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code></blockquote>",
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
        f"<blockquote>Всего платных подписок: <b>{total}</b></blockquote>\n\n"
        "⚠️ <i>Действие применится ко <b>всем</b> платным подпискам сразу.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить срок", callback_data="paid_bulk_extend"),
             InlineKeyboardButton("➖ Убавить срок", callback_data="paid_bulk_reduce")],
            [InlineKeyboardButton("🔑 Лимит устройств всем", callback_data="paid_bulk_hwid")],
            [InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")],
        ]),
    )


async def handle_paid_bulk_extend(query, context):
    from states import AWAITING_PAID_BULK_EXTEND
    context.user_data["state"] = AWAITING_PAID_BULK_EXTEND
    await query.edit_message_text(
        "➕ <b>Добавить срок всем подпискам</b>\n\n"
        "<blockquote>Время — в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code></blockquote>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_bulk_reduce(query, context):
    from states import AWAITING_PAID_BULK_REDUCE
    context.user_data["state"] = AWAITING_PAID_BULK_REDUCE
    await query.edit_message_text(
        "➖ <b>Убавить срок всем подпискам</b>\n\n"
        "<blockquote>Время — в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code></blockquote>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_bulk_apply(query, context):
    """Массовый сдвиг срока — только после «Да» на вопросе с числом подписок."""
    pending = context.user_data.pop("bulk_pending", None)
    if not pending:
        # уже применено или бот перезапускался — вводить срок заново
        await handle_paid_bulk_menu(query)
        return
    seconds, direction = int(pending["seconds"]), int(pending["direction"])
    await query.edit_message_text("⏳ Применяю ко всем подпискам...")
    result = await bulk_shift_expire(seconds, direction, context)
    action = "добавлен" if direction > 0 else "убавлен"
    await query.edit_message_text(
        f"✅ <b>Массовое действие завершено</b>\n\n"
        f"Срок {action} на <b>{fmt_duration(seconds)}</b>\n"
        f"📊 Обработано: <b>{result['updated']}/{result['total']}</b>\n"
        + (f"⛔ Пропущено — в чёрном списке: <b>{result['skipped']}</b>\n" if result.get("skipped") else "")
        + (f"❌ Ошибок: <b>{result['errors']}</b>" if result['errors'] else ""),
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def apply_devices_payment(tg_id: int, count: int, context, amount: int = 0,
                                mode: str = "add") -> dict:
    """Начисляет оплаченные слоты устройств: в базе, в панели и человеку в чат.

    mode="add" — докуп среди периода: слоты прибавляются к уже оплаченным.
    mode="set" — выбор при продлении: слотов становится ровно столько, сколько
    человек взял на новый период. Ноль возвращает лимит к своему значению
    подписки, и платить за устройства больше не нужно.
    """
    from panel import update_client_limits
    from paidsub.storage import base_hwid
    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "подписка не найдена"}
    sub_id, email = row[0], row[2]
    extra_was = int(row[18] if len(row) > 18 and row[18] else 0)
    base = base_hwid(row[8], extra_was)
    count = int(count or 0)

    if mode == "set":
        extra_now = max(0, count)
        if extra_now == extra_was:
            return {"ok": True, "limit": int(row[8] or 0), "changed": False}
    else:
        if base <= 0:
            # лимита нет — докупать нечего, но деньги уже пришли
            return {"ok": False, "error": "у подписки нет лимита устройств"}
        extra_now = extra_was + max(1, count)

    if base <= 0:
        # лимит без ограничения: слоты не к чему прибавлять, но и терять нечего
        await update_paid_sub_field(sub_id, "extra_devices", extra_now)
        return {"ok": True, "limit": 0, "changed": False}

    new_limit = base + extra_now
    await update_paid_sub_field(sub_id, "limit_hwid", new_limit)
    await update_paid_sub_field(sub_id, "extra_devices", extra_now)
    res = await update_client_limits(email, limit_hwid=new_limit)
    note = "" if res.get("success") else f" (панель: {res.get('error', '?')})"

    added = extra_now - extra_was
    if added > 0:
        action = f"Оплачено устройств: +{added} → лимит {new_limit}"
    else:
        action = f"Отказ от устройств: {extra_was} → {extra_now}, лимит {new_limit}"
    await add_history(tg_id, "devices_bought",
                      action + (f"\nСумма: {amount} ₽" if amount else "") + note)

    bot = context.bot if hasattr(context, "bot") else None
    if bot and added > 0:
        await _notify_user(bot, tg_id,
            "✅ <b>Устройства добавлены</b>\n\n"
            f"<blockquote>📱 Теперь можно подключить: <b>{new_limit}</b></blockquote>"
        )
    elif bot and added < 0:
        await _notify_user(bot, tg_id,
            "📱 <b>Дополнительные устройства отключены</b>\n\n"
            f"<blockquote>Теперь можно подключить: <b>{new_limit}</b></blockquote>"
        )
    return {"ok": True, "limit": new_limit, "changed": True,
            "panel": res.get("success", False)}


def _when(value) -> str:
    """Время из панели: строка с датой, реже — число секунд или миллисекунд."""
    if value in (None, "", 0, "0"):
        return "—"
    try:
        num = int(float(value))
        if num <= 0:
            return "—"
        if num > 10 ** 12:          # миллисекунды это или секунды — видно по числу
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


async def handle_paid_devices(query, sub_id: int):
    """Устройства (HWID), которые панель запомнила по этой подписке."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from panel import get_client_hwids
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    email, limit_hwid = row[2], row[8]
    await query.edit_message_text("📱 Спрашиваю панель…")
    r = await get_client_hwids(email)

    lines = [f"📱 <b>Устройства подписки #{sub_id}</b>\n",
             f"🔑 Лимит HWID: <b>{limit_hwid or 'без ограничения'}</b>"]
    kb = []
    if not r.get("ok"):
        lines.append(f"\n❌ Панель не ответила:\n<code>{escape(str(r.get('error')))}</code>")
    else:
        items = r["items"]
        lines.append(f"📦 Запомнено устройств: <b>{len(items)}</b>\n")
        if not items:
            lines.append("<i>Пока ни одного — клиент ещё не подключался "
                         "или панель не считает HWID.</i>")
        for i, d in enumerate(items[:12], 1):
            name = " · ".join(str(x) for x in (d.get("deviceOs"), d.get("osVersion"),
                                               d.get("deviceModel")) if x) or "устройство"
            # приложение видно по User-Agent — админу это первое, что нужно знать
            app = str(d.get("userAgent") or "").split()[0] if d.get("userAgent") else ""
            app_line = f" · 📲 {escape(app)}" if app else ""
            lines.append(f"{i}. {escape(name)}{app_line}\n"
                         f"     был: {_when(d.get('lastSeen'))} · с {_when(d.get('firstSeen'))}")
            kb.append([InlineKeyboardButton(
                f"🗑 Убрать {i} — {name[:24]}",
                callback_data=f"paid_hwid_del:{sub_id}:{str(d.get('id'))[:20]}")])
        if len(items) > 12:
            lines.append(f"…и ещё {len(items) - 12}")
        if items:
            kb.append([InlineKeyboardButton("🧹 Очистить все устройства",
                                            callback_data=f"paid_hwid_clear:{sub_id}")])
    kb.append([InlineKeyboardButton("🌐 IP-адреса", callback_data=f"paid_ips:{sub_id}"),
               InlineKeyboardButton("🔄 Обновить", callback_data=f"paid_devices:{sub_id}")])
    kb.append([InlineKeyboardButton("◀️ К подписке", callback_data=f"paid_sub_view:{sub_id}")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_paid_ips(query, sub_id: int):
    """С каких адресов подключалась подписка."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from panel import get_client_ips
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    email = row[2]
    await query.edit_message_text("🌐 Спрашиваю панель…")
    r = await get_client_ips(email)

    lines = [f"🌐 <b>IP-адреса подписки #{sub_id}</b>\n"]
    kb = []
    if not r.get("ok"):
        lines.append(f"\n❌ Панель не ответила:\n<code>{escape(str(r.get('error')))}</code>")
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
    # адрес — часть записи об устройстве, отдельного журнала адресов в панели нет
    lines.append("\n<i>Адреса панель держит вместе с устройствами: "
                 "чтобы забыть адрес, убери устройство.</i>")
    kb.append([InlineKeyboardButton("📱 Устройства", callback_data=f"paid_devices:{sub_id}"),
               InlineKeyboardButton("🔄 Обновить", callback_data=f"paid_ips:{sub_id}")])
    kb.append([InlineKeyboardButton("◀️ К подписке", callback_data=f"paid_sub_view:{sub_id}")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_paid_hwid_del(query, context, sub_id: int, ref: str):
    from panel import delete_client_hwid, resolve_hwid
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    hwid_id = await resolve_hwid(row[2], ref)
    if hwid_id is None:
        await query.answer("Устройства уже нет в панели", show_alert=True)
        await handle_paid_devices(query, sub_id)
        return
    res = await delete_client_hwid(row[2], hwid_id)
    if res.get("success"):
        await query.answer("Устройство убрано")
        if row[1]:
            await add_history(row[1], "settings_changed", f"Убрано устройство #{hwid_id}")
    else:
        await query.answer(f"Панель не приняла: {res.get('error', '?')}"[:190], show_alert=True)
    await handle_paid_devices(query, sub_id)


async def handle_paid_hwid_clear(query, context, sub_id: int):
    from panel import clear_client_hwids
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    res = await clear_client_hwids(row[2])
    if res.get("success"):
        await query.answer("Устройства очищены")
        if row[1]:
            await add_history(row[1], "settings_changed", "Очищены все устройства (HWID)")
            await _notify_user(context.bot, row[1],
                "📱 <b>Список устройств сброшен</b>\n\n"
                "<i>Просто включите VPN на тех устройствах, которыми пользуетесь, — "
                "они добавятся заново.</i>"
            )
    else:
        await query.answer(f"Панель не приняла: {res.get('error', '?')}"[:190], show_alert=True)
    await handle_paid_devices(query, sub_id)


async def handle_paid_device_price(query, context):
    from states import AWAITING_DEVICE_PRICE
    context.user_data["state"] = AWAITING_DEVICE_PRICE
    cur = int(load_config().get("device_price") or 0)
    await query.edit_message_text(
        "📱 <b>Цена дополнительного устройства</b>\n\n"
        f"Сейчас: <b>{cur} ₽</b>{' — докуп выключен' if not cur else ''}\n\n"
        "Введи цену за одно устройство в рублях.\n"
        "<code>0</code> — убрать кнопку докупа у клиентов.",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_device_max(query, context):
    from states import AWAITING_DEVICE_MAX
    context.user_data["state"] = AWAITING_DEVICE_MAX
    cur = int(load_config().get("device_max_extra") or 5)
    await query.edit_message_text(
        "📱 <b>Максимум докупа</b>\n\n"
        f"Сейчас: <b>{cur}</b> устройств сверх тарифа\n\n"
        "Сколько слотов один человек может добрать?",
        parse_mode="HTML", reply_markup=back_admin(),
    )




async def handle_paid_bulk_hwid(query, context):
    from states import AWAITING_PAID_BULK_HWID
    context.user_data["state"] = AWAITING_PAID_BULK_HWID
    await query.edit_message_text(
        "🔑 <b>Лимит устройств (HWID) для всех подписок</b>\n\n"
        "Сколько устройств разрешить на подписку?\n"
        "Введи число, <code>0</code> — без ограничения.",
        parse_mode="HTML", reply_markup=back_admin(),
    )


# что именно правим оптом: подпись для экрана и колонка в базе
LIMIT_KINDS = {"hwid": ("🔑", "устройств", "limit_hwid")}


async def preview_bulk_limits(message, context, kind: str, value: int):
    """Показывает, кого затронет смена лимита, и спрашивает подтверждение."""
    import aiosqlite
    from blacklist import blacklisted_ids
    from database import DB_PATH
    from handlers.confirm import confirm_keyboard
    emoji, label, field = LIMIT_KINDS[kind]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT tg_id, {field}, extra_devices FROM paid_subs"
        ) as cur:
            rows = await cur.fetchall()
    skip = await blacklisted_ids()
    targets = [r for r in rows if r[0] not in skip]
    with_extra = sum(1 for _tg, _old, ex in targets if kind == "hwid" and ex)
    # 0 в лимите — это «без ограничения», поэтому переход с нуля тоже ужесточение
    def _target(ex):
        return value + int(ex or 0) if (kind == "hwid" and value) else value
    tighter = sum(1 for _tg, old, ex in targets
                  if _target(ex) and (not old or _target(ex) < old))
    context.user_data["bulk_limits"] = {"kind": kind, "value": value}
    await message.reply_text(
        f"{emoji} <b>Поставить лимит {label} = {value or 'без ограничения'} всем?</b>\n\n"
        f"👥 Затронет подписок: <b>{len(targets)}</b>"
        + (f" · пропустим из ЧС: {len(rows) - len(targets)}\n" if len(rows) != len(targets) else "\n")
        + (f"⚠️ У <b>{tighter}</b> лимит станет строже — им придёт уведомление.\n" if tighter else "")
        + (f"📱 У <b>{with_extra}</b> есть оплаченные устройства — им добавим сверх этого числа.\n"
           if with_extra else "")
        + "\nМеняем и в базе, и в панели. "
          "Пресет для новых подписок остаётся прежним.",
        parse_mode="HTML",
        reply_markup=confirm_keyboard("✅ Да, применить", "paid_bulk_limits_apply",
                                      "paid_bulk_menu", "paid_subs"),
    )


async def handle_paid_bulk_limits_apply(query, context):
    plan = context.user_data.pop("bulk_limits", None)
    if not plan:
        await handle_paid_bulk_menu(query)
        return
    kind, value = plan["kind"], plan["value"]
    emoji, label, _field = LIMIT_KINDS[kind]
    await query.edit_message_text(f"{emoji} Меняю лимит {label} у всех подписок…")
    r = await bulk_set_limits(kind, value, context)
    await query.edit_message_text(
        f"✅ <b>Готово</b>\n\n"
        f"{emoji} Лимит {label}: <b>{value or 'без ограничения'}</b>\n"
        f"📊 Обновлено подписок: <b>{r['updated']}</b>\n"
        + (f"⛔ Пропущено — в чёрном списке: <b>{r['skipped']}</b>\n" if r["skipped"] else "")
        + (f"⚠️ Панель не приняла: <b>{r['panel_fail']}</b>\n" if r["panel_fail"] else "")
        + (f"📨 Предупредили об ужесточении: <b>{r['tightened']}</b>" if r["tightened"] else ""),
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def bulk_set_limits(kind: str, value: int, context) -> dict:
    """Ставит лимит устройств всем платным подпискам: в базе и в панели."""
    import aiosqlite
    from blacklist import blacklisted_ids
    from database import DB_PATH
    from panel import update_client_limits
    emoji, label, field = LIMIT_KINDS[kind]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT id, tg_id, email, {field}, extra_devices FROM paid_subs"
        ) as cur:
            rows = await cur.fetchall()

    skip_ids = await blacklisted_ids()
    bot = context.bot if hasattr(context, "bot") else None
    updated = panel_fail = skipped = 0
    tightened = []
    for sub_id, tg_id, email, old, extra in rows:
        if tg_id in skip_ids:
            skipped += 1
            continue
        # человек оплатил дополнительные устройства — они идут сверх общего
        # лимита, иначе массовая правка молча отбирала бы купленное
        target = value + int(extra or 0) if (kind == "hwid" and value) else value
        await update_paid_sub_field(sub_id, field, target)
        res = await update_client_limits(
            email, limit_hwid=target)
        if not res.get("success"):
            panel_fail += 1
        updated += 1
        if tg_id:
            await add_history(tg_id, "settings_changed",
                              f"Массово: лимит {label} → {target or 'без ограничения'}"
                              + (f" (в т.ч. докуплено {extra})" if target != value else ""))
            # пишем только тем, кому стало строже: остальным это не новость.
            # old == 0 значит «было без ограничения» — любой лимит строже
            if target and (not old or target < old):
                tightened.append((tg_id, target))

    if bot:
        for tg_id, target in tightened:
            await _notify_user(bot, tg_id,
                f"📱 <b>Изменён лимит устройств</b>\n\n"
                f"<blockquote>Теперь можно подключить: <b>{target}</b></blockquote>\n\n"
                f"<i>Лишние устройства перестанут подключаться.</i>"
            )
    return {"updated": updated, "panel_fail": panel_fail,
            "skipped": skipped, "tightened": len(tightened)}


async def bulk_shift_expire(seconds: int, direction: int, context) -> dict:
    """Сдвигает дату окончания у всех платных подписок.
    direction = +1 (добавить) или -1 (убавить). Возвращает отчёт."""
    from panel import update_client_expire, get_client_info, toggle_client
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM paid_subs") as cur:
            all_ids = [r[0] for r in await cur.fetchall()]

    cfg = load_config()
    updated = 0
    errors = 0
    # подписки людей из ЧС не трогаем: добавление срока включило бы их обратно
    from blacklist import blacklisted_ids
    skip_ids = await blacklisted_ids()
    skipped = 0

    for sid in all_ids:
        row = await get_paid_sub(sid)
        if not row:
            continue
        email = row[2]
        tg_id = row[1]
        if tg_id in skip_ids:
            skipped += 1
            continue
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
            await set_expire_date(sid, new_expire_str)
            await update_client_expire(email, new_expire_str)
            if direction > 0:
                # при добавлении срока подписку возвращаем в строй
                await update_paid_sub_field(sid, "status", "active")
                info = await get_client_info(email)
                if info.get("success") and not info.get("enabled", True):
                    await toggle_client(email, True)
            updated += 1

            # уведомление пользователю
            if tg_id:
                bot = context.bot if hasattr(context, 'bot') else None
                if bot:
                    if direction > 0:
                        await _notify_user(bot, tg_id,
                            f"🎉 <b>Подписка продлена!</b>\n\n"
                            f"<blockquote>➕ Добавлено: <b>{fmt_duration(seconds)}</b>\n"
                            f"📅 Действует до: <b>{new_expire_str[:16]}</b></blockquote>"
                        )
                    else:
                        await _notify_user(bot, tg_id,
                            f"ℹ️ <b>Срок подписки изменён</b>\n\n"
                            f"<blockquote>➖ Убавлено: <b>{fmt_duration(seconds)}</b>\n"
                            f"📅 Действует до: <b>{new_expire_str[:16]}</b></blockquote>"
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

    return {"updated": updated, "errors": errors, "total": len(all_ids), "skipped": skipped}


# ── Индивидуальные настройки платной подписки ─────────────────────────────────

async def handle_paid_sub_settings(query, sub_id: int):
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    # row: id,tg_id,email,uuid,sub_id,sub_url,expire,ip,hwid,traffic,created,status,payment_pending,
    #       ind_trial,ind_pay_period,ind_renew,ind_price,ind_pay_url
    expire = row[6]
    limit_hwid = row[8]
    total_gb = row[9]

    traffic = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"
    hwid_str = str(limit_hwid) if limit_hwid > 0 else "безлимит"

    # показываем действующие условия подписки, а не «общие»:
    # с ними она реально живёт, по ним считаются сроки и уведомления
    from paidsub.storage import sub_settings
    eff = sub_settings(row)
    period_end_line = row[18] if len(row) > 18 and row[18] else expire
    trial_str = fmt_duration(eff["trial_period"])
    from handlers.payprovider import provider_label
    pay_line = f"💳 Оплата: <b>{provider_label()}</b> — счёт выставляет бот\n"

    await query.edit_message_text(
        f"⚙️ <b>Настройки подписки #{sub_id}</b>\n\n"
        f"📅 Действует до: <b>{period_end_line}</b>\n"
        f"🖥 Лимит устройств: <b>{hwid_str}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n"
        f"🆓 Пробный период: <b>{trial_str}</b>\n"
        f"{pay_line}\n"
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




async def handle_paid_sub_edit_hwid(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_HWID
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_HWID
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🖥 <b>Лимит HWID подписки #{sub_id}</b>\n\n<i>Пришли число (0 = безлимит).</i>",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_traffic(query, sub_id: int, context):
    from states import AWAITING_PAID_SUB_EDIT_TRAFFIC
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_TRAFFIC
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📶 <b>Трафик подписки #{sub_id}</b>\n\n<i>Пришли число ГБ или <code>-</code> для безлимита.</i>",
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










# ── Починка окна оплаты ──────────────────────────────────────────────────────







# ── Job: напоминания о скором конце ───────────────────────────────────────────

def in_quiet_hours(now, cfg) -> bool:
    """Ночью людей не будим. Окно задаётся часами: с 23 до 9, например."""
    start = cfg.get("remind_quiet_from")
    end = cfg.get("remind_quiet_to")
    if start is None or end is None:
        return False
    start, end = int(start), int(end)
    if start == end:
        return False
    hour = now.hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end          # окно через полночь


async def expiry_reminder_tick(context):
    """Пишет заранее, что срок подходит к концу.

    Раньше первое письмо человек получал уже после отключения — когда VPN
    перестал работать. Два срока: заранее и впритык. Отправленная стадия
    хранится в подписке, поэтому повторов нет, а продление её сбрасывает.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_subs_for_reminder, parse_sub_date
    from blacklist import blacklisted_ids
    cfg = load_config()
    if not cfg.get("remind_enabled", True):
        return
    stages = [int(cfg.get("remind_first", 3 * 86400) or 0),
              int(cfg.get("remind_second", 86400) or 0),
              int(cfg.get("remind_third", 0) or 0)]
    if not any(stages):
        return

    now = datetime.now()
    # тихие часы: ночью не пишем, отправим позже — джоб крутится каждые полчаса
    if in_quiet_hours(now, cfg):
        return

    rows = await get_subs_for_reminder()
    if not rows:
        return
    skip = await blacklisted_ids()
    remind_trials = cfg.get("remind_trials", True)

    for sub_id, tg_id, period_end_str, times_renewed, stage in rows:
        if not tg_id or tg_id in skip:
            continue
        if not times_renewed and not remind_trials:
            continue
        end = parse_sub_date(period_end_str)
        if not end:
            continue
        left = int((end - now).total_seconds())
        if left <= 0:
            continue
        # какая стадия подходит: считаем от самой поздней, чтобы при долгом
        # простое бота человек получил одно письмо, а не оба подряд
        target = 0
        for idx, window in enumerate(stages, start=1):
            if window and left <= window:
                target = idx
        if not target or target <= int(stage or 0):
            continue

        await update_paid_sub_field(sub_id, "remind_stage", target)
        trial = not times_renewed
        what = "Пробный период" if trial else "Подписка"
        action = "Оформить подписку" if trial else "Продлить подписку"
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=(
                    f"⏳ <b>{what} скоро закончится</b>\n\n"
                    f"<blockquote>Осталось: <b>{fmt_duration_precise(left)}</b></blockquote>\n\n"
                    "<i>Продлите сейчас — оставшиеся дни не сгорят, а прибавятся.</i>"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"💳 {action}", callback_data="renew_sub")]
                ]),
            )
            from database import log_activity
            await log_activity(tg_id, "ev:reminded", f"этап {target}")
        except Exception:
            pass


# ── Job: проверка истечения подписок ──────────────────────────────────────────

async def check_expired_subs(context):
    """Следит за сроками: меняет статусы и предупреждает людей.

    Окна оплаты нет: подписка работает до даты окончания, потом сразу
    истекает. Доступ в панели не выключаем — у клиента там тот же срок,
    и панель закрывает его сама, переводя в EXPIRED.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import parse_sub_date

    now = datetime.now()
    for row in await get_expired_paid_subs():
        (sub_id, tg_id, email, _uuid_val, _sub_id_str, _sub_url,
         expire_str, status, times_renewed, _ind_renew_time, _period_end) = row

        expire_dt = parse_sub_date(expire_str)
        if not expire_dt:
            continue

        if now < expire_dt:
            if status != "active":
                await update_paid_sub_field(sub_id, "status", "active")
            continue

        if status == "expired":
            continue

        # Срок вышел: помечаем истёкшей и один раз говорим об этом человеку
        await update_paid_sub_field(sub_id, "status", "expired")
        if tg_id:
            from database import log_activity
            await log_activity(tg_id, "ev:period_ended",
                               "триал" if times_renewed == 0 else "оплаченный")
            await log_activity(tg_id, "ev:expired")

        # Единственное, что делаем в панели, — ещё раз отдаём ей ту же дату
        # окончания. Запрос идемпотентный, зато если срок в панели когда-то
        # разъехался с базой (например, правили руками), он снова сойдётся.
        from panel import update_client_expire
        synced = await update_client_expire(email, expire_str)
        if not synced.get("success"):
            from log_channel import send_log as _send_log
            await _send_log(context.bot,
                f"⚠️ Срок в панели не сошёлся с базой: <code>{email}</code> — "
                f"{synced.get('error', '?')}\nПроверь, закрыт ли доступ.")

        if not tg_id:
            continue
        head = ("Пробный период закончился" if times_renewed == 0
                else "Подписка закончилась")
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=(f"🔴 <b>{head}</b>\n\n"
                      "<i>Продлите — VPN включится сразу после оплаты.</i>"),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")]
                ]),
            )
        except Exception:
            pass


async def revoke_paid_period(tg_id: int, period_seconds: int | None, context,
                             reason: str = "Возврат платежа") -> dict:
    """Отзывает оплаченный срок — обратная операция к начислению при оплате.

    Двигает дату окончания назад на оплаченный период, конец периода сдвигается
    вместе с ней. Если срок уходит в прошлое, обычная проверка сроков
    переведёт подписку в истёкшие.
    """
    if not period_seconds:
        return {"ok": False, "error": "у платежа нет сохранённого периода"}
    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "подписка не найдена"}

    from paidsub.storage import parse_sub_date
    sub_id, email, expire_str = row[0], row[2], row[6]
    expire_dt = parse_sub_date(expire_str)
    if not expire_dt:
        return {"ok": False, "error": f"не разобрал дату окончания: {expire_str}"}

    new_expire = expire_dt - timedelta(seconds=int(period_seconds))
    new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")
    await set_expire_date(sub_id, new_expire_str)

    # Деньги вернули — доступ должен закрыться, поэтому ответ панели проверяем,
    # а не выбрасываем: иначе бот отчитается новой датой, а человек продолжит
    # пользоваться VPN по старому сроку.
    from panel import update_client_expire, toggle_client
    panel_error = ""
    r = await update_client_expire(email, new_expire_str)
    if not r.get("success"):
        panel_error = str(r.get("error") or "панель не приняла новый срок")

    if new_expire <= datetime.now():
        # срок ушёл в прошлое: закрываем доступ сразу, не дожидаясь, пока
        # панель сама заметит дату — за возврат человек уже не платит
        off = await toggle_client(email, False)
        if not off.get("success"):
            panel_error = ((panel_error + "; ") if panel_error else "") + \
                str(off.get("error") or "не удалось отключить клиента")
        await update_paid_sub_field(sub_id, "status", "expired")

    await add_history(
        tg_id, "payment_refunded",
        f"{reason}\nОтозвано: {fmt_duration(int(period_seconds))}\nНовая дата: {new_expire_str}"
        + (f"\n⚠️ Панель: {panel_error}" if panel_error else ""),
    )
    return {"ok": True, "expire": new_expire_str, "panel_error": panel_error}


def _renew_base(full_row) -> tuple:
    """С какой точки отсчитывать оплаченный срок.

    Остаток не сгорает: если период ещё идёт (в том числе пробный), новый срок
    прибавляется к его концу. Кончился — считаем от «сейчас».
    Возвращает (точка отсчёта, сколько секунд остатка перенесли).
    """
    from paidsub.storage import parse_sub_date
    now = datetime.now()
    raw = full_row[18] if full_row is not None and len(full_row) > 18 else None
    if not raw:
        raw = full_row[6] if full_row is not None and len(full_row) > 6 else None
    end = parse_sub_date(raw) if raw else None
    if end and end > now:
        return end, int((end - now).total_seconds())
    return now, 0


async def apply_paid_payment(tg_id: int, amount: int, context,
                             promo_code: str | None = None,
                             source: str = "Platega",
                             period_seconds: int | None = None) -> dict:
    """Засчитывает оплату, пришедшую из платёжной системы.

    Делает то же, что ручное подтверждение админом, но без его участия:
    продлевает период, включает клиента, списывает промокод и уведомляет.

    period_seconds — срок из оплаченного тарифа. Он зафиксирован в счёте,
    поэтому правка тарифа после оплаты не меняет уже купленный срок.
    """
    # Человек из ЧС: деньги пришли, но срок не начисляем — иначе оплата по
    # счёту, выставленному до внесения в ЧС, включила бы подписку обратно
    from blacklist import is_blacklisted
    if await is_blacklisted(tg_id):
        return {"ok": False, "error": "пользователь в чёрном списке — срок не начислен: "
                                      "верни деньги или убери из ЧС"}

    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "подписка не найдена"}

    sub_id = row[0]
    email = row[2]

    full_row = await get_paid_sub(sub_id)
    cfg = load_config()
    from paidsub.storage import sub_settings
    settings = sub_settings(full_row)
    pay_seconds = int(period_seconds or settings["pay_period"] or 0)
    guessed = ""
    if not pay_seconds:
        # у платежа нет срока (старый счёт или сбой) — берём первый активный
        # тариф, чтобы деньги не повисли, и говорим об этом админу
        from database import list_tariffs
        tariffs = await list_tariffs(only_active=True)
        pay_seconds = int(tariffs[0][2]) if tariffs else 30 * 86400
        guessed = (f"⚠️ У платежа не было срока — начислил "
                   f"{fmt_duration(pay_seconds)} "
                   + ("по первому тарифу" if tariffs else "по умолчанию (30 дней)"))
    base, _carried = _renew_base(full_row)
    # окна оплаты нет: конец периода и конец доступа — одна и та же дата
    new_expire = base + timedelta(seconds=pay_seconds)
    new_expire_str = new_expire.strftime("%d.%m.%Y %H:%M:%S")

    await update_paid_sub_field(sub_id, "expire_date", new_expire_str)
    await update_paid_sub_field(sub_id, "period_end", new_expire_str)
    await update_paid_sub_field(sub_id, "status", "active")
    await update_paid_sub_field(sub_id, "payment_pending", 0)
    # срок сдвинулся — напоминания о скором конце начинают отсчёт заново
    await update_paid_sub_field(sub_id, "remind_stage", 0)
    cur_renewed = row[12] if len(row) > 12 else 0
    await update_paid_sub_field(sub_id, "times_renewed", cur_renewed + 1)

    from panel import get_client_info, toggle_client, update_client_expire
    info = await get_client_info(email)
    if info.get("success") and not info.get("enabled", True):
        await toggle_client(email, True)
    paid_panel = await update_client_expire(email, new_expire_str)
    if not paid_panel.get("success"):
        # оплата прошла, а срок в панели не сдвинулся — человек остался
        # без доступа, и знать об этом надо немедленно
        from log_channel import send_log as _log
        await _log(context.bot,
            f"🛑 Оплата зачтена, но панель не приняла новый срок: "
            f"<code>{email}</code> — {paid_panel.get('error', '?')}\n"
            f"Проставь срок <b>{new_expire_str}</b> в панели руками.")

    promo_line = ""
    pending_promo = promo_code or await get_pending_promo(tg_id)
    if pending_promo:
        promo = await get_promo(pending_promo)
        if promo and not await promo_used_by(pending_promo, tg_id):
            await record_promo_use(pending_promo, tg_id)
            await add_history(tg_id, "promo_used", f"Промокод {pending_promo} (−{promo[2]}%)")
            promo_line = f"🎟 Промокод: <b>{pending_promo}</b> (−{promo[2]}%)\n"
        await update_paid_sub_field(sub_id, "pending_promo", None)

    promo_note = f" (промокод {pending_promo})" if promo_line else ""
    await add_history(
        tg_id, "payment_confirmed",
        f"Сумма: {amount} ₽{promo_note}\nЧерез: {source}\nДо: {new_expire_str}",
    )

    from log_channel import send_log
    from database import get_user_info
    u = await get_user_info(tg_id)
    u_name = _esc_name(u[1] if u else None, tg_id)
    await send_log(context.bot,
        f"💰 Оплата через {source}: {u_name} (<code>{tg_id}</code>) — {amount} ₽\n"
        f"{promo_line}📅 До: {new_expire_str}"
        + (f"\n{guessed}" if guessed else "")
    )

    await _notify_user(context.bot, tg_id,
        "✅ <b>Оплата прошла — спасибо!</b>\n\n"
        f"<blockquote>➕ Добавлено: <b>{fmt_duration(pay_seconds)}</b>\n"
        f"📅 Подписка до: <b>{new_expire_str[:16]}</b></blockquote>"
    )

    from config import ADMIN_ID
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💰 <b>Оплата через {source}</b>\n\n"
                f"👤 {u_name} (<code>{tg_id}</code>)\n"
                f"💵 {amount} ₽\n"
                f"{promo_line}"
                f"📅 До: <b>{new_expire_str}</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    return {"ok": True, "expire": new_expire_str}






# ── Запросы ──────────────────────────────────────────────────────────────────

# ── Авто-обновление ников ────────────────────────────────────────────────────


# ── Реферальная система (админ) ──────────────────────────────────────────────

async def handle_referral_settings(query):
    cfg = load_config()
    bonus = cfg.get("referral_bonus")
    bonus_str = fmt_duration(bonus) if bonus else "не задан"
    invited_bonus = cfg.get("referral_invited_bonus")
    invited_str = fmt_duration(invited_bonus) if invited_bonus else "не задан"
    stats = await get_all_referral_stats()

    from database import get_user_info
    top_lines = []
    for ref_id, cnt in stats["top_referrers"]:
        u = await get_user_info(ref_id)
        name = _esc_name(u[1] if u else None, ref_id)
        uname = _esc_name(f"@{u[2]}" if u and u[2] else f"id{ref_id}")
        top_lines.append(f"{len(top_lines) + 1}. {name} ({uname}) — <b>{cnt}</b>")

    counts = [f"👤 Всего рефералов: <b>{stats['total']}</b>  ·  с бонусом: <b>{stats['rewarded']}</b>"]
    if stats['total_bonus'] > 0:
        counts.append(f"⏱ Всего начислено: <b>{fmt_duration(stats['total_bonus'])}</b>")
    lines = [
        "👥 <b>Реферальная система</b>", "",
        "🎁 <b>Бонусы</b>",
        f"<blockquote>Пригласившему: <b>{bonus_str}</b>\n"
        f"Приглашённому: <b>{invited_str}</b></blockquote>", "",
        "📊 <b>Статистика</b>",
        "<blockquote>" + "\n".join(counts) + "</blockquote>",
    ]
    if top_lines:
        lines += ["", "🏆 <b>Топ пригласивших</b>",
                  "<blockquote>" + "\n".join(top_lines) + "</blockquote>"]

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Пригласившему", callback_data="set_referral_bonus"),
         InlineKeyboardButton("🤝 Приглашённому", callback_data="set_referral_invited_bonus")],
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
        f"🎁 <b>Бонус пригласившему</b>\n\n"
        f"Сейчас: <b>{cur_str}</b>\n\n"
        "Введи время бонуса:\n"
        "<code>1 день</code>, <code>3 дня</code>, <code>12 часов</code>, <code>1 неделя</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_set_referral_invited_bonus(query, context):
    from states import AWAITING_REFERRAL_INVITED_BONUS
    context.user_data["state"] = AWAITING_REFERRAL_INVITED_BONUS
    cfg = load_config()
    bonus = cfg.get("referral_invited_bonus")
    cur_str = fmt_duration(bonus) if bonus else "не задан"
    await query.edit_message_text(
        f"🎁 <b>Бонус приглашённому</b>\n\n"
        f"Сейчас: <b>{cur_str}</b>\n\n"
        "Введи время бонуса для приглашённого друга:\n"
        "<code>1 день</code>, <code>3 дня</code>, <code>12 часов</code>, <code>1 неделя</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Промокоды ────────────────────────────────────────────────────────────────

def apply_discount(price: int, percent: int) -> int:
    return max(0, round(price * (100 - percent) / 100))


def _parse_date(s: str):
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


async def validate_promo(code: str, tg_id: int):
    """Возвращает (promo_row, None) или (None, текст_ошибки)."""
    promo = await get_promo(code)
    if not promo:
        return None, "❌ Промокод не найден."
    _id, code_u, percent, expires_at, active, _ = promo[:6]
    owner = promo[6] if len(promo) > 6 else None
    max_uses = promo[7] if len(promo) > 7 else 0
    if not active:
        return None, "❌ Промокод неактивен."
    if expires_at:
        exp = _parse_date(expires_at)
        if exp and datetime.now() > exp:
            return None, "❌ Срок действия промокода истёк."
    # личный код работает только у того, кому его выдали
    if owner and int(owner) != int(tg_id):
        return None, "❌ Этот промокод выдан другому пользователю."
    if await promo_used_by(code_u, tg_id):
        return None, "❌ Вы уже использовали этот промокод."
    if max_uses and await promo_use_count(code_u) >= int(max_uses):
        return None, "❌ Промокод уже разобрали — закончились активации."
    if len(promo) > 12 and promo[12]:
        row = await get_paid_sub_by_tg_id(tg_id)
        if row and (row[12] if len(row) > 12 else 0):
            return None, "❌ Этот промокод — только для тех, кто ещё не оплачивал подписку."
    return promo, None


async def handle_toggle_auto_trial(query):
    cfg = load_config()
    cfg["auto_approve_trial"] = not cfg.get("auto_approve_trial", False)
    save_config(cfg)
    await handle_paid_presets_menu(query)


def save_paid_preset(key: str, value):
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
