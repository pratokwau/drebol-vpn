"""Раздел «Платёжная система»: выбор способа приёма платежей.

CloudPayments — прежняя схема: ссылка на оплату и подтверждение админом.
Platega — приём через API: бот сам выставляет счёт и сам засчитывает оплату.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
from keyboards import back_admin
from states import AWAITING_PLATEGA_MERCHANT, AWAITING_PLATEGA_SECRET

PROVIDERS = {
    "cloudpayments": "CloudPayments",
    "platega": "Platega",
}
DEFAULT_PROVIDER = "cloudpayments"


def current_provider() -> str:
    p = (load_config().get("pay_provider") or DEFAULT_PROVIDER).lower()
    return p if p in PROVIDERS else DEFAULT_PROVIDER


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
    cur = current_provider()

    import platega_api as pg
    lines = [
        "💳 <b>Платёжная система</b>\n",
        f"Сейчас активна: <b>{PROVIDERS[cur]}</b>\n",
    ]

    if cur == "cloudpayments":
        pay_url = cfg.get("paid_pay_url") or "не задана"
        lines.append(
            "Оплата идёт по ссылке, подтверждает админ вручную "
            "по кнопке «Я оплатил».\n"
            f"🔗 Ссылка: <code>{pay_url}</code>"
        )
    else:
        ready = pg.is_configured()
        method_id = int(cfg.get("platega_method", pg.DEFAULT_METHOD) or pg.DEFAULT_METHOD)
        lines.append(
            "Бот сам выставляет счёт и сам засчитывает оплату — "
            "подтверждать вручную не нужно.\n"
            f"🆔 MerchantId: <code>{_mask(cfg.get('platega_merchant_id'))}</code>\n"
            f"🔑 Ключ: <code>{_mask(cfg.get('platega_secret'))}</code>\n"
            f"💠 Способ: <b>{pg.PAYMENT_METHODS.get(method_id, method_id)}</b>"
        )
        if not ready:
            lines.append("\n⚠️ Не хватает данных — заполни MerchantId и ключ.")

    rows = []
    for key, label in PROVIDERS.items():
        mark = "✅ " if key == cur else ""
        rows.append([InlineKeyboardButton(
            f"{mark}{label}", callback_data=f"pay_provider_set:{key}"
        )])

    if cur == "platega":
        rows.append([
            InlineKeyboardButton("🆔 MerchantId", callback_data="platega_set_merchant"),
            InlineKeyboardButton("🔑 Ключ", callback_data="platega_set_secret"),
        ])
        rows.append([InlineKeyboardButton("💠 Способ оплаты", callback_data="platega_methods")])
        rows.append([InlineKeyboardButton("🔌 Проверить подключение", callback_data="platega_test")])
    else:
        rows.append([InlineKeyboardButton("🔗 Ссылка на оплату", callback_data="paid_preset_pay_url")])

    rows.append([InlineKeyboardButton("◀️ К настройкам", callback_data="paid_sub_presets")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows), disable_web_page_preview=True,
    )


async def handle_pay_provider_set(query, context: ContextTypes.DEFAULT_TYPE, provider: str):
    if provider not in PROVIDERS:
        await query.answer("Неизвестная система", show_alert=True)
        return
    cfg = load_config()
    cfg["pay_provider"] = provider
    save_config(cfg)

    from log_channel import send_log
    await send_log(context.bot, f"💳 Платёжная система переключена на {PROVIDERS[provider]}")
    await query.answer(f"Активна {PROVIDERS[provider]}")
    await handle_pay_provider_menu(query, context)


async def handle_platega_set_merchant(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_PLATEGA_MERCHANT
    await query.edit_message_text(
        "🆔 <b>MerchantId Platega</b>\n\n"
        "Пришли MerchantId из личного кабинета Platega "
        "(Настройки) одним сообщением.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def handle_platega_set_secret(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_PLATEGA_SECRET
    await query.edit_message_text(
        "🔑 <b>API-ключ Platega</b>\n\n"
        "Пришли ключ (X-Secret) одним сообщением.\n\n"
        "⚠️ Сообщение с ключом лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def handle_platega_methods(query, context: ContextTypes.DEFAULT_TYPE):
    import platega_api as pg
    cfg = load_config()
    cur = int(cfg.get("platega_method", pg.DEFAULT_METHOD) or pg.DEFAULT_METHOD)
    rows = [
        [InlineKeyboardButton(
            f"{'✅ ' if code == cur else ''}{name}",
            callback_data=f"platega_method:{code}",
        )]
        for code, name in pg.PAYMENT_METHODS.items()
    ]
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")])
    await query.edit_message_text(
        "💠 <b>Способ оплаты Platega</b>\n\n"
        "Выбери, какой способ будет предлагаться клиентам.\n"
        "Доступность способов зависит от подключённых у тебя в Platega.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_platega_method_set(query, context: ContextTypes.DEFAULT_TYPE, code: int):
    cfg = load_config()
    cfg["platega_method"] = int(code)
    save_config(cfg)
    await query.answer("Способ сохранён")
    await handle_pay_provider_menu(query, context)


async def handle_platega_test(query, context: ContextTypes.DEFAULT_TYPE):
    import platega_api as pg
    await query.edit_message_text("🔌 Проверяю подключение к Platega...")
    r = await pg.test_connection()
    if r["ok"]:
        text = "✅ <b>Подключение работает</b>\n\nКлючи приняты Platega."
    else:
        text = (
            f"❌ <b>Не удалось подключиться</b>\n\n<code>{r['error']}</code>\n\n"
            "Проверь MerchantId и ключ в личном кабинете Platega."
        )
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Ещё раз", callback_data="platega_test")],
            [InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def apply_credential(message, context: ContextTypes.DEFAULT_TYPE,
                           field: str, raw: str):
    """Сохраняет MerchantId или ключ, введённый в чате."""
    value = (raw or "").strip()
    if not value or len(value) > 200:
        await message.reply_text(
            "❌ Пустое или слишком длинное значение.",
            reply_markup=back_admin(),
        )
        return
    cfg = load_config()
    cfg[field] = value
    save_config(cfg)

    label = "MerchantId" if field == "platega_merchant_id" else "API-ключ"
    await message.reply_text(
        f"✅ {label} сохранён.\n\n"
        "Рекомендую удалить сообщение с ним из чата.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔌 Проверить подключение", callback_data="platega_test")],
            [InlineKeyboardButton("◀️ К платёжной системе", callback_data="pay_provider_menu")],
        ]),
    )
