"""Раздел «Платёжная система»: настройки приёма платежей через anore.

Бот сам выставляет счёт и сам засчитывает оплату — подтверждать вручную
не нужно. Другого способа приёма платежей в боте нет.

Способ оплаты (СБП или крипта) человек выбирает сам на форме anore.
Настройки самой кассы (способы, комиссия, редиректы, дизайн формы,
логотип) живут только в кабинете anore — API их не отдаёт и не меняет,
поэтому в боте они показаны отдельным экраном «🏬 Настройки кассы»
как справка. А вот баланс, счета и вывод средств — живые данные из API.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
from core.keyboards import back_admin
from core.states import (
    AWAITING_ANORE_KEY, AWAITING_ANORE_SHOP, AWAITING_ANORE_WEBHOOK_SECRET,
    AWAITING_PAYOUT_ADDRESS, AWAITING_PAYOUT_AMOUNT,
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
        [InlineKeyboardButton("💰 Баланс", callback_data="anore_balance"),
         InlineKeyboardButton("💸 Выплаты", callback_data="anore_payouts")],
        [InlineKeyboardButton("🧾 Счета anore", callback_data="anore_payments"),
         InlineKeyboardButton("🏬 Настройки кассы", callback_data="anore_shop")],
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


# ── Баланс, счета и выплаты ───────────────────────────────────────────────
# Живые данные из API anore (GET /balance, /payments, /payouts).


def _fmt_money(value) -> str:
    """12 750,42 ₽ — или прочерк, если значения нет."""
    if value is None:
        return "—"
    try:
        return f"{float(value):,.2f}".replace(",", " ").replace(".", ",") + " ₽"
    except (TypeError, ValueError):
        return str(value)


def _mask_address(method: str, address: str) -> str:
    """Реквизиты показываем только в маске: карта — последние 4 цифры,
    кошелёк — первые и последние 4 символа."""
    a = (address or "").strip()
    if method == "card":
        digits = "".join(ch for ch in a if ch.isdigit())
        return f"•••• {digits[-4:]}" if len(digits) >= 4 else "••••"
    return f"{a[:4]}…{a[-4:]}" if len(a) > 8 else a


_PAYOUT_STATUS = {
    "pending": "⏳ На обработке",
    "approved": "🔄 Принята оператором",
    "paid": "✅ Выплачено",
    "rejected": "❌ Отклонено",
}


def _anore_error_text(error: str) -> str:
    from html import escape
    return (
        "❌ <b>anore не ответила</b>\n\n"
        f"<blockquote><code>{escape(str(error))}</code></blockquote>"
    )


async def handle_anore_balance(query, context: ContextTypes.DEFAULT_TYPE):
    import services.anore_api as an
    await query.edit_message_text("💰 Запрашиваю баланс anore…")
    r = await an.get_balance()
    if not r["ok"]:
        await query.edit_message_text(
            _anore_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="anore_balance"),
                 InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
            ]),
        )
        return
    fee = r.get("fee") or {}
    lines = [
        "💰 <b>Баланс anore</b>", "",
        f"<blockquote>✅ Доступно: <b>{_fmt_money(r.get('available'))}</b>\n"
        f"⏳ В холде: {_fmt_money(r.get('hold'))}\n"
        f"📥 Созрело: {_fmt_money(r.get('matured'))}\n"
        f"💸 Уже выведено: {_fmt_money(r.get('withdrawn'))}\n"
        f"🧾 Всего оплат: {_fmt_money(r.get('paid_amount'))}</blockquote>", "",
    ]
    if fee:
        lines.append(
            "<i>Комиссия на вывод: "
            f"{_fmt_money(fee.get('flatRub'))} до "
            f"{_fmt_money(fee.get('thresholdRub'))}, дальше +"
            f"{fee.get('percentAbove')}%"
            + (f" (+{_fmt_money(fee.get('trc20SurchargeRub'))} за TRC20)"
               if fee.get("trc20SurchargeRub") else "")
            + ".</i>")
    lines.append(
        f"<i>Вывод — от {_fmt_money(r.get('min_amount'))} "
        f"до {_fmt_money(r.get('max_amount'))}.</i>")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Вывести", callback_data="anore_payout_new"),
             InlineKeyboardButton("💸 Выплаты", callback_data="anore_payouts")],
            [InlineKeyboardButton("🔁 Обновить", callback_data="anore_balance"),
             InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def handle_anore_payments(query, context: ContextTypes.DEFAULT_TYPE):
    """Последние счета в anore — со способом оплаты, которого нет в базе бота."""
    import services.anore_api as an
    await query.edit_message_text("🧾 Запрашиваю счета anore…")
    r = await an.list_payments(limit=10)
    if not r["ok"]:
        await query.edit_message_text(
            _anore_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="anore_payments"),
                 InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
            ]),
        )
        return
    items = r.get("payments", [])
    lines = ["🧾 <b>Счета anore</b> — последние 10", ""]
    if not items:
        lines.append("<i>Счетов пока нет.</i>")
    method_label = {"sbp": "СБП", "card": "карта", "yoomoney": "ЮMoney",
                    "crypto": "крипта"}
    status_label = {"paid": "✅ оплачен", "new": "⏳ новый",
                    "expired": "⌛ истёк", "pending": "⏳ в обработке",
                    "failed": "❌ неудачный", "written_off": "🗑 списан"}
    for p in items:
        lines.append(
            f"• {_fmt_money(p.get('rubAmount') or p.get('amount'))} — "
            f"{status_label.get((p.get('status') or '').lower(), p.get('status'))}"
            + (f", {method_label.get(p.get('method'), p.get('method'))}"
               if p.get("method") else "")
            + (f" · <code>{p.get('orderId')}</code>" if p.get("orderId") else "")
        )
    if r.get("total"):
        lines.append(f"\n<i>Всего счетов: {r['total']}.</i>")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Обновить", callback_data="anore_payments"),
             InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


async def handle_anore_payouts(query, context: ContextTypes.DEFAULT_TYPE):
    import services.anore_api as an
    await query.edit_message_text("💸 Запрашиваю выплаты anore…")
    r = await an.list_payouts(limit=10)
    if not r["ok"]:
        await query.edit_message_text(
            _anore_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="anore_payouts"),
                 InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
            ]),
        )
        return
    items = r.get("items", [])
    lines = ["💸 <b>Выплаты anore</b> — последние 10", ""]
    if not items:
        lines.append("<i>Выплат пока не было.</i>")
    for p in items:
        lines.append(
            f"• <code>{p.get('id')}</code> — {_fmt_money(p.get('amount'))} · "
            f"{_PAYOUT_STATUS.get((p.get('status') or '').lower(), p.get('status'))}"
            + (f" · комиссия {_fmt_money(p.get('fee'))}" if p.get("fee") is not None else "")
            + (f" · {p.get('address')}" if p.get("address") else "")
        )
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Новая выплата", callback_data="anore_payout_new"),
             InlineKeyboardButton("💰 Баланс", callback_data="anore_balance")],
            [InlineKeyboardButton("🔁 Обновить", callback_data="anore_payouts"),
             InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )


# ── Создание выплаты: сумма → способ → реквизиты → подтверждение ─────────
# Реквизиты (номер карты / адрес кошелька) в боте НЕ хранятся — только
# в этой заявке. После ввода сообщение с реквизитами лучше удалить из чата.

async def handle_anore_payout_new(query, context: ContextTypes.DEFAULT_TYPE):
    import services.anore_api as an
    context.user_data["state"] = AWAITING_PAYOUT_AMOUNT
    context.user_data.pop("payout", None)
    r = await an.get_balance()
    available = r.get("available") if r.get("ok") else None
    text = (
        "💸 <b>Новая выплата</b>\n\n"
        "<i>Пришли сумму в рублях, целым числом.</i>\n\n"
        + (f"Доступно: <b>{_fmt_money(available)}</b>\n" if available is not None else "")
        + "Карта РФ — от 3 000 до 500 000 ₽, USDT — от 500 до 1 500 000 ₽."
    )
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="anore_payouts")],
        ]),
    )


async def apply_payout_amount(message, context: ContextTypes.DEFAULT_TYPE,
                              raw: str):
    import services.anore_api as an
    text = (raw or "").strip().replace(" ", "").replace(",", ".")
    try:
        amount = int(float(text))
    except ValueError:
        await message.reply_text(
            "❌ <b>Сумма — целое число рублей</b>\n\n"
            "<i>Пришли сумму ещё раз.</i>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    if amount <= 0:
        await message.reply_text(
            "❌ <b>Сумма должна быть больше нуля</b>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    context.user_data.pop("state", None)
    context.user_data["payout"] = {"amount": amount}
    rows = [[InlineKeyboardButton(label, callback_data=f"anore_payout_method:{code}")]
            for code, label in an.PAYOUT_METHODS.items()]
    rows.append([InlineKeyboardButton("◀️ Отмена", callback_data="anore_payouts")])
    await message.reply_text(
        f"💸 <b>Выплата {amount:,} ₽</b>\n\n<i>Куда выводим?</i>".replace(",", " "),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_anore_payout_method(query, context: ContextTypes.DEFAULT_TYPE,
                                     method: str):
    import services.anore_api as an
    payout = context.user_data.get("payout") or {}
    if method not in an.PAYOUT_METHODS:
        await query.answer("Неизвестный способ", show_alert=True)
        return
    low, high = an.payout_limits(method)
    if not low <= int(payout.get("amount", 0)) <= high:
        await query.edit_message_text(
            f"❌ <b>Сумма не подходит</b>\n\n"
            f"<i>{an.PAYOUT_METHODS[method]} — от {low:,} до {high:,} ₽.</i>"
            .replace(",", " "),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="anore_payout_new")],
            ]),
        )
        return
    payout["method"] = method
    context.user_data["payout"] = payout
    context.user_data["state"] = AWAITING_PAYOUT_ADDRESS
    if method == "card":
        hint = ("<i>Пришли полный номер карты РФ одним сообщением "
                "(пробелы допустимы). CVV и PIN никогда не нужны.</i>")
    else:
        hint = ("<i>Пришли адрес кошелька USDT в этой сети одним "
                "сообщением.</i>")
    await query.edit_message_text(
        f"{an.PAYOUT_METHODS[method]}\n\n{hint}\n\n"
        "⚠️ Сообщение с реквизитами лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="anore_payouts")],
        ]),
    )


def _address_ok(method: str, address: str) -> str | None:
    """Возвращает текст ошибки или None, если реквизиты похожи на правду."""
    a = (address or "").strip()
    if not a:
        return "Пустое значение"
    if method == "card":
        digits = "".join(ch for ch in a if ch.isdigit())
        if not (13 <= len(digits) <= 19) or len(digits) != len(a.replace(" ", "").replace("-", "")):
            return "Номер карты — 13–19 цифр"
        return None
    if method == "usdt_trc20":
        if not (a.startswith("T") and len(a) == 34):
            return "Адрес TRON — 34 символа, начинается с T"
        return None
    if method in ("usdt_bep20", "usdt_erc20"):
        if not (a.startswith("0x") and len(a) == 42):
            return "Адрес сети — 0x и 40 hex-символов"
        return None
    if method == "usdt_ton":
        if len(a) < 40:
            return "Адрес TON выглядит слишком коротким"
        return None
    return None


async def apply_payout_address(message, context: ContextTypes.DEFAULT_TYPE,
                               raw: str):
    import services.anore_api as an
    payout = context.user_data.get("payout") or {}
    method = payout.get("method")
    amount = payout.get("amount")
    if not method or not amount:
        context.user_data.pop("state", None)
        await message.reply_text(
            "❌ <b>Заявка потерялась</b> — начни выплату заново.",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    address = (raw or "").strip()
    err = _address_ok(method, address)
    if err:
        await message.reply_text(
            f"❌ <b>{err}</b>\n\n<i>Пришли реквизиты ещё раз.</i>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    payout["address"] = address
    context.user_data["payout"] = payout
    context.user_data.pop("state", None)
    # Примерная комиссия по текущим тарифам — точную anore вернёт
    # в ответе на создание выплаты.
    fee_line = ""
    fees = await an.get_payout_fees()
    if fees.get("ok"):
        raw_fees = fees["raw"]
        code = {"card": "card_rub"}.get(method, method)
        entry = next((m for m in raw_fees.get("methods", [])
                      if m.get("code") == code), None)
        if entry:
            flat = entry.get("flatRub") or 0
            threshold = raw_fees.get("thresholdRub") or 0
            pct = entry.get("percentAbove") or 0
            surcharge = entry.get("surchargeRub") or 0
            est = flat + surcharge
            if threshold and amount > threshold:
                est += (amount - threshold) * pct / 100
            fee_line = f"\nКомиссия ≈ {_fmt_money(est)} (точная — в ответе anore)"
    await message.reply_text(
        "💸 <b>Проверь выплату</b>\n\n"
        f"<blockquote>Сумма: <b>{amount:,} ₽</b>\n".replace(",", " ") +
        f"Куда: {an.PAYOUT_METHODS[method]}\n"
        f"Реквизиты: <code>{_mask_address(method, address)}</code>"
        f"{fee_line}</blockquote>\n\n"
        "<i>Выплата создаётся сразу после подтверждения. "
        "Сообщение с реквизитами лучше удалить из чата.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Вывести", callback_data="anore_payout_do"),
             InlineKeyboardButton("❌ Отмена", callback_data="anore_payouts")],
        ]),
    )


async def handle_anore_payout_do(query, context: ContextTypes.DEFAULT_TYPE):
    import uuid
    import services.anore_api as an
    payout = context.user_data.pop("payout", None)
    if not payout or not payout.get("address"):
        await query.edit_message_text(
            "❌ <b>Заявка потерялась</b> — начни выплату заново.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Выплаты", callback_data="anore_payouts")],
            ]),
        )
        return
    await query.edit_message_text("💸 Создаю выплату в anore…")
    r = await an.create_payout(
        payout["amount"], payout["method"], payout["address"],
        external_id=f"wd-{query.from_user.id}-{uuid.uuid4().hex[:8]}",
    )
    if not r["ok"]:
        await query.edit_message_text(
            _anore_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Выплаты", callback_data="anore_payouts"),
                 InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
            ]),
        )
        return
    lines = [
        "✅ <b>Выплата создана</b>", "",
        f"<blockquote>ID: <code>{r.get('id')}</code>\n"
        f"Сумма: <b>{_fmt_money(r.get('amount'))}</b>\n"
        f"Комиссия: {_fmt_money(r.get('fee'))}\n"
        f"К получению: <b>{_fmt_money(r.get('net'))}</b>\n"
        f"Статус: {_PAYOUT_STATUS.get((r.get('status') or '').lower(), r.get('status'))}\n"
        f"Реквизиты: <code>{r.get('address_masked') or ''}</code></blockquote>",
    ]
    if r.get("tx_hash"):
        lines.append(f"\nTx: <code>{r['tx_hash']}</code>")
    lines.append("\n<i>Статус выплаты обновится сам — anore пришлёт вебхук.</i>")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Выплаты", callback_data="anore_payouts"),
             InlineKeyboardButton("💰 Баланс", callback_data="anore_balance")],
        ]),
    )


# ── Настройки кассы ─────────────────────────────────────────────────────────
# ВНИМАНИЕ: эти значения API anore не отдаёт — их нельзя ни прочитать,
# ни изменить из бота. Экран показывает их так, как настроено в кабинете
# anore (по данным от 08.11.2026). Поменяешь что-то в кабинете — обнови
# и этот экран, иначе он будет врать. Меняется всё только на anore.cc.

async def handle_anore_shop(query, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    lines = [
        "🏬 <b>Настройки кассы anore</b>", "",
        "<i>Эти настройки живут только в кабинете anore — API их не отдаёт, "
        "поэтому бот показывает их так, как настроено (08.11.2026). "
        "Меняется всё только на anore.cc.</i>", "",
        "<blockquote>"
        f"Магазин: <b>drebolvpn_bot</b> · ID <code>{cfg.get('anore_shop_id') or '—'}</code>\n"
        "Способы оплаты: СБП 6% — вкл, криптовалюта 1% — вкл\n"
        "Комиссия: платит магазин (клиент платит ровно цену тарифа)\n"
        "После оплаты: https://t.me/drebolvpn_bot\n"
        "При неуспехе: https://t.me/drebolvpn_bot\n"
        "Кнопка «вернуться»: https://t.me/drebolvpn_bot\n"
        "Дизайн формы: split\n"
        "Логотип формы: https://vpn.drbl.tech/logo.png\n"
        "Вебхук: https://vpn.drbl.tech/api/webhooks/anore\n"
        "События: payment.succeeded, payment.canceled"
        "</blockquote>",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть кабинет anore",
                                  url="https://anore.cc/app/settings")],
            [InlineKeyboardButton("◀️ Назад", callback_data="pay_provider_menu")],
        ]),
    )
