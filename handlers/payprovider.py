"""Раздел «Платёжная система»: настройки приёма платежей через anore.

Бот сам выставляет счёт и сам засчитывает оплату — подтверждать вручную
не нужно. Другого способа приёма платежей в боте нет.

Способ оплаты (СБП или крипта) человек выбирает сам на форме anore,
комиссия и редиректы задаются в настройках магазина на anore.cc —
в боте их нет.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
from core.keyboards import back_admin
from core.states import (
    AWAITING_ANORE_KEY, AWAITING_ANORE_SHOP, AWAITING_ANORE_WEBHOOK_SECRET,
)


def provider_label() -> str:
    return "Anore"


def provider_line() -> str:
    """Строка о платёжке для админских экранов."""
    import services.anore_api as an
    cfg = load_config()
    if not an.is_configured():
        return "💳 Anore  ·  ⚠️ <b>ключи не заданы</b>"
    return (f"💳 Anore  ·  магазин <b>{cfg.get('anore_shop_id')}</b>"
            f"{' · 🔔 вебхук' if cfg.get('anore_webhook_secret') else ''}")


def _mask(value: str) -> str:
    """Показываем, что ключ задан, не раскрывая его."""
    v = (value or "").strip()
    if not v:
        return "не задан"
    return f"{v[:4]}…{v[-4:]}" if len(v) > 12 else "задан"


async def handle_pay_provider_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    if context:
        context.user_data.pop("state", None)
    cfg = load_config()

    import services.anore_api as an
    ready = an.is_configured()
    lines = ["💳 <b>Платёжная система</b>", "",
             f"<blockquote>Приём платежей: <b>Anore</b>\n"
             f"🔑 Ключ: <code>{_mask(cfg.get('anore_api_key'))}</code>\n"
             f"🏬 ID магазина: <code>{cfg.get('anore_shop_id') or 'не задан'}</code>\n"
             f"🔔 Секрет вебхука: <code>{_mask(cfg.get('anore_webhook_secret'))}</code></blockquote>", "",
             "<i>Бот сам выставляет счёт и сам засчитывает оплату — "
             "подтверждать вручную не нужно.</i>",
             "<i>Оплата подтверждается вебхуком мгновенно, опрос — "
             "страховка, если вебхук не дойдёт.</i>"]
    if not ready:
        lines.append("\n⚠️ <b>Не хватает данных</b> — заполни ключ и id магазина. "
                     "Пока их нет, клиенты не смогут оплатить подписку.")
    if ready and not cfg.get("anore_webhook_secret"):
        lines.append("\n⚠️ <b>Без секрета вебхука</b> подтверждения будут "
                     "только опросом раз в минуту. Секрет появляется в "
                     "настройках anore после сохранения url вебхука.")

    rows = [
        [InlineKeyboardButton("🔑 API-ключ", callback_data="anore_set_key"),
         InlineKeyboardButton("🏬 ID магазина", callback_data="anore_set_shop")],
        [InlineKeyboardButton("🔔 Секрет вебхука", callback_data="anore_set_webhook_secret"),
         InlineKeyboardButton("🔌 Проверить", callback_data="anore_test")],
        [InlineKeyboardButton("◀️ К настройкам", callback_data="paid_sub_presets")],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows), disable_web_page_preview=True,
    )


async def handle_anore_set_key(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_ANORE_KEY
    await query.edit_message_text(
        "🔑 <b>API-ключ anore</b>\n\n"
        "<i>Пришли ключ из личного кабинета anore (Настройки → Ключи API) "
        "одним сообщением. Для проверки сначала можно вставить тестовый "
        "ключ (an_test_…), потом заменить его на боевой (an_live_…).</i>\n\n"
        "⚠️ Сообщение с ключом лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def handle_anore_set_shop(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_ANORE_SHOP
    await query.edit_message_text(
        "🏬 <b>ID магазина anore</b>\n\n"
        "<i>Пришли id магазина из настроек anore (там же, рядом с ключами) "
        "одним сообщением — просто число.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def handle_anore_set_webhook_secret(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_ANORE_WEBHOOK_SECRET
    await query.edit_message_text(
        "🔔 <b>Секрет подписи вебхука anore</b>\n\n"
        "<i>Секрет появляется в настройках anore, когда сохранишь там url "
        "вебхука. Пришли его одним сообщением.</i>\n\n"
        "⚠️ Сообщение с секретом лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def handle_anore_test(query, context: ContextTypes.DEFAULT_TYPE):
    import services.anore_api as an
    await query.edit_message_text("🔌 Проверяю подключение к anore…")
    r = await an.test_connection()
    if r["ok"]:
        text = "✅ <b>Подключение работает</b>\n\n<blockquote>Ключи приняты anore.</blockquote>"
    else:
        from html import escape
        text = (
            "❌ <b>Не удалось подключиться</b>\n\n"
            f"<blockquote><code>{escape(str(r['error']))}</code></blockquote>\n\n"
            "<i>Проверь ключ и id магазина в личном кабинете anore.</i>"
        )
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Ещё раз", callback_data="anore_test"),
             InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def apply_credential(message, context: ContextTypes.DEFAULT_TYPE,
                           field: str, raw: str):
    """Сохраняет ключ, id магазина или секрет вебхука, введённый в чате."""
    value = (raw or "").strip()
    labels = {
        "anore_api_key": "API-ключ",
        "anore_shop_id": "ID магазина",
        "anore_webhook_secret": "Секрет вебхука",
    }
    if not value or len(value) > 200:
        await message.reply_text(
            "❌ <b>Пустое или слишком длинное значение</b>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    if field == "anore_shop_id" and not value.isdigit():
        await message.reply_text(
            "❌ <b>ID магазина — просто число</b>\n\n"
            "<i>Пришли id из настроек anore ещё раз.</i>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    cfg = load_config()
    cfg[field] = value
    save_config(cfg)

    label = labels.get(field, field)
    await message.reply_text(
        f"✅ <b>{label} сохранён</b>\n\n"
        "<i>Рекомендую удалить сообщение с ним из чата.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔌 Проверить", callback_data="anore_test"),
             InlineKeyboardButton("◀️ К платёжке", callback_data="pay_provider_menu")],
        ]),
    )
