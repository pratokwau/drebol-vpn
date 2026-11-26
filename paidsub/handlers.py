from datetime import datetime, timedelta

from telegram import Bot

from config import ADMIN_ID, load_config, save_config
from core.keyboards import back_admin, back_main

from paidsub.storage import (
    get_paid_sub, get_paid_sub_by_tg_id,
    add_request, get_pending_request, resolve_request,
    update_paid_sub_field, get_expired_paid_subs, set_expire_date,
    add_history,
    get_referrer, mark_referral_rewarded, get_all_referral_stats,
    get_promo, promo_used_by, promo_use_count,
)
from paidsub.keyboards import (
    paid_subs_list_keyboard, paid_presets_keyboard, paid_sub_view_keyboard,
    approve_keyboard, paid_sub_settings_keyboard,
)
from paidsub import service as _svc
from paidsub.time_parser import fmt_duration, fmt_duration_precise


def _display_url(sub_url: str) -> str:
    """Показная форма ссылки подписки: домен выбирает настройка
    sub_link_domain (по умолчанию sub.drbl.tech), как у пользователя."""
    from handlers.user import primary_sub_url
    return primary_sub_url(sub_url)


def _both_urls(sub_url: str) -> tuple[str, str]:
    """Обе формы ссылки для админки: (sub.drbl.tech, key.drbl.tech)."""
    from config import (SUB_DISPLAY_DOMAIN, SUB_STORED_DOMAIN,
                        sub_url_with_domain)
    return (sub_url_with_domain(sub_url, SUB_DISPLAY_DOMAIN),
            sub_url_with_domain(sub_url, SUB_STORED_DOMAIN))


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
        "🗂 <b>Сквады Remnawave</b>\n<blockquote>"
        + ("Выдаём: <b>{}</b>".format(_esc_name(", ".join(chosen)))
           if chosen else "Выдаём: <b>не выбраны</b>")
        + "</blockquote>"
    )
    # LTE-настройки живут на экране «Сквады Remnawave»: здесь их не дублируем
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
    from services.panel import get_client_states
    if not force and _PANEL_STATES["ok"] and time.time() - _PANEL_STATES["at"] < STATES_TTL:
        return _PANEL_STATES
    got = await get_client_states()
    if got.get("ok"):
        _PANEL_STATES.update(at=time.time(), states=got["states"], ok=True)
    else:
        _PANEL_STATES.update(ok=False, states={})
    return _PANEL_STATES


def _sub_mark(row, states: dict, frozen_ids: set = None) -> str:
    """Значок подписки в списке: что с ней прямо сейчас."""
    from paidsub.storage import SOON_DAYS, parse_sub_date
    email, status = row[2], (row[6] if len(row) > 6 else "active")
    if frozen_ids and row[0] in frozen_ids:
        return "❄️"
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
    from paidsub.storage import (
        SUBS_PER_PAGE, all_paid_subs, list_paid_subs, paid_counts, paid_emails,
    )
    if scope not in PAID_TABS:
        scope = "all"
    if sort not in SORT_LABELS:
        sort = "new"

    counts = await paid_counts()
    from paidsub.storage import count_pending_requests
    counts["pending"] = await count_pending_requests()
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
        counts["off"] = (len(off_emails & await paid_emails()) if panel["ok"] else None)

    from paidsub.storage import frozen_paid_sub_ids
    frozen_ids = await frozen_paid_sub_ids()
    marks = {r[0]: _sub_mark(r, states, frozen_ids) for r in rows}
    cfg = load_config()
    ready = _paid_presets_ready(cfg)
    icon, label = PAID_TABS[scope]

    lines = ["💳 <b>Платные подписки</b>", "",
             "<blockquote>🟢 работает · ⏳ скоро кончится · 🔴 истекла · ⏸ выключена в панели · ❄️ заморожена\n"
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


# ── Поиск и заявки ────────────────────────────────────────────────────────────

async def handle_paid_search(query, context):
    from core.states import AWAITING_PAID_SUB_SEARCH
    context.user_data["state"] = AWAITING_PAID_SUB_SEARCH
    await query.edit_message_text(
        "🔎 <b>Поиск подписки</b>\n\n"
        "Пришли что знаешь: TG ID, email клиента, часть UUID или Sub ID, "
        "ник или имя владельца.",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def apply_paid_search(message, context, text: str):
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import search_paid_subs
    rows = await search_paid_subs(text)
    if not rows:
        await message.reply_text(
            "🔎 Ничего не нашлось. Проверь запрос и попробуй ещё раз — "
            "или ищи через раздел пользователей.",
            reply_markup=back_admin())
        return
    if len(rows) == 1:
        # Одно совпадение — сразу единая карточка, без лишнего шага.
        sent = await message.reply_text("⏳ Открываю подписку...")

        class _MsgQuery:
            def __init__(self, m):
                self._m = m

            async def edit_message_text(self, text, **kw):
                return await self._m.edit_text(text, **kw)

            async def answer(self, *a, **kw):
                return None

        await handle_paid_sub_view(_MsgQuery(sent), rows[0][0])
        return
    lines = [f"🔎 <b>Нашлось подписок: {len(rows)}</b>\n"]
    kb = []
    for r in rows:
        name = str(r[2] or "").removeprefix("paid_")
        lines.append(f"• <code>{escape(name)}</code> · до {str(r[3])[:10]} · "
                     f"TG <code>{r[1]}</code>")
        kb.append([InlineKeyboardButton(
            f"💳 {name} · до {str(r[3])[:10]}",
            callback_data=f"paid_sub_view:{r[0]}")])
    kb.append([InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")])
    await message.reply_text("\n".join(lines), parse_mode="HTML",
                             reply_markup=InlineKeyboardMarkup(kb))


async def handle_paid_requests(query):
    """Заявки, ждущие решения: раньше жили только в уведомлениях — потерял
    уведомление, потерял заявку. Теперь у них свой экран."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import list_pending_requests
    rows = await list_pending_requests()
    lines = ["📥 <b>Заявки на подписку</b>\n"]
    kb = []
    if not rows:
        lines.append("<blockquote>Ждущих заявок нет.</blockquote>")
    for tg_id, created, first_name, username in rows:
        name = escape(str(first_name or tg_id))
        uname = f" · @{escape(str(username))}" if username else ""
        lines.append(f"• <b>{name}</b>{uname} · <code>{tg_id}</code> · {str(created)[:16]}")
        kb.append([
            InlineKeyboardButton(f"✅ {str(first_name or tg_id)[:16]}",
                                 callback_data=f"paid_approve:{tg_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"paid_reject:{tg_id}"),
        ])
    kb.append([InlineKeyboardButton("🔄 Обновить", callback_data="paid_requests"),
               InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


# ── Настройки ─────────────────────────────────────────────────────────────────

async def handle_paid_presets_menu(query):
    cfg = load_config()
    squad_names = {}
    if cfg.get("rw_squads"):
        import services.remnawave as rw
        got = await rw.list_squads()
        if got.get("ok"):
            for sq in got["squads"]:
                squad_names[sq["uuid"]] = sq["name"]
    await query.edit_message_text(
        "⚙️ <b>Настройки подписок</b>\n\n"
        + _fmt_presets(cfg, squad_names)
        + "\n\n<i>Применяются только к новым подпискам. У выданных условия "
          "зафиксированы при создании — меняются в самой подписке. "
          "Исключение: LTE-пресет подхватывают и старые подписки без своего лимита.</i>",
        parse_mode="HTML",
        reply_markup=paid_presets_keyboard(),
    )


_TIME_HINT = (
    "<blockquote>Время — в свободной форме:\n"
    "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, "
    "<code>44 минуты</code>, <code>3 месяца</code></blockquote>"
)


async def handle_paid_preset_trial(query, context):
    from core.states import AWAITING_PAID_TRIAL_PERIOD
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
    from core.states import AWAITING_PAID_PRESET_HWID
    context.user_data["state"] = AWAITING_PAID_PRESET_HWID
    await query.edit_message_text(
        "🖥 <b>Лимит HWID</b>\n\n<i>Пришли число (0 = безлимит).</i>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_traffic(query, context):
    from core.states import AWAITING_PAID_PRESET_TRAFFIC
    context.user_data["state"] = AWAITING_PAID_PRESET_TRAFFIC
    await query.edit_message_text(
        "📶 <b>Трафик (ГБ)</b>\n\n<i>Пришли число в ГБ или <code>-</code> для безлимита.</i>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_preset_lte(query, context):
    from core.states import AWAITING_PAID_PRESET_LTE
    context.user_data["state"] = AWAITING_PAID_PRESET_LTE
    cfg = load_config()
    cur = cfg.get("paid_preset_lte")
    cur_str = f"{cur} ГБ" if cur is not None else "30 ГБ (по умолчанию)"
    await query.edit_message_text(
        "🌐 <b>LTE-трафик новых подписок (ГБ в месяц)</b>\n\n"
        f"<blockquote>Сейчас: <b>{cur_str}</b></blockquote>\n\n"
        "<i>Пришли число в ГБ или <code>-</code>, чтобы вернуться к 30 ГБ по умолчанию. "
        "Подписки без своего лимита подхватят новый пресет автоматически, "
        "а со своим — нет, он правится в самой подписке.</i>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


# ── Сквады Remnawave (платные) ──────────────────────────────────────────────
# Один экран вместо двух кнопок: здесь настраиваются два параметра.
# 1) Выдаваемые сквады (rw_squads): их получают все новые подписки —
#    в их число должен входить и сквад LTE-серверов.
# 2) LTE: месячный лимит ГБ, какой из выданных сквадов считать LTE
#    (его бот отключит при конце трафика) и какой сквад включить вместо
#    него. В новом месяце всё возвращается обратно: LTE-сквад снова
#    включается, fallback — отключается.

async def handle_paid_squads_menu(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import services.remnawave as rw
    cfg = load_config()
    lte_raw = cfg.get("paid_preset_lte")
    lte_str = f"{lte_raw} ГБ" if lte_raw is not None else "30 ГБ (по умолчанию)"
    fb = cfg.get("paid_lte_fallback_squad")
    lte_squads = list(cfg.get("paid_lte_squads") or [])
    issued = list(cfg.get("rw_squads") or [])
    names = {}
    r = await rw.list_squads()
    if r["ok"]:
        names = {sq["uuid"]: sq["name"] for sq in r["squads"]}
    fb_label = "не переключать" if not fb else names.get(fb) or f"сквад {str(fb)[:8]}…"
    lte_label = ("не выбраны" if not lte_squads else
                 ", ".join(names.get(u) or f"{str(u)[:8]}…" for u in lte_squads))
    issued_label = ("не выбраны" if not issued else
                    ", ".join(names.get(u) or f"{str(u)[:8]}…" for u in issued))
    await query.edit_message_text(
        "🗂 <b>Сквады Remnawave</b>\n\n"
        "🗂 <b>Выдаваемые сквады</b>\n<blockquote>"
        f"Новые подписки получают: <b>{_esc_name(issued_label)}</b>"
        "</blockquote>\n\n"
        "🌐 <b>LTE</b>\n<blockquote>"
        f"📶 LTE-трафик в месяц: <b>{lte_str}</b>\n"
        f"📡 Сквад LTE-серверов: <b>{_esc_name(lte_label)}</b>\n"
        f"🔀 Сквад после конца LTE: <b>{_esc_name(fb_label)}</b>"
        "</blockquote>\n\n"
        "Как это работает: пока LTE есть, у подписки работают обычные "
        "сквады и сквад LTE-серверов. Как только месячный LTE-трафик "
        "кончается, сквад LTE-серверов отключается, а включается сквад "
        "после конца LTE. В новом месяце бот возвращает всё обратно.\n\n"
        "<i>Сквад LTE-серверов должен быть также выбран в выдаваемых "
        "сквадах — именно оттуда новые подписки его получают. "
        "В настройках LTE мы только помечаем, какой из выданных "
        "сквадов отключать.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗂 Выдаваемые сквады",
                                  callback_data="paid_issued_squads")],
            [InlineKeyboardButton(f"📡 LTE-трафик: {lte_str}",
                                  callback_data="paid_preset_lte")],
            [InlineKeyboardButton("📡 Сквад LTE-серверов", callback_data="paid_lte_squads")],
            [InlineKeyboardButton("🔀 Сквад после конца LTE", callback_data="paid_lte_fallback")],
            [InlineKeyboardButton("🔍 Проверить LTE сейчас", callback_data="paid_lte_check_now")],
            [InlineKeyboardButton("◀️ Назад к настройкам", callback_data="paid_sub_presets")],
        ]),
    )


async def handle_paid_issued_squads(query, context):
    """Выдаваемые сквады (платные): какие сквады получают новые подписки.

    Отдельный экран, а не общий из remnawave: у того возврат ведёт
    в меню Remnawave, а здесь надо вернуться в «Сквады Remnawave»
    платных настроек.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import services.remnawave as rw
    await query.edit_message_text("👥 Загружаю сквады…")
    r = await rw.list_squads()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить список сквадов</b>\n\n<code>{r.get('error', '?')}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    chosen = set(load_config().get("rw_squads") or [])
    rows = []
    for sq in r["squads"]:
        mark = "✅ " if sq["uuid"] in chosen else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{sq['name']} · {sq['inbounds']} инб · {sq['members']} чел",
            callback_data=f"paid_issued_squad:{sq['uuid']}")])
    rows.append([InlineKeyboardButton("◀️ Назад к сквадам",
                                      callback_data="paid_squads_menu")])
    await query.edit_message_text(
        "🗂 <b>Выдаваемые сквады</b>\n\n"
        "Отметь, какие сквады выдавать новым платным подпискам. "
        "В их число должен входить и сквад LTE-серверов — иначе "
        "у подписок не будет LTE-доступа.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_paid_issued_squad_toggle(query, context, uuid: str):
    chosen = list(load_config().get("rw_squads") or [])
    if uuid in chosen:
        chosen.remove(uuid)
    else:
        chosen.append(uuid)
    cfg = load_config()
    cfg["rw_squads"] = chosen
    save_config(cfg)
    await handle_paid_issued_squads(query, context)


async def handle_paid_lte_squads(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import services.remnawave as rw
    await query.edit_message_text("👥 Загружаю сквады…")
    r = await rw.list_squads()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить список сквадов</b>\n\n<code>{r.get('error', '?')}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    chosen = set(load_config().get("paid_lte_squads") or [])
    rows = []
    for sq in r["squads"]:
        mark = "✅ " if sq["uuid"] in chosen else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{sq['name']} · {sq['inbounds']} инб · {sq['members']} чел",
            callback_data=f"paid_lte_squad:{sq['uuid']}")])
    rows.append([InlineKeyboardButton("◀️ Назад к сквадам",
                                      callback_data="paid_squads_menu")])
    await query.edit_message_text(
        "📡 <b>Сквад LTE-серверов</b>\n\n"
        "Отметь сквады, которые дают доступ к LTE-серверам. Именно их "
        "бот отключит, когда у подписки кончится LTE-трафик. Можно "
        "выбрать несколько — нажми ещё раз, чтобы снять отметку.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_paid_lte_squad_toggle(query, context, uuid: str):
    chosen = list(load_config().get("paid_lte_squads") or [])
    if uuid in chosen:
        chosen.remove(uuid)
    else:
        chosen.append(uuid)
    cfg = load_config()
    cfg["paid_lte_squads"] = chosen
    save_config(cfg)
    await handle_paid_lte_squads(query, context)


# ── Сквад после конца LTE ────────────────────────────────────────────────────
# Внутренний сквад в Remnawave — это набор инбаундов. Когда у подписки
# кончается месячный LTE-трафик, бот отключает сквад LTE-серверов
# и включает выбранный здесь сквад. В новом месяце, когда счётчик
# обнуляется, бот возвращает обычные сквады.

async def handle_paid_lte_fallback(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import services.remnawave as rw
    await query.edit_message_text("👥 Загружаю сквады…")
    r = await rw.list_squads()
    if not r["ok"]:
        await query.edit_message_text(
            f"❌ <b>Не получить список сквадов</b>\n\n<code>{r.get('error', '?')}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    cfg = load_config()
    current = cfg.get("paid_lte_fallback_squad")
    limit_off = bool(cfg.get("paid_lte_limit_off"))
    rows = [[InlineKeyboardButton(
        "✅ Лимит LTE отключён — нажми, чтобы включить" if limit_off
        else "📉 Лимит LTE включён — нажми, чтобы отключить",
        callback_data="paid_lte_limit_toggle")]]
    for sq in r["squads"]:
        mark = "✅ " if sq["uuid"] == current else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{sq['name']} · {sq['inbounds']} инб · {sq['members']} чел",
            callback_data=f"paid_lte_fallback:{sq['uuid']}")])
    rows.append([InlineKeyboardButton("🚫 Не переключать",
                                      callback_data="paid_lte_fallback_off")])
    rows.append([InlineKeyboardButton("🔍 Проверить LTE сейчас",
                                      callback_data="paid_lte_check_now")])
    rows.append([InlineKeyboardButton("◀️ Назад к сквадам",
                                      callback_data="paid_squads_menu")])
    cur_name = ""
    if current:
        cur_name = next((s["name"] for s in r["squads"] if s["uuid"] == current),
                        "выбранный сквад")
    await query.edit_message_text(
        "🔀 <b>Сквад после конца LTE</b>\n\n"
        + ("<blockquote>📴 <b>Лимит LTE сейчас ОТКЛЮЧЁН</b> — "
           "CDN-серверы доступны всем без учёта трафика, "
           "в fallback никто не перекидывается, а у пользователей "
           "скрыты остаток LTE в боте, кабинете и подписке.</blockquote>\n\n"
           if limit_off else "")
        + (f"<blockquote>Сейчас: <b>{_esc_name(cur_name)}</b></blockquote>\n\n"
           if cur_name else "")
        + "Выбери внутренний сквад панели — его инбаунды получит подписка, "
          "когда её месячный LTE-трафик закончится: сквад LTE-серверов "
          "отключится, а этот включится. Проверка идёт каждые "
          "30 минут, а в новом месяце бот вернёт обычные сквады сам.\n\n"
          "<i>Если выбрать «Не переключать», LTE просто считается в боте, "
          "а доступ не меняется — как раньше.</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_paid_lte_limit_toggle(query, context):
    """Тумблер «Отключить лимит LTE» (config paid_lte_limit_off).

    При отключении лимита lte_fallback_tick на ближайшем проходе
    вернёт уже перекинутых в fallback на обычные сквады.
    """
    cfg = load_config()
    cfg["paid_lte_limit_off"] = not bool(cfg.get("paid_lte_limit_off"))
    save_config(cfg)
    await handle_paid_lte_fallback(query, context)


async def handle_paid_lte_fallback_set(query, context, uuid: str | None):
    cfg = load_config()
    if uuid:
        cfg["paid_lte_fallback_squad"] = uuid
        note = "выбран"
    else:
        cfg.pop("paid_lte_fallback_squad", None)
        note = "выключен"
    save_config(cfg)
    await query.answer(f"Сквад после LTE: {note}")
    await handle_paid_squads_menu(query, context)


async def handle_paid_lte_check_now(query, context):
    await query.edit_message_text("⏳ Проверяю LTE у всех подписок…")
    r = await lte_fallback_tick(context)
    if not r.get("ok"):
        await query.edit_message_text(
            f"⚠️ <b>Проверка не прошла</b>\n\n<code>{r.get('error', '?')}</code>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    cfg = load_config()
    warn = ""
    if not cfg.get("paid_lte_squads"):
        warn += "\n⚠️ Не выбран сквад LTE-серверов — бот не знает, что отключать."
    if not cfg.get("paid_lte_fallback_squad"):
        warn += "\n⚠️ Не выбран сквад после конца LTE — переключения не будет."
    await query.edit_message_text(
        "✅ <b>Проверка LTE завершена</b>\n\n"
        f"🔀 Переведено на fallback-сквад: <b>{r['switched']}</b>\n"
        f"↩️ Возвращено на обычные сквады: <b>{r['restored']}</b>\n"
        f"👥 Проверено подписок: <b>{r['checked']}</b>"
        + (f"\n⚠️ Панель не приняла: <b>{r['panel_fail']}</b>" if r["panel_fail"] else "")
        + warn,
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def lte_fallback_tick(context) -> dict:
    """Фоновая проверка LTE: при конце трафика отключает сквад
    LTE-серверов и включает сквад после конца LTE, а в новом месяце
    (или при росте лимита) возвращает обычные сквады.

    Состояние — колонка paid_subs.lte_fallback_month («ГГГГ-ММ:uuid»):
    месяц перевода и сквад, на который перевели. Если админ сменил
    fallback-сквад посреди месяца, переведённых переведём на новый
    при следующей проверке, а не только в новом месяце.
    Возвращает счётчики {ok, checked, switched, restored, panel_fail}.
    """
    import logging
    from datetime import datetime
    from features.blacklist import blacklisted_ids
    from services.panel import update_client_squads
    from paidsub.storage import lte_watch_subs, update_paid_sub_field, add_history
    import services.remnawave as rw
    cfg = load_config()
    fallback = cfg.get("paid_lte_fallback_squad")
    limit_off = bool(cfg.get("paid_lte_limit_off"))
    lte_squads = set(cfg.get("paid_lte_squads") or [])
    month = datetime.now().strftime("%Y-%m")
    if not rw.is_configured():
        return {"ok": False, "error": "панель не настроена"}
    usage_r = await rw.all_lte_usage()
    if not usage_r["ok"]:
        return {"ok": False, "error": usage_r.get("error")}
    usage = usage_r["usage"]
    # Обычные сквады — те, что выдаются подпискам (в них входит и
    # сквад LTE-серверов, пока он не отключён). При конце LTE из них
    # убирается сквад LTE-серверов и добавляется fallback.
    normal = list(dict.fromkeys(rw.settings()["squads"]))
    exhausted_squads = list(dict.fromkeys(
        [s for s in normal if s not in lte_squads]
        + ([fallback] if fallback else [])))
    skip = await blacklisted_ids()
    bot = context.bot if hasattr(context, "bot") else None
    checked = switched = restored = panel_fail = 0
    for sub_id, tg_id, email, sub_lte, fb_raw in await lte_watch_subs():
        if tg_id in skip:
            continue
        checked += 1
        fb_m, _, fb_sq = (fb_raw or "").partition(":")
        switched_this_month = fb_m == month
        used_gb = usage.get(rw.make_username(email or "", 0), 0) / 1024 ** 3
        limit = rw.lte_limit_gb(sub_lte, cfg.get("paid_preset_lte"))
        exhausted = used_gb >= limit
        if (not limit_off and exhausted and fallback and lte_squads
                and not (switched_this_month and fb_sq == fallback)):
            res = await update_client_squads(email, exhausted_squads)
            if not res.get("success"):
                panel_fail += 1
                logging.error("LTE fallback: панель не приняла %s: %s",
                              email, res.get("error"))
                continue
            await update_paid_sub_field(sub_id, "lte_fallback_month",
                                        f"{month}:{fallback}")
            await add_history(tg_id, "settings_changed",
                              f"LTE закончился ({used_gb:.2f} ГБ из {limit} ГБ) — "
                              "сквад LTE-серверов отключён, включён fallback-сквад")
            switched += 1
            if bot and tg_id and not switched_this_month:
                await _notify_user(
                    bot, tg_id,
                    "🌐 <b>LTE-трафик на этот месяц закончился</b>\n\n"
                    f"<blockquote>Использовано: <b>{used_gb:.2f} ГБ</b> из {limit} ГБ</blockquote>\n\n"
                    "<i>LTE-серверы отключены, до 1-го числа доступны "
                    "обычные серверы — LTE вернётся в новом месяце.</i>")
        elif fb_m and (fb_m != month or limit_off) and normal:
            # новый месяц: счётчик обнулся — возвращаем обычные сквады
            # (среди них снова есть сквад LTE-серверов, fallback уходит);
            # тот же возврат — при отключении лимита админом.
            res = await update_client_squads(email, normal)
            if not res.get("success"):
                panel_fail += 1
                logging.error("LTE restore: панель не приняла %s: %s",
                              email, res.get("error"))
                continue
            await update_paid_sub_field(sub_id, "lte_fallback_month", None)
            await add_history(tg_id, "settings_changed",
                              "Лимит LTE отключён — возврат с fallback-сквада "
                              "на обычные, LTE-сквад снова включён"
                              if limit_off else
                              "Новый месяц — возврат с fallback-сквада на обычные, "
                              "LTE-сквад снова включён")
            restored += 1
            if bot and tg_id:
                await _notify_user(
                    bot, tg_id,
                    "🌐 <b>Лимит LTE отключён</b>\n\n"
                    "<i>Серверы через CDN снова доступны без ограничения.</i>"
                    if limit_off else
                    "🌐 <b>Новый месяц — LTE-трафик снова доступен</b>\n\n"
                    f"<blockquote>Лимит на месяц: <b>{limit} ГБ</b></blockquote>")
        elif switched_this_month and not exhausted:
            # лимит подняли (или пресет вырос) — возвращаем досрочно
            if not normal:
                continue
            res = await update_client_squads(email, normal)
            if not res.get("success"):
                panel_fail += 1
                continue
            await update_paid_sub_field(sub_id, "lte_fallback_month", None)
            await add_history(tg_id, "settings_changed",
                              "LTE-лимит увеличен — возврат с fallback-сквада, "
                              "LTE-сквад снова включён")
            restored += 1
    return {"ok": True, "checked": checked, "switched": switched,
            "restored": restored, "panel_fail": panel_fail}


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
    from core.database import list_tariffs
    tariffs = await list_tariffs(only_active=True)

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = [[InlineKeyboardButton(f"🆓 Пробный · {fmt_duration(trial_period)}",
                                callback_data="paid_create_type:trial")]]
    for t_id, _name, period, price, _a, _s in tariffs:
        kb.append([InlineKeyboardButton(
            f"💳 {fmt_duration(period)} · {price} ₽",
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
    from core.states import AWAITING_PAID_SUB_TG_ID
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cfg = load_config()
    context.user_data["state"] = AWAITING_PAID_SUB_TG_ID

    if kind == "trial":
        context.user_data["create_trial"] = True
        context.user_data.pop("create_period", None)
        label = "🆓 <b>Пробная подписка</b>"
        period = fmt_duration(cfg.get("paid_trial_period", 86400))
    else:
        from core.database import get_tariff
        tariff = await get_tariff(int(kind))
        if not tariff:
            await query.answer("Тариф не найден", show_alert=True)
            return
        context.user_data["create_trial"] = False
        context.user_data["create_period"] = int(tariff[2])
        label = "💳 <b>Платная подписка</b>"
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
                             period_override: int | None = None,
                             notify: bool = True):
    """Создаёт платную подписку. trial=True — пробный период.

    Работа — в paidsub.service.create_paid_sub, здесь только тексты.
    notify=False — не шлёт клиенту «Подписка готова!»: текст уведомления
    формирует вызывающий (например, подарок со своим текстом).
    """
    await reply_func("⏳ Создаю подписку…")
    bot = context.bot if hasattr(context, "bot") else None
    result = await _svc.create_paid_sub(
        tg_id, trial=trial, period_seconds=period_override, bot=bot)
    if not result.get("ok"):
        await reply_func(
            "❌ <b>Ошибка создания подписки</b>" + NL + NL +
            "<code>" + str(result["error"]) + "</code>",
            parse_mode="HTML",
        )
        return

    traffic_str = result["traffic_str"]
    period_label = result["period_label"]
    # ссылку даём через sub.drbl.tech (CDN), а не key: DPI режет TLS до key
    from handlers.user import primary_sub_url
    sub_link = primary_sub_url(result["sub_url"])
    user_text = (
        "🎉 <b>Подписка готова!</b>" + NL + NL +
        "<blockquote>📅 Действует до: <b>" + result["expire"][:16] + "</b></blockquote>" + NL + NL +
        "🔑 <b>Ссылка для подключения</b>" + NL +
        "<code>" + sub_link + "</code>" + NL + NL +
        "<i>Нажмите на ссылку — она скопируется — и вставьте её в INCY.</i>"
    )

    if for_user:
        # экран открыт у самого клиента (авто-триал): служебные поля вроде
        # TG ID и email ему не нужны, и второе уведомление было бы дублем
        await reply_func(user_text, parse_mode="HTML")
        return

    await reply_func(
        "✅ <b>Подписка создана (" + period_label + ")!</b>" + NL + NL +
        "👤 TG ID: <code>" + str(tg_id) + "</code>" + NL +
        "📧 Email: <code>" + result["email"] + "</code>" + NL +
        "📅 До: <b>" + result["expire"] + "</b>" + NL +
        "📶 Трафик: <b>" + traffic_str + "</b>" + NL + NL +
        "🔗 Ссылка:" + NL + "<code>" + sub_link + "</code>",
        parse_mode="HTML",
    )

    if bot and notify:
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
            from core.log_channel import send_log
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

    fraud_block = ""
    try:
        from html import escape
        from features.fraud import pre_trial_check
        warns = await pre_trial_check(user.id)
        if warns:
            fraud_block = ("\n🕵 <b>Антифрод:</b>\n"
                           + "\n".join(f"· {escape(w)}" for w in warns)
                           + "\n")
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🆕 <b>Запрос на подписку</b>\n\n"
            f'👤 <a href="tg://user?id={user.id}">{_esc_name(user.first_name, user.id)}</a> '
            f"({_esc_name(uname, user.id)})\n"
            f"🆔 TG ID: <code>{user.id}</code>\n"
            f"{fraud_block}\n"
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

    from services.panel import update_client_expire
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
                    from core.log_channel import send_log as _log
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
                    from core.log_channel import send_log as _log
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

    from core.log_channel import send_log
    from core.database import get_user_info
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


# Название месяца в предложном падеже: «в октябре», «в ноябре»…
# (та же таблица, что на экране «LTE-интернет» у пользователя)
_MONTH_PREP = ("", "январе", "феврале", "марте", "апреле", "мае", "июне",
               "июле", "августе", "сентябре", "октябре", "ноябре", "декабре")


async def _lte_view_line(row) -> str:
    """Строки LTE для карточки подписки: потребление за текущий месяц
    и лимит (свой или по умолчанию). Потребление берётся из панели
    тем же путём, что и на экране «LTE-интернет»: сумма по узлам [CDN].
    Если панель не отвечает или LTE-узлов нет — карточка не ломается,
    показывается только лимит, а при ошибке панели — пометка об этом."""
    from services.remnawave import (is_configured, lte_limit_gb, lte_limit_label,
                           make_username, user_cdn_usage)
    from datetime import datetime as _dt
    email = row[2]
    sub_lte = row[19] if len(row) > 19 else None
    preset = load_config().get("paid_preset_lte")
    limit_line = (f"🌐 LTE-трафик в месяц: "
                  f"<b>{lte_limit_label(sub_lte, preset)}</b>\n")
    limit = lte_limit_gb(sub_lte, preset)
    if limit == 0:
        return "🌐 LTE-серверы: <b>закрыты</b>\n"
    if not is_configured():
        return limit_line
    r = await user_cdn_usage(make_username(email or "", 0))
    if not r.get("ok"):
        return limit_line.rstrip("\n") + " · потребление недоступно\n"
    if not r.get("cdn_nodes"):
        return limit_line
    used_gb = r["used_bytes"] / 1024 ** 3
    left_gb = max(0.0, limit - used_gb)
    ratio = min(used_gb / limit, 1.0)
    bar = "▓" * int(ratio * 10) + "░" * (10 - int(ratio * 10))
    month = _MONTH_PREP[_dt.now().month]
    lines = (f"🌐 LTE в {month}: <b>{used_gb:.2f} ГБ</b> из {limit} ГБ · "
             f"осталось <b>{left_gb:.2f} ГБ</b>\n"
             f"[{bar}] {int(ratio * 100)}%\n")
    if r.get("failed"):
        lines += ("<i>Часть LTE-серверов не ответила — "
                  "цифра может быть неполной.</i>\n")
    return lines


async def handle_paid_sub_view(query, sub_id: int):
    card = await _svc.get_sub_card(sub_id, kind="paid")
    if not card.get("ok"):
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    row = card["row"]
    sub = card["sub"]
    # row: id(0),tg_id(1),email(2),uuid(3),sub_id(4),sub_url(5),expire(6),
    #      ip(7),hwid(8),traffic(9),created(10),status(11),payment_pending(12),
    #      ind_trial(13),ind_pay(14),ind_renew(15),ind_price(16),ind_pay_url(17)
    _, tg_id, email, uuid_val, sub_id_str, sub_url, expire, _limit_ip, limit_hwid, total_gb, created_at = row[:11]
    status = sub["status"]
    ind_trial = sub["ind_trial_period"]

    traffic_limit = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    if card["panel"]["traffic_ok"]:
        up = card["panel"]["up"]
        down = card["panel"]["down"]
        total_used = up + down
        traffic_line = (f"📶 Трафик: <b>{_fmt_bytes(total_used)}</b> из {traffic_limit}  "
                        f"(⬆ {_fmt_bytes(up)} · ⬇ {_fmt_bytes(down)})")
    else:
        traffic_line = f"📶 Трафик: <b>{traffic_limit}</b>"

    enabled = card["panel"]["enabled"]
    frozen_at = card.get("frozen_at")
    frozen = bool(frozen_at)
    status_icon = "❄️" if frozen else ("🟢" if enabled else "🔴")
    frozen_line = ""
    if frozen:
        from paidsub.storage import parse_sub_date as _psd
        frozen_dt = _psd(frozen_at)
        paused_line = ""
        if frozen_dt:
            paused_line = (f" · на паузе уже "
                           f"{fmt_duration_precise(int((datetime.now() - frozen_dt).total_seconds()))}")
        frozen_line = (f"❄️ <b>Заморожена</b> с {frozen_at}{paused_line} — "
                       f"срок стоит, дни не сгорают\n")

    # Статус подписки
    status_labels = {"active": "активна", "expired": "истекла"}
    status_label = status_labels.get(status, status)

    # Оплаты владельца: сколько всего заплатил и какая оплата последняя.
    # Раньше здесь был пустой payment_line — блок задумывался, но не жил.
    payment_line = ""
    if tg_id:
        try:
            from core.database import user_payments
            prows, pcount, psum = await user_payments(tg_id, 1)
            if pcount:
                payment_line = (f"💰 Оплат: <b>{pcount}</b> · на сумму "
                                f"<b>{psum} ₽</b>\n")
                if prows:
                    last = prows[0]
                    prov = {"platega": "Platega", "anore": "Anore"}.get(
                        last[1], last[1] or "")
                    payment_line += (f"🧾 Последняя: <b>{last[2]} ₽</b>"
                                     f" · {prov} · {str(last[4])[:10]}\n")
            else:
                payment_line = "💰 Оплат не было\n"
        except Exception:
            payment_line = ""

    # Количество продлений
    times_renewed = card["times_renewed"]
    sub_type = "оплаченная" if times_renewed > 0 else "пробная"

    # Юзер инфо
    user = card["user"]
    uname = user["username"] if user else None
    first_name = user["first_name"] if user else None

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
    if card["referrer"]:
        ref = card["referrer"]
        referral_line = (f"👥 Пришёл от: <b>{_esc_name(ref['first_name'], ref['tg_id'])}</b> "
                         f"(<code>{ref['tg_id']}</code>)\n")

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

    # Из карточки пользователя (меню объединили в одно): последнее
    # подключение к VPN, приглашённые рефералы, пометка чёрного списка.
    vpn_line = ""
    if tg_id:
        try:
            from services.panel import get_last_online
            from handlers.control import last_seen_text
            lo = await get_last_online(timeout=5)
            if lo.get("ok"):
                vpn_line = f"🔌 VPN: {last_seen_text(lo['last'].get(email))}\n"
        except Exception:
            vpn_line = ""
    invited_line = ""
    if tg_id:
        try:
            from paidsub.storage import get_referral_stats
            rs = await get_referral_stats(tg_id)
            if rs["total"] > 0:
                invited_line = (f"👥 Приглашено: <b>{rs['total']}</b> "
                                f"(с бонусом: {rs['rewarded']})")
        except Exception:
            invited_line = ""
    bl_block = ""
    if tg_id:
        try:
            from features.blacklist import entry as _bl_entry, public_reason as _bl_reason
            from html import escape as _esc_html
            ble = await _bl_entry(tg_id)
            if ble:
                src = "вручную" if ble["source"] == "manual" else "общий список"
                bl_block = (f"\n⛔ <b>В чёрном списке</b> ({src})\n"
                            f"<blockquote>{_esc_html(_bl_reason(ble['reason']))}</blockquote>\n")
        except Exception:
            bl_block = ""

    extra_lines = "\n".join(
        x for x in (referral_line.strip(), invited_line) if x)
    # В админке показываем обе формы ссылки: sub — для людей, key — как
    # хранится и как ходит origin; настройка домена на админку не влияет.
    sub_form, key_form = _both_urls(sub_url)
    await query.edit_message_text(
        f"📄 <b>Подписка #{sub_id}</b>  {status_icon}\n"
        + tg_line
        + bl_block
        + "\n📌 <b>Срок</b>\n<blockquote>"
        f"Статус: <b>{status_label}</b>  ·  {sub_type} (продлений: {times_renewed})\n"
        + frozen_line
        + payment_line
        + time_left_line.rstrip("\n")
        + "</blockquote>\n\n"
        "📊 <b>Лимиты</b>\n<blockquote>"
        f"🖥 Устройств: <b>{limit_hwid or 'без ограничения'}</b>\n"
        f"{traffic_line}\n"
        + await _lte_view_line(row)
        + vpn_line
        + f"🕐 Создана: {created_at}"
        "</blockquote>\n"
        + (f"\n{extra_lines}\n" if extra_lines else "")
        + ind_block
        + "\n🔧 <b>Технические данные</b>\n<blockquote expandable>"
        f"📧 Email: <code>{email}</code>\n"
        f"🆔 UUID: <code>{uuid_val}</code>\n"
        f"📋 Sub ID: <code>{sub_id_str}</code>"
        "</blockquote>\n\n"
        "🔗 <b>Ссылки</b>\n"
        f"sub: <code>{sub_form}</code>\n"
        f"key: <code>{key_form}</code>",
        parse_mode="HTML",
        reply_markup=paid_sub_view_keyboard(sub_id, enabled, frozen=frozen,
                                            tg_id=tg_id),
        disable_web_page_preview=True,
    )


# ── Вкл/Выкл ─────────────────────────────────────────────────────────────────

async def handle_paid_sub_toggle(query, sub_id: int, context=None):
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    await query.edit_message_text("⏳ Обновляю статус...")
    result = await _svc.toggle_sub(sub_id, kind="paid", bot=bot)
    if not result.get("ok"):
        if result.get("error") == "panel_client_not_found":
            await query.answer("❌ Клиент не найден в панели", show_alert=True)
        else:
            await query.edit_message_text(
                f"❌ Ошибка: <code>{result['error']}</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
        return
    await handle_paid_sub_view(query, sub_id)


# ── Удаление ──────────────────────────────────────────────────────────────────

async def handle_paid_sub_delete(query, sub_id: int, context=None):
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if row and row[2]:
        await query.edit_message_text("⏳ Удаляю из панели...")
    result = await _svc.delete_sub(sub_id, kind="paid", bot=bot)
    await query.edit_message_text(
        f"🗑 Подписка удалена из базы.\n{result['panel_status']}",
        reply_markup=back_admin(),
    )


# ── Заморозка ─────────────────────────────────────────────────────────────────

async def handle_paid_sub_freeze(query, sub_id: int, context=None):
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    await query.edit_message_text("🧊 Замораживаю подписку...")
    result = await _svc.freeze_sub(sub_id, kind="paid", bot=bot)
    if not result.get("ok"):
        if result.get("error") == "already_frozen":
            await query.answer("Подписка уже заморожена", show_alert=True)
            await handle_paid_sub_view(query, sub_id)
        elif result.get("error") == "panel_client_not_found":
            await query.answer("❌ Клиент не найден в панели", show_alert=True)
        else:
            await query.edit_message_text(
                f"❌ Ошибка: <code>{result['error']}</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
        return
    await handle_paid_sub_view(query, sub_id)


async def handle_paid_sub_unfreeze(query, sub_id: int, context=None):
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    await query.edit_message_text("▶️ Размораживаю подписку...")
    result = await _svc.unfreeze_sub(sub_id, kind="paid", bot=bot)
    if not result.get("ok"):
        if result.get("error") == "not_frozen":
            await query.answer("Подписка не заморожена", show_alert=True)
            await handle_paid_sub_view(query, sub_id)
        else:
            await query.edit_message_text(
                f"❌ Ошибка: <code>{result['error']}</code>",
                parse_mode="HTML", reply_markup=back_admin(),
            )
        return
    await handle_paid_sub_view(query, sub_id)


async def handle_paid_sub_topic(query, sub_id: int, context=None):
    """«💬 Открыть тему»: тема человека в группе поддержки + ссылка.

    Тема одна на человека навсегда: существующую переиспользуем,
    нет — заводим из основного бота (origin='admin'). Дальше админ
    пишет прямо в тему, бот поддержки пересылает человеку.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if not row:
        await query.edit_message_text("❌ Подписка не найдена.", reply_markup=back_admin())
        return
    tg_id = row[1]
    if not tg_id or not bot:
        await query.answer("У подписки нет владельца в Telegram — тему завести некому.",
                           show_alert=True)
        return
    from core.admin_dm import ensure_user_topic
    topic = await ensure_user_topic(bot, tg_id)
    if not topic:
        await query.answer("Не удалось открыть тему: группа поддержки не настроена "
                           "или основной бот не админ в ней.", show_alert=True)
        return
    topic_id, group_id = topic
    gid = str(group_id)
    internal = gid[4:] if gid.startswith("-100") else gid.lstrip("-")
    url = f"https://t.me/c/{internal}/{topic_id}"
    await query.edit_message_text(
        "💬 <b>Тема в группе поддержки</b>\n\n"
        "<i>Пишите прямо в тему — бот поддержки перешлёт человеку. "
        "Если человек ещё ни разу не писал в бота поддержки, переслать "
        "ему не выйдет, пока он не обратится туда сам.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Перейти в тему", url=url)],
            [InlineKeyboardButton("◀️ К подписке",
                                  callback_data=f"paid_sub_view:{sub_id}")],
        ]),
    )


# ── Продление срока ──────────────────────────────────────────────────────────

async def handle_paid_sub_extend(query, sub_id: int, context):
    from core.states import AWAITING_PAID_SUB_EXTEND
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
    from core.states import AWAITING_PAID_SUB_REDUCE
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

BULK_SCOPES = ("all", "active", "trial", "paying", "soon", "expired")


async def handle_paid_bulk_menu(query, context=None, scope: str = "all"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.keyboards import PAID_TABS
    from paidsub.storage import paid_counts
    if scope not in BULK_SCOPES:
        scope = "all"
    if context is not None:
        context.user_data["bulk_scope"] = scope
    counts = await paid_counts()
    total = counts.get(scope, 0)
    icon, label = PAID_TABS[scope]
    scope_row = [InlineKeyboardButton(
        ("• " if k == scope else "") + f"{PAID_TABS[k][0]} {counts.get(k, 0)}",
        callback_data=f"paid_bulk_menu:{k}") for k in BULK_SCOPES[:3]]
    scope_row2 = [InlineKeyboardButton(
        ("• " if k == scope else "") + f"{PAID_TABS[k][0]} {counts.get(k, 0)}",
        callback_data=f"paid_bulk_menu:{k}") for k in BULK_SCOPES[3:]]
    await query.edit_message_text(
        "⚡ <b>Массовые действия</b>\n\n"
        f"<blockquote>Выборка: {icon} <b>{label}</b> — подписок: <b>{total}</b></blockquote>\n\n"
        "⚠️ <i>Действие применится ко всей выбранной вкладке сразу.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            scope_row, scope_row2,
            [InlineKeyboardButton("➕ Добавить срок", callback_data=f"paid_bulk_extend:{scope}"),
             InlineKeyboardButton("➖ Убавить срок", callback_data=f"paid_bulk_reduce:{scope}")],
            [InlineKeyboardButton("🖥 Лимит устройств", callback_data=f"paid_bulk_hwid:{scope}")],
            [InlineKeyboardButton("📡 LTE-трафик", callback_data=f"paid_bulk_lte:{scope}")],
            [InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")],
        ]),
    )


async def handle_paid_bulk_extend(query, context, scope: str = "all"):
    from core.states import AWAITING_PAID_BULK_EXTEND
    context.user_data["state"] = AWAITING_PAID_BULK_EXTEND
    context.user_data["bulk_scope"] = scope if scope in BULK_SCOPES else "all"
    await query.edit_message_text(
        "➕ <b>Добавить срок подпискам выборки</b>\n\n"
        "<blockquote>Время — в свободной форме:\n"
        "<code>5 часов</code>, <code>7 дней</code>, <code>2 недели</code>, <code>1 месяц</code></blockquote>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )


async def handle_paid_bulk_reduce(query, context, scope: str = "all"):
    from core.states import AWAITING_PAID_BULK_REDUCE
    context.user_data["state"] = AWAITING_PAID_BULK_REDUCE
    context.user_data["bulk_scope"] = scope if scope in BULK_SCOPES else "all"
    await query.edit_message_text(
        "➖ <b>Убавить срок у подписок выборки</b>\n\n"
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
        await handle_paid_bulk_menu(query, context)
        return
    seconds, direction = int(pending["seconds"]), int(pending["direction"])
    scope = pending.get("scope", "all")
    await query.edit_message_text("⏳ Применяю к подпискам выборки...")
    bot = context.bot if hasattr(context, "bot") else None
    only_ids = None
    if scope != "all":
        from paidsub.storage import all_paid_subs
        only_ids = [r[0] for r in await all_paid_subs(scope)]
    result = await _svc.bulk_extend(seconds, direction, bot=bot, only_ids=only_ids)
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
    """Тонкая обёртка над paidsub.service.apply_devices_payment (совместимость)."""
    bot = context.bot if hasattr(context, "bot") else None
    return await _svc.apply_devices_payment(
        tg_id, count, amount=amount, mode=mode, bot=bot)


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
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    email, limit_hwid = row[2], row[8]
    await query.edit_message_text("📱 Спрашиваю панель…")
    r = await _svc.list_devices(sub_id, kind="paid")

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
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    await query.edit_message_text("🌐 Спрашиваю панель…")
    r = await _svc.list_ips(sub_id, kind="paid")

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


async def handle_paid_sub_reissue(query, sub_id: int, context=None):
    """Перевыпуск ключа платной подписки из админки.

    Сервис владельцу не пишет (у платных перевыпуск обычно делает сам
    владелец из своего чата), поэтому новую ссылку человеку отправляем
    отсюда. Подтверждение перед действием — handlers/confirm.py
    (paid_sub_reissue).
    """
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    bot = context.bot if context and hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    await query.edit_message_text("🔁 Перевыпускаю ключ…")
    result = await _svc.reissue_sub(sub_id, kind="paid", bot=bot)
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ К подписке",
                              callback_data=f"paid_sub_view:{sub_id}")]])
    if not result.get("ok"):
        await query.edit_message_text(
            "❌ <b>Не получилось</b>\n\n"
            f"<blockquote><code>{escape(str(result.get('error')))}</code></blockquote>\n\n"
            "<i>Старая ссылка продолжает работать.</i>",
            parse_mode="HTML", reply_markup=back_kb)
        return
    new_url = _display_url(result.get("new_url") or "")
    tg_id = result.get("tg_id") or row[1]
    sent = False
    if bot and tg_id:
        await _notify_user(
            bot, tg_id,
            "🔁 <b>Ключ подписки перевыпущен</b>\n\n"
            f"<blockquote><code>{new_url}</code></blockquote>\n\n"
            "Удалите старую подписку в приложении и вставьте эту ссылку — "
            "старая больше не работает.")
        sent = True
    await query.edit_message_text(
        "🔁 <b>Ключ перевыпущен</b>\n\n"
        f"Новая ссылка:\n<code>{new_url}</code>"
        + ("\n\n<i>Отправил её владельцу сообщением.</i>" if sent else ""),
        parse_mode="HTML", reply_markup=back_kb)


_HISTORY_LABELS = {
    "trial_approved": "🆓 Триал одобрен",
    "trial_rejected": "🚫 Триал отклонён",
    "trial_stopped": "⏹ Триал остановлен",
    "key_reissued": "🔁 Ключ перевыпущен",
    "settings_changed": "⚙️ Изменены настройки",
    "device_removed": "📱 Устройство убрано",
    "promo_days": "🎟 Промокод: начислены дни",
    "promo_issued": "🎟 Выдан промокод",
    "blacklisted": "⛔ Чёрный список: добавлен",
    "unblacklisted": "✅ Чёрный список: убран",
}


async def handle_paid_sub_history(query, sub_id: int, page: int = 1):
    """История событий подписки: что с ней делали и когда."""
    from html import escape
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_user_history
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    rows, total_pages = await get_user_history(row[1], page, 8)
    page = min(max(1, page), total_pages)
    lines = [f"📜 <b>История подписки #{sub_id}</b>\n"]
    if not rows:
        lines.append("<i>Событий пока не было.</i>")
    for _id, _tg, action, details, created_at in rows:
        label = _HISTORY_LABELS.get(action, action)
        lines.append(f"• <b>{escape(str(created_at)[:16])}</b> — {escape(label)}")
        if details:
            det = escape(str(details))
            if len(det) > 140:
                det = det[:140] + "…"
            lines.append(f"   <i>{det}</i>")
    if total_pages > 1:
        lines.append(f"\n<i>Стр. {page} из {total_pages}</i>")
    kb = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            "⬅️", callback_data=f"paid_sub_history:{sub_id}:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            "➡️", callback_data=f"paid_sub_history:{sub_id}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ К подписке",
                                    callback_data=f"paid_sub_view:{sub_id}")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_paid_hwid_del(query, context, sub_id: int, ref: str):
    bot = context.bot if hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    res = await _svc.delete_device(sub_id, ref, kind="paid", bot=bot)
    if res.get("ok"):
        await query.answer("Устройство убрано")
    elif res.get("error") == "gone":
        await query.answer("Устройства уже нет в панели", show_alert=True)
    else:
        await query.answer(f"Панель не приняла: {res.get('error', '?')}"[:190], show_alert=True)
    await handle_paid_devices(query, sub_id)


async def handle_paid_hwid_clear(query, context, sub_id: int):
    bot = context.bot if hasattr(context, "bot") else None
    row = await get_paid_sub(sub_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    res = await _svc.clear_hwid(sub_id, kind="paid", bot=bot)
    if res.get("ok"):
        await query.answer("Устройства очищены")
    else:
        await query.answer(f"Панель не приняла: {res.get('error', '?')}"[:190], show_alert=True)
    await handle_paid_devices(query, sub_id)


async def handle_paid_device_price(query, context):
    from core.states import AWAITING_DEVICE_PRICE
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
    from core.states import AWAITING_DEVICE_MAX
    context.user_data["state"] = AWAITING_DEVICE_MAX
    cur = int(load_config().get("device_max_extra") or 5)
    await query.edit_message_text(
        "📱 <b>Максимум докупа</b>\n\n"
        f"Сейчас: <b>{cur}</b> устройств сверх тарифа\n\n"
        "Сколько слотов один человек может добрать?",
        parse_mode="HTML", reply_markup=back_admin(),
    )




async def handle_paid_bulk_hwid(query, context, scope: str = "all"):
    from core.states import AWAITING_PAID_BULK_HWID
    context.user_data["state"] = AWAITING_PAID_BULK_HWID
    context.user_data["bulk_scope"] = scope if scope in BULK_SCOPES else "all"
    await query.edit_message_text(
        "🔑 <b>Лимит устройств (HWID) для подписок выборки</b>\n\n"
        "Сколько устройств разрешить на подписку?\n"
        "Введи число, <code>0</code> — без ограничения.",
        parse_mode="HTML", reply_markup=back_admin(),
    )


# что именно правим оптом: подпись для экрана и колонка в базе
LIMIT_KINDS = {"hwid": ("🖥", "устройств", "limit_hwid"),
               "lte": ("📡", "LTE-трафика", "lte_gb")}


async def handle_paid_bulk_lte(query, context, scope: str = "all"):
    from core.states import AWAITING_PAID_BULK_LTE
    context.user_data["state"] = AWAITING_PAID_BULK_LTE
    context.user_data["bulk_scope"] = scope if scope in BULK_SCOPES else "all"
    cfg = load_config()
    cur = cfg.get("paid_preset_lte")
    cur_str = f"{cur} ГБ" if cur is not None else "30 ГБ (по умолчанию)"
    await query.edit_message_text(
        "🌐 <b>LTE-трафик для подписок выборки (ГБ в месяц)</b>\n\n"
        f"<blockquote>Пресет для новых: <b>{cur_str}</b></blockquote>\n\n"
        "Сколько LTE-трафика дать каждой подписке в месяц?\n"
        "Введи число в ГБ (0 — LTE закрыт для всех) или <code>-</code>, "
        "чтобы вернуть всем лимит по умолчанию. "
        "В панель это не уходит — LTE считается только ботом.",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def preview_bulk_limits(message, context, kind: str, value: int | None):
    """Показывает, кого затронет смена лимита, и спрашивает подтверждение."""
    import aiosqlite
    from features.blacklist import blacklisted_ids
    from core.database import DB_PATH
    from handlers.confirm import confirm_keyboard
    emoji, label, field = LIMIT_KINDS[kind]
    scope = context.user_data.get("bulk_scope", "all")
    id_filter = None
    if scope != "all":
        from paidsub.storage import all_paid_subs
        id_filter = {r[0] for r in await all_paid_subs(scope)}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT id, tg_id, {field}, extra_devices FROM paid_subs"
        ) as cur:
            all_rows = await cur.fetchall()
    rows = [(tg, f, ex) for sid, tg, f, ex in all_rows
            if id_filter is None or sid in id_filter]
    context.user_data["bulk_scope"] = scope
    skip = await blacklisted_ids()
    targets = [r for r in rows if r[0] not in skip]
    with_extra = sum(1 for _tg, _old, ex in targets if kind == "hwid" and ex)
    # 0 в лимите — это «без ограничения», поэтому переход с нуля тоже ужесточение
    def _target(ex):
        return value + int(ex or 0) if (kind == "hwid" and value) else value
    if kind == "lte":
        # NULL у подписки — это пресет (или 30 ГБ по умолчанию): сравниваем
        # с действующим лимитом, а не с NULL, иначе предпросмотр врёт
        from services.remnawave import lte_limit_gb
        preset = load_config().get("paid_preset_lte")
        default = lte_limit_gb(None, preset)
        new_eff = default if value is None else value
        tighter = sum(1 for _tg, old, _ex in targets
                      if new_eff < lte_limit_gb(old, preset))
        value_label = "по умолчанию" if value is None else f"{value} ГБ"
        panel_note = "Меняем только в базе бота: панель о LTE-лимите не знает. "
    else:
        tighter = sum(1 for _tg, old, ex in targets
                      if _target(ex) and (not old or _target(ex) < old))
        value_label = value or "без ограничения"
        panel_note = "Меняем и в базе, и в панели. "
    context.user_data["bulk_limits"] = {"kind": kind, "value": value}
    await message.reply_text(
        f"{emoji} <b>Поставить лимит {label} = {value_label} подпискам выборки?</b>\n\n"
        f"👥 Затронет подписок: <b>{len(targets)}</b>"
        + (f" · пропустим из ЧС: {len(rows) - len(targets)}\n" if len(rows) != len(targets) else "\n")
        + (f"⚠️ У <b>{tighter}</b> лимит станет строже — им придёт уведомление.\n" if tighter else "")
        + (f"📱 У <b>{with_extra}</b> есть оплаченные устройства — им добавим сверх этого числа.\n"
           if with_extra else "")
        + "\n" + panel_note
        + "Пресет для новых подписок остаётся прежним.",
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
    await query.edit_message_text(f"{emoji} Меняю лимит {label} у подписок выборки…")
    bot = context.bot if hasattr(context, "bot") else None
    scope = context.user_data.pop("bulk_scope", "all")
    only_ids = None
    if scope != "all":
        from paidsub.storage import all_paid_subs
        only_ids = [r[0] for r in await all_paid_subs(scope)]
    r = await _svc.bulk_set_limits(kind, value, bot=bot, only_ids=only_ids)
    if kind == "lte":
        value_label = "по умолчанию" if value is None else f"{value} ГБ"
    else:
        value_label = value or "без ограничения"
    await query.edit_message_text(
        f"✅ <b>Готово</b>\n\n"
        f"{emoji} Лимит {label}: <b>{value_label}</b>\n"
        f"📊 Обновлено подписок: <b>{r['updated']}</b>\n"
        + (f"⛔ Пропущено — в чёрном списке: <b>{r['skipped']}</b>\n" if r["skipped"] else "")
        + (f"⚠️ Панель не приняла: <b>{r['panel_fail']}</b>\n" if r["panel_fail"] else "")
        + (f"📨 Предупредили об ужесточении: <b>{r['tightened']}</b>" if r["tightened"] else ""),
        parse_mode="HTML", reply_markup=back_admin(),
    )


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
    from services.remnawave import lte_limit_label
    sub_lte = row[19] if len(row) > 19 else None
    lte_str = lte_limit_label(sub_lte, load_config().get("paid_preset_lte"))

    await query.edit_message_text(
        f"⚙️ <b>Настройки подписки #{sub_id}</b>\n\n"
        f"📅 Действует до: <b>{period_end_line}</b>\n"
        f"🖥 Лимит устройств: <b>{hwid_str}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n"
        f"🌐 LTE-трафик в месяц: <b>{lte_str}</b>\n"
        f"🆓 Пробный период: <b>{trial_str}</b>\n"
        f"{pay_line}\n"
        "Выбери параметр для изменения:",
        parse_mode="HTML",
        reply_markup=paid_sub_settings_keyboard(sub_id),
    )


async def handle_paid_sub_edit_expire(query, sub_id: int, context):
    from core.states import AWAITING_PAID_SUB_EDIT_EXPIRE
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
    from core.states import AWAITING_PAID_SUB_EDIT_HWID
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_HWID
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"🖥 <b>Лимит HWID подписки #{sub_id}</b>\n\n<i>Пришли число (0 = безлимит).</i>",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_traffic(query, sub_id: int, context):
    from core.states import AWAITING_PAID_SUB_EDIT_TRAFFIC
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_TRAFFIC
    context.user_data["edit_sub_id"] = sub_id
    await query.edit_message_text(
        f"📶 <b>Трафик подписки #{sub_id}</b>\n\n<i>Пришли число ГБ или <code>-</code> для безлимита.</i>",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_lte(query, sub_id: int, context):
    from core.states import AWAITING_PAID_SUB_EDIT_LTE
    context.user_data["state"] = AWAITING_PAID_SUB_EDIT_LTE
    context.user_data["edit_sub_id"] = sub_id
    row = await get_paid_sub(sub_id)
    sub_lte = row[19] if row and len(row) > 19 else None
    from services.remnawave import lte_limit_label
    cur = lte_limit_label(sub_lte, load_config().get("paid_preset_lte"))
    await query.edit_message_text(
        f"🌐 <b>LTE-трафик подписки #{sub_id} (ГБ в месяц)</b>\n\n"
        f"<blockquote>Сейчас: <b>{cur}</b></blockquote>\n\n"
        "<i>Пришли число в ГБ (0 — LTE закрыт для этой подписки) или "
        "<code>-</code>, чтобы вернуться к лимиту по умолчанию. "
        "Это только счётчик в боте: панель о LTE-лимите не знает, "
        "доступ он сам по себе не закрывает.</i>",
        parse_mode="HTML", reply_markup=back_admin(),
    )


async def handle_paid_sub_edit_trial(query, sub_id: int, context):
    from core.states import AWAITING_PAID_SUB_EDIT_TRIAL
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
    from features.blacklist import blacklisted_ids
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
            from core.database import log_activity
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
    from services.panel_tags import refresh_user_tag

    now = datetime.now()
    for row in await get_expired_paid_subs():
        (sub_id, tg_id, email, _uuid_val, _sub_id_str, _sub_url,
         expire_str, status, times_renewed, _ind_renew_time, _period_end,
         frozen_at) = row

        if frozen_at:
            # Замороженная: срок на паузе. Не помечаем истёкшей и не
            # тревожим человека — при разморозке дата сдвинется на всё
            # время паузы, и проверка увидит её уже актуальной.
            continue

        expire_dt = parse_sub_date(expire_str)
        if not expire_dt:
            continue

        if now < expire_dt:
            if status != "active":
                await update_paid_sub_field(sub_id, "status", "active")
                await refresh_user_tag(tg_id)
            continue

        if status == "expired":
            continue

        # Срок вышел: помечаем истёкшей и один раз говорим об этом человеку
        await update_paid_sub_field(sub_id, "status", "expired")
        await refresh_user_tag(tg_id)
        if tg_id:
            from core.database import log_activity
            await log_activity(tg_id, "ev:period_ended",
                               "триал" if times_renewed == 0 else "оплаченный")
            await log_activity(tg_id, "ev:expired")

        # Панель закрывает доступ сама по своему сроку. Перезаписывать её
        # прошедшей датой Remnawave не даёт («Validation failed») — а разница
        # в секунды не стоит ни запроса, ни тревоги. Проверяем только, что
        # панель не даёт доступ сильно дольше базы (правили руками).
        try:
            from services.panel import _name as _panel_name
            import services.remnawave as rw
            from datetime import datetime as _dt
            _r = await rw.user_by_name(_panel_name(email))
            _panel_exp = ((_r.get("data") or {}).get("expireAt")
                          if _r.get("ok") else None)
            _drift = 0
            if _panel_exp:
                _pdt = _dt.fromisoformat(str(_panel_exp).replace("Z", "+00:00"))
                if _pdt.tzinfo is not None:
                    _pdt = _pdt.replace(tzinfo=None)
                _drift = (_pdt - expire_dt).total_seconds()
            # панель даёт доступ дольше базы больше чем на 5 минут —
            # это уже не погрешность, а ручная правка: доступ открыт зря
            if _drift > 300:
                from core.log_channel import send_log as _send_log
                await _send_log(context.bot,
                    f"⚠️ Панель даёт доступ дольше базы: <code>{email}</code>\n"
                    f"База до: <b>{expire_str[:16]}</b> · панель до: "
                    f"<b>{str(_panel_exp)[:16]}</b>\n"
                    "Отключи клиента в панели руками.")
        except Exception:
            pass

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
    """Тонкая обёртка над paidsub.service.revoke_period (совместимость)."""
    bot = context.bot if hasattr(context, "bot") else None
    return await _svc.revoke_period(
        tg_id, period_seconds, reason=reason, bot=bot)


async def apply_paid_payment(tg_id: int, amount: int, context,
                             promo_code: str | None = None,
                             source: str = "Platega",
                             period_seconds: int | None = None,
                             gift_from: int | None = None) -> dict:
    """Тонкая обёртка над paidsub.service.apply_paid_payment (совместимость)."""
    bot = context.bot if hasattr(context, "bot") else None
    return await _svc.apply_paid_payment(
        tg_id, amount, promo_code=promo_code, source=source,
        period_seconds=period_seconds, gift_from=gift_from, bot=bot)


async def apply_gift_payment(gift_tg: int, giver_tg: int, amount: int, context,
                             promo_code: str | None = None,
                             source: str = "Platega",
                             period_seconds: int | None = None) -> dict:
    """Тонкая обёртка над paidsub.service.gift_sub (совместимость)."""
    bot = context.bot if hasattr(context, "bot") else None
    return await _svc.gift_sub(
        gift_tg, giver_tg, amount, promo_code=promo_code, source=source,
        period_seconds=period_seconds, bot=bot)




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

    from core.database import get_user_info
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
    from core.states import AWAITING_REFERRAL_BONUS
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
    from core.states import AWAITING_REFERRAL_INVITED_BONUS
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
