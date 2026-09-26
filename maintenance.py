"""Техработы и выключатели функций.

Два уровня:
• режим техработ — весь бот закрыт для пользователей, админ работает как обычно;
• отдельные функции — можно выключить, например, выдачу триалов или поддержку,
  не останавливая остальное.

Фоновые задачи — опрос оплат, сроки подписок, мониторинг — продолжают работать:
техработы закрывают действия пользователей, а не обработку уже начатого.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import load_config, save_config

DEFAULT_TEXT = (
    "🛠 <b>Идут технические работы</b>\n\n"
    "<blockquote>Бот ненадолго на обслуживании. Уже оплаченные подписки "
    "продолжают работать.</blockquote>\n\n"
    "<i>Скоро вернёмся — спасибо за терпение!</i>"
)

# ключ → (эмодзи, название, callback-и, которые функция закрывает).
# «Моя подписка» без оформленной подписки ведёт к выдаче триала, поэтому
# кнопку my_paid_sub роутер относит к subscription или trial сам.
FEATURES = {
    "trial": ("🆓", "Выдача пробного периода", ()),
    "subscription": ("👤", "Моя подписка", ("qr_code", "copy_sub")),
    "payments": ("💳", "Оплата и продление",
                 ("renew_sub", "pay_invoice", "tariff_pick",
                  "enter_promo", "remove_promo")),
    "reissue": ("🔁", "Перевыпуск ключа", ("reissue_key", "reissue_do")),
    "support": ("💬", "Поддержка", ("support_open", "support_page", "support_files")),
    "referral": ("👥", "Рефералы", ("referral",)),
}


def is_maintenance() -> bool:
    return bool(load_config().get("maintenance_enabled", False))


def maintenance_text() -> str:
    return load_config().get("maintenance_text") or DEFAULT_TEXT


def feature_enabled(key: str) -> bool:
    return key not in (load_config().get("features_off") or [])


def feature_for_callback(data: str) -> str | None:
    for key, (_emoji, _name, callbacks) in FEATURES.items():
        for cb in callbacks:
            if data == cb or data.startswith(cb + ":"):
                return key
    return None


def _one_button(label: str, cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=cb)]])


async def _deliver(text: str, kb, query=None, message=None):
    if query is not None:
        try:
            await query.edit_message_text(
                text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True
            )
            return
        except Exception as e:
            # повторное нажатие на тот же экран — Telegram отвечает «not modified»
            if "not modified" in str(e).lower():
                return
            message = query.message
    if message is not None:
        try:
            await message.reply_text(
                text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True
            )
        except Exception:
            pass


async def show_maintenance(query=None, message=None):
    await _deliver(maintenance_text(), _one_button("🔄 Проверить снова", "back_start"),
                   query=query, message=message)


async def show_feature_off(key: str, query=None, message=None):
    name = FEATURES.get(key, ("", "Эта функция", ()))[1]
    text = (f"⏸ <b>{name}</b>\n\n"
            "<blockquote>Раздел временно недоступен.</blockquote>\n\n"
            "<i>Попробуйте чуть позже.</i>")
    await _deliver(text, _one_button("◀️ Главное меню", "back_start"),
                   query=query, message=message)


# ── Админка ──────────────────────────────────────────────────────────────────

def _menu_text() -> str:
    on = is_maintenance()
    off = [k for k in FEATURES if not feature_enabled(k)]
    state = "🔴 включены — бот закрыт для пользователей" if on else "🟢 выключены"
    lines = [
        "🛠 <b>Техработы и функции</b>", "",
        f"Техработы: <b>{state}</b>",
        "<i>На админа это не действует. Оплаты, сроки подписок и мониторинг "
        "продолжают работать.</i>", "",
        "👀 <b>Пользователи увидят</b>",
        "┈┈┈┈┈┈┈┈┈┈",
        # текст сам может содержать цитату — поэтому не заворачиваем его в свою
        maintenance_text(),
        "┈┈┈┈┈┈┈┈┈┈", "",
        "⚙️ <b>Функции</b> — нажми, чтобы выключить или включить."
        + (f"\nСейчас выключено: <b>{len(off)}</b>" if off else ""),
    ]
    return "\n".join(lines)


def _menu_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        "🟢 Выключить техработы" if is_maintenance() else "🔴 Включить техработы",
        callback_data="mnt_toggle",
    )]]
    rows.append([InlineKeyboardButton("✏️ Текст сообщения", callback_data="mnt_text")])
    # функции парами — меню короче, а отметка ✅/⏸ всё равно видна сразу
    pair = []
    for key, (emoji, name, _cbs) in FEATURES.items():
        mark = "✅" if feature_enabled(key) else "⏸"
        pair.append(InlineKeyboardButton(f"{mark} {emoji} {name}",
                                         callback_data=f"mnt_feature:{key}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


async def handle_maintenance_menu(query, context=None):
    if context:
        context.user_data.pop("state", None)
    await query.edit_message_text(
        _menu_text(), parse_mode="HTML", reply_markup=_menu_kb(),
        disable_web_page_preview=True,
    )


async def handle_maintenance_toggle(query, context):
    cfg = load_config()
    cfg["maintenance_enabled"] = not cfg.get("maintenance_enabled", False)
    save_config(cfg)
    from log_channel import send_log
    await send_log(context.bot, "🛠 Техработы включены" if cfg["maintenance_enabled"]
                   else "✅ Техработы выключены")
    await handle_maintenance_menu(query, context)


async def handle_feature_toggle(query, context, key: str):
    if key not in FEATURES:
        return
    cfg = load_config()
    off = set(cfg.get("features_off") or [])
    now_off = key not in off
    if now_off:
        off.add(key)
    else:
        off.discard(key)
    cfg["features_off"] = sorted(off)
    save_config(cfg)
    from log_channel import send_log
    name = FEATURES[key][1]
    await send_log(context.bot, f"⏸ Выключена функция «{name}»" if now_off
                   else f"▶️ Включена функция «{name}»")
    await handle_maintenance_menu(query, context)


async def handle_maintenance_text(query, context):
    from states import AWAITING_MAINTENANCE_TEXT
    context.user_data["state"] = AWAITING_MAINTENANCE_TEXT
    await query.edit_message_text(
        "✏️ <b>Текст техработ</b>\n\n"
        "Пришли сообщение, которое увидят пользователи.\n\n"
        "<i>Форматирование Telegram сохранится. <code>-</code> — вернуть стандартный текст.</i>",
        parse_mode="HTML",
        reply_markup=_one_button("◀️ Назад", "mnt_menu"),
    )


async def apply_maintenance_text(message, context):
    """Сохраняет текст, только если Telegram принял его разметку."""
    context.user_data.pop("state", None)
    raw = (message.text or "").strip()
    if raw == "-":
        new = None
    else:
        from handlers.broadcast import extract_html
        new = extract_html(message)[:3500]

    # сначала превью: если разметка битая, Telegram откажет,
    # и сломанный текст не попадёт к пользователям
    try:
        await message.reply_text(
            f"✅ <b>{'Вернул стандартный текст' if new is None else 'Текст сохранён'}</b>\n"
            f"<i>Так его увидят пользователи:</i>\n\n{new or DEFAULT_TEXT}",
            parse_mode="HTML",
            reply_markup=_one_button("◀️ К техработам", "mnt_menu"),
            disable_web_page_preview=True,
        )
    except Exception as e:
        await message.reply_text(
            f"❌ Telegram не принял разметку — текст не сохранён.\n\n{e}",
            reply_markup=_one_button("◀️ К техработам", "mnt_menu"),
        )
        return

    cfg = load_config()
    if new is None:
        cfg.pop("maintenance_text", None)
    else:
        cfg["maintenance_text"] = new
    save_config(cfg)
