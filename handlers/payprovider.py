"""Раздел «Платёжная система»: настройки приёма платежей через Platega.

Бот сам выставляет счёт и сам засчитывает оплату — подтверждать вручную
не нужно. Другого способа приёма платежей в боте нет.

Способ оплаты (СБП, карта, крипта) человек выбирает сам на форме Platega
(счёт создаётся через /v2 без заданного способа). Настройки кассы
(способы, комиссия, редиректы, Callback URL) живут только в кабинете
Platega — API их не отдаёт и не меняет, поэтому в боте они показаны
отдельным экраном «🏬 Настройки Platega» как справка. А вот баланс,
вывод средств и возвраты — живые данные из API.

Возвраты у Platega ЕСТЬ (в отличие от anore): проверка → запуск →
итог приходит колбэком (статус CHARGEBACKED) или виден опросом.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
from core.keyboards import back_admin
from core.states import (
    AWAITING_PLATEGA_MERCHANT, AWAITING_PLATEGA_SECRET,
    AWAITING_PLATEGA_PAYOUT_SECRET,
    AWAITING_PAYOUT_ADDRESS, AWAITING_PAYOUT_AMOUNT,
)


def provider_label() -> str:
    return "Platega"


def provider_line() -> str:
    """Строка о платёжной системе для админских экранов."""
    import services.platega_api as pg
    cfg = load_config()
    if not pg.is_configured():
        return "💳 Platega  ·  ⚠️ <b>ключи не заданы</b>"
    merchant = (cfg.get("platega_merchant_id") or "").strip()
    tail = " · 💸 выплаты" if pg.is_payout_configured() else " · 💸 выплаты не настроены"
    return (f"💳 Platega  ·  merchant <code>{_mask(merchant)}</code>{tail}")


def _mask(value: str) -> str:
    """Показываем, что ключ задан, не раскрывая его."""
    v = (value or "").strip()
    if not v:
        return "не задан"
    return f"{v[:4]}…{v[-4:]}" if len(v) > 12 else "задан"


async def handle_pay_provider_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    """Раздел «Финансы»: доходы, расходы и прибыль за месяц + подразделы."""
    if context:
        context.user_data.pop("state", None)
    from core.database import finance_summary
    from handlers.finance import current_period, fmt_price, month_title
    period = current_period()
    s = await finance_summary(period)
    spent = ""
    if s["expenses"]:
        spent = (f" (оплачено {fmt_price(s['expenses_paid'])}"
                 f", не оплачено {fmt_price(s['expenses_unpaid'])})")
    lines = ["💰 <b>Финансы</b>", "",
             f"📅 {month_title(period)}", "",
             f"💵 Доходы: <b>{fmt_price(s['income'])}</b>",
             f"🖥 Расходы: <b>{fmt_price(s['expenses'])}</b> в месяц{spent}",
             f"💹 Прибыль: <b>{fmt_price(s['profit'])}</b>", "",
             "<i>Доходы — оплаченные счета за месяц. "
             "Расходы — серверы из списка «🖥 Серверы».</i>"]
    rows = [
        [InlineKeyboardButton("💰 Оплаты", callback_data="payments:paid:1")],
        [InlineKeyboardButton("🖥 Серверы", callback_data="servers_menu")],
        [InlineKeyboardButton("💳 Платёжная система", callback_data="platega_menu")],
        [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows), disable_web_page_preview=True,
    )


async def handle_platega_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    """Экран «Платёжная система»: ключи, баланс, выплаты, возвраты."""
    if context:
        context.user_data.pop("state", None)
    cfg = load_config()

    import services.platega_api as pg
    ready = pg.is_configured()
    payout_ready = pg.is_payout_configured()
    lines = ["💳 <b>Платёжная система</b>", "",
             f"<blockquote>Приём платежей: <b>Platega</b>\n"
             f"🏬 Merchant ID: <code>{_mask(cfg.get('platega_merchant_id'))}</code>\n"
             f"🔑 X-Secret: <code>{_mask(cfg.get('platega_secret'))}</code>\n"
             f"💸 Секрет Payout API: <code>{_mask(cfg.get('platega_payout_secret'))}</code></blockquote>", "",
             "<i>Бот сам выставляет счёт и сам засчитывает оплату — "
             "подтверждать вручную не нужно.</i>",
             "<i>Оплата подтверждается колбэком мгновенно, опрос — "
             "страховка, если колбэк не дойдёт. Счёт живёт 15 минут.</i>",
             "<i>Возвраты работают через API: кнопка «↩️ Вернуть» "
             "на карточке оплаченного счёта в «💰 Оплаты».</i>"]
    if not ready:
        lines.append("\n⚠️ <b>Не хватает данных</b> — заполни Merchant ID "
                     "и X-Secret из кабинета Platega (Настройки → API-ключи). "
                     "Пока их нет, клиенты не смогут оплатить подписку.")
    if ready and not payout_ready:
        lines.append("\n⚠️ <b>Выплаты не настроены</b> — нужен отдельный "
                     "секрет из раздела Payout API в кабинете Platega "
                     "плюс IP сервера в белом списке ключа. "
                     "Приём платежей работает и без него.")

    rows = [
        [InlineKeyboardButton("🏬 Merchant ID", callback_data="platega_set_merchant"),
         InlineKeyboardButton("🔑 X-Secret", callback_data="platega_set_secret")],
        [InlineKeyboardButton("💸 Секрет Payout API", callback_data="platega_set_payout_secret"),
         InlineKeyboardButton("🔌 Проверить", callback_data="platega_test")],
        [InlineKeyboardButton("💰 Баланс", callback_data="platega_balance"),
         InlineKeyboardButton("💸 Выплаты", callback_data="platega_payouts")],
        [InlineKeyboardButton("🏬 Настройки Platega", callback_data="platega_settings")],
        [InlineKeyboardButton("◀️ К финансам", callback_data="pay_provider_menu")],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows), disable_web_page_preview=True,
    )


async def handle_platega_set_merchant(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_PLATEGA_MERCHANT
    await query.edit_message_text(
        "🏬 <b>Merchant ID Platega</b>\n\n"
        "<i>Пришли Merchant ID из личного кабинета Platega "
        "(Настройки → API-ключи) одним сообщением — это UUID вида "
        "1d793365-…</i>\n\n"
        "⚠️ Сообщение с ключом лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
        ]),
    )


async def handle_platega_set_secret(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_PLATEGA_SECRET
    await query.edit_message_text(
        "🔑 <b>X-Secret Platega</b>\n\n"
        "<i>Пришли API-ключ (X-Secret) из личного кабинета Platega "
        "(Настройки → API-ключи) одним сообщением.</i>\n\n"
        "⚠️ Сообщение с ключом лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
        ]),
    )


async def handle_platega_set_payout_secret(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_PLATEGA_PAYOUT_SECRET
    await query.edit_message_text(
        "💸 <b>Секрет Payout API Platega</b>\n\n"
        "<i>Пришли секрет из раздела Payout API в кабинете Platega "
        "одним сообщением. Это ОТДЕЛЬНЫЙ секрет — не X-Secret из "
        "API-ключей. Генерируется в кабинете и показывается один раз.</i>\n\n"
        "<i>И не забудь внести IP сервера (95.85.251.169) в белый "
        "список ключа в том же разделе — иначе Payout API ответит 403.</i>\n\n"
        "⚠️ Сообщение с секретом лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
        ]),
    )


async def handle_platega_test(query, context: ContextTypes.DEFAULT_TYPE):
    import services.platega_api as pg
    await query.edit_message_text("🔌 Проверяю подключение к Platega…")
    r = await pg.test_connection()
    if r["ok"]:
        text = "✅ <b>Подключение работает</b>\n\n<blockquote>Ключи приняты Platega.</blockquote>"
    else:
        from html import escape
        text = (
            "❌ <b>Не удалось подключиться</b>\n\n"
            f"<blockquote><code>{escape(str(r['error']))}</code></blockquote>\n\n"
            "<i>Проверь Merchant ID и X-Secret в личном кабинете Platega.</i>"
        )
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Ещё раз", callback_data="platega_test"),
             InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
        ]),
    )


async def apply_credential(message, context: ContextTypes.DEFAULT_TYPE,
                           field: str, raw: str):
    """Сохраняет Merchant ID, X-Secret или секрет Payout API, введённый в чате."""
    value = (raw or "").strip()
    labels = {
        "platega_merchant_id": "Merchant ID",
        "platega_secret": "X-Secret",
        "platega_payout_secret": "Секрет Payout API",
    }
    if not value or len(value) > 200:
        await message.reply_text(
            "❌ <b>Пустое или слишком длинное значение</b>",
            parse_mode="HTML", reply_markup=back_admin(),
        )
        return
    if field == "platega_merchant_id" and len(value) < 8:
        await message.reply_text(
            "❌ <b>Merchant ID выглядит слишком коротким</b>\n\n"
            "<i>Пришли UUID из кабинета Platega ещё раз.</i>",
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
            [InlineKeyboardButton("🔌 Проверить", callback_data="platega_test"),
             InlineKeyboardButton("◀️ К платёжке", callback_data="platega_menu")],
        ]),
    )


# ── Баланс, счета и выплаты ───────────────────────────────────────────────
# Живые данные из API Platega (GET /balance/all, GET /transaction/{id}).
# Списка счетов у Platega нет — счета смотрят в «💰 Оплаты» (база бота)
# и проверяют живым статусом кнопкой на карточке счёта.


def _fmt_money(value, currency: str = "₽") -> str:
    """12 750,42 ₽ — или прочерк, если значения нет."""
    if value is None:
        return "—"
    try:
        return f"{float(value):,.2f}".replace(",", " ").replace(".", ",") + f" {currency}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_amount(amount, unit: str) -> str:
    """10 000 ₽ / 42,5 USDT — с разделителем тысяч для целых сумм."""
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return f"{amount} {unit}"
    if v == int(v):
        return f"{int(v):,}".replace(",", " ") + f" {unit}"
    return f"{v:g} {unit}"


def _mask_address(method: str, address: str) -> str:
    """Реквизиты показываем только в маске: карта — последние 4 цифры,
    телефон — первые и последние 2 цифры, кошелёк — первые и последние
    4 символа."""
    a = (address or "").strip()
    if method == "card":
        digits = "".join(ch for ch in a if ch.isdigit())
        return f"•••• {digits[-4:]}" if len(digits) >= 4 else "••••"
    if method == "sbp":
        digits = "".join(ch for ch in a if ch.isdigit())
        return f"+{digits[:1]} ••• ••• ••{digits[-2:]}" if len(digits) >= 6 else "••••"
    return f"{a[:4]}…{a[-4:]}" if len(a) > 8 else a


_PAYOUT_STATUS = {
    "created": "⏳ Создана",
    "pending": "⏳ На обработке",
    "approved": "🔄 Принята оператором",
    "paid": "✅ Выплачено",
    "rejected": "❌ Отклонено",
    "failed": "❌ Неудачная",
    "completed": "✅ Выплачено",
}


def _platega_error_text(error: str) -> str:
    from html import escape
    return (
        "❌ <b>Platega не ответила</b>\n\n"
        f"<blockquote><code>{escape(str(error))}</code></blockquote>"
    )


async def handle_platega_balance(query, context: ContextTypes.DEFAULT_TYPE):
    import services.platega_api as pg
    await query.edit_message_text("💰 Запрашиваю баланс Platega…")
    r = await pg.get_balance()
    if not r["ok"]:
        await query.edit_message_text(
            _platega_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="platega_balance"),
                 InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
            ]),
        )
        return
    lines = [
        "💰 <b>Баланс Platega</b>", "",
        f"<blockquote>💵 Рубли: <b>{_fmt_money(r.get('rub'))}</b>"
        + (f" (заморожено {_fmt_money(r.get('frozen_rub'))})"
           if r.get("frozen_rub") else "")
        + f"\n💎 USDT: <b>{_fmt_money(r.get('usdt'), 'USDT')}</b>"
        + (f" (заморожено {_fmt_money(r.get('frozen_usdt'), 'USDT')})"
           if r.get("frozen_usdt") else "")
        + "</blockquote>", "",
        "<i>Вывод — от 1 000 до 100 000 ₽ на карту и по СБП.</i>",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Вывести", callback_data="platega_payout_new"),
             InlineKeyboardButton("💸 Выплаты", callback_data="platega_payouts")],
            [InlineKeyboardButton("🔁 Обновить", callback_data="platega_balance"),
             InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
        ]),
    )


# ── Один счёт: живой статус + запись в базе + возврат ─────────────────────

_PLATEGA_STATUS_LABEL = {
    "paid": "✅ оплачен",
    "pending": "⏳ ожидает оплаты",
    "canceled": "❌ отменён",
    "chargebacked": "↩️ возврат",
    "partially_refunded": "↩️ частично возвращён",
}


async def handle_platega_payment(query, context: ContextTypes.DEFAULT_TYPE,
                                 transaction_id: str):
    """Один счёт: статус в Platega + запись в базе бота и журнале начислений."""
    import services.platega_api as pg
    from core.database import get_payment_by_external, get_payment_credit
    await query.edit_message_text("🔍 Запрашиваю счёт…")
    r = await pg.get_status(transaction_id)
    if not r.get("ok"):
        await query.edit_message_text(
            _platega_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз",
                                      callback_data=f"platega_payment:{transaction_id}"),
                 InlineKeyboardButton("◀️ К оплатам", callback_data="payments:paid:1")],
            ]),
        )
        return
    raw = r.get("raw") or {}
    status_label = _PLATEGA_STATUS_LABEL.get(r.get("status"), r.get("status"))
    method = pg.PAYMENT_METHODS.get(raw.get("paymentMethod"),
                                    raw.get("paymentMethod") or "")
    lines = ["🧾 <b>Счёт Platega</b>", "",
             f"<blockquote>Статус: <b>{status_label}</b>\n"
             f"Сумма: <b>{_fmt_money(r.get('amount'))}</b>\n"
             f"Оплачен: <b>{'да' if r.get('paid') else 'нет'}</b>"
             + (f"\nСпособ: {method}" if method else "")
             + (f"\nЗаказ: <code>{raw.get('payload')}</code>"
                if raw.get("payload") else "")
             + f"\nID: <code>{transaction_id}</code></blockquote>", ""]
    row = await get_payment_by_external(transaction_id)
    kb_rows = []
    if row:
        # строка get_payment_by_external: статус в конце, индекс 11
        bot_status = (row[11] or "") if len(row) > 11 else ""
        credit = await get_payment_credit(row[0])
        lines.append(
            "🤖 <b>В базе бота:</b>\n"
            f"👤 <code>{row[1]}</code> · статус <b>{bot_status}</b> · "
            f"{_fmt_money(row[4])}\n"
            f"Начисление: {'✅ записано в журнале' if credit else '— нет записи'}")
        kb_rows.append([InlineKeyboardButton(
            "👤 Профиль плательщика", callback_data=f"user_profile:{row[1]}")])
        if bot_status == "paid" and r.get("status") == "paid":
            kb_rows.append([InlineKeyboardButton(
                "↩️ Вернуть платёж", callback_data=f"platega_refund:{row[0]}")])
    else:
        lines.append("<i>В базе бота такого счёта нет — создан не ботом.</i>")
    kb_rows.append([InlineKeyboardButton("◀️ К оплатам", callback_data="payments:paid:1")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )


# ── Возврат платежа ───────────────────────────────────────────────────────
# Проверка (cancel-supported) → подтверждение с выбором, отзывать ли срок →
# запуск (cancel) → итог приходит колбэком (CHARGEBACKED) или виден опросом:
# тогда finalize_refund доводит возврат до конца по сохранённому выбору.

async def handle_platega_refund(query, context: ContextTypes.DEFAULT_TYPE,
                                payment_id: int):
    """Проверка возможности возврата: сумма, удержания, причина отказа."""
    import services.platega_api as pg
    from core.database import get_payment_full
    p = await get_payment_full(payment_id)
    if not p:
        await query.answer("Платёж не найден", show_alert=True)
        return
    (_pid, _tg, provider, ext_id, amount, _period, _promo,
     status, _url, _err, _created, _paid, _fn, _un) = p
    if provider != "platega" or status != "paid" or not ext_id:
        await query.answer("Этот платёж вернуть нельзя", show_alert=True)
        return
    await query.edit_message_text("🔍 Проверяю возможность возврата…")
    r = await pg.refund_supported(ext_id)
    if not r.get("ok"):
        await query.edit_message_text(
            _platega_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К платежу",
                                      callback_data=f"payment_view:{payment_id}")],
            ]),
        )
        return
    if not r.get("supported"):
        reason = r.get("block_reason") or "Platega отказала в возврате"
        await query.edit_message_text(
            f"❌ <b>Вернуть нельзя</b>\n\n<blockquote>{reason}</blockquote>\n\n"
            "<i>Возможно, на балансе мерчанта не хватает средств — "
            "возврат оплачивается с него.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К платежу",
                                      callback_data=f"payment_view:{payment_id}")],
            ]),
        )
        return
    lines = [
        "↩️ <b>Возврат платежа</b>", "",
        f"<blockquote>Сумма: <b>{_fmt_money(amount)}</b>\n"
        f"К возврату: <b>{_fmt_money(r.get('refundable_amount') or amount)}</b>"
        + (f"\nУже возвращено: {_fmt_money(r.get('refunded_amount'))}"
           if r.get("refunded_amount") else "")
        + (f"\nСпишется с баланса: {r.get('deduct_usdt')} USDT"
           if r.get("deduct_usdt") else "")
        + (f"\nШтраф: {r.get('penalty_usdt')} USDT"
           if r.get("penalty_usdt") else "")
        + "</blockquote>", "",
        "<i>Возврат может пройти не сразу: Platega обрабатывает его "
        "и присылает итог колбэком. Срок подписки можно отозвать "
        "или оставить — выбери.</i>",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Вернуть и отозвать срок",
                                  callback_data=f"platega_refund_ok:{payment_id}:1")],
            [InlineKeyboardButton("↩️ Вернуть, срок оставить",
                                  callback_data=f"platega_refund_ok:{payment_id}:0")],
            [InlineKeyboardButton("❌ Отмена",
                                  callback_data=f"payment_view:{payment_id}")],
        ]),
    )


async def handle_platega_refund_do(query, context: ContextTypes.DEFAULT_TYPE,
                                   payment_id: int, revoke: bool):
    """Запускает возврат и ставит счёт в «возврат в обработке»."""
    import services.platega_api as pg
    from core.database import (
        get_payment_full, set_payment_status, set_refund_revoke,
    )
    from handlers.payments import finalize_refund
    p = await get_payment_full(payment_id)
    if not p:
        await query.answer("Платёж не найден", show_alert=True)
        return
    (_pid, _tg, provider, ext_id, amount, _period, _promo,
     status, _url, _err, _created, _paid, _fn, _un) = p
    if provider != "platega" or status != "paid" or not ext_id:
        await query.answer("Этот платёж вернуть нельзя", show_alert=True)
        return
    await query.edit_message_text("↩️ Запускаю возврат в Platega…")
    r = await pg.refund(ext_id)
    if not r.get("ok"):
        await query.edit_message_text(
            _platega_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К платежу",
                                      callback_data=f"payment_view:{payment_id}")],
            ]),
        )
        return
    await set_refund_revoke(payment_id, 1 if revoke else 0)
    await set_payment_status(payment_id, "refund_pending")
    if r.get("accepted"):
        # быстрый возврат: сразу доводим до конца
        await finalize_refund(context, payment_id, revoke=revoke)
        text = (
            "✅ <b>Возврат выполнен</b>\n\n"
            f"<blockquote>Сумма: <b>{_fmt_money(amount)}</b>\n"
            f"Срок подписки: {'отозван' if revoke else 'оставлен'}</blockquote>"
        )
    else:
        text = (
            "⏳ <b>Возврат в обработке</b>\n\n"
            "<blockquote>Platega приняла заявку на ручной контроль. "
            "Итог придёт колбэком — тогда бот сам пометит платёж "
            "возвращённым"
            + (" и отзовёт срок" if revoke else "")
            + ".</blockquote>"
        )
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К платежу",
                                  callback_data=f"payment_view:{payment_id}")],
        ]),
    )


# ── Выплаты ───────────────────────────────────────────────────────────────
# У Payout API Platega нет списка выплат — историю созданных ботом
# выплат ведём в своей базе (таблица payouts).

async def handle_platega_payouts(query, context: ContextTypes.DEFAULT_TYPE):
    from core.database import list_payout_records
    items = await list_payout_records(limit=10)
    lines = ["💸 <b>Выплаты Platega</b> — последние 10", ""]
    if not items:
        lines.append("<i>Выплат пока не было.</i>")
    rows: list = []
    for (pid, _prov, ext_id, method, amount, currency, status,
         masked, _created) in items:
        import services.platega_api as pg
        method_label = pg.PAYOUT_METHODS.get(method, method or "")
        unit = "USDT" if currency == "USDT" else "₽"
        st = _PAYOUT_STATUS.get((status or "").lower(), status or "")
        lines.append(
            f"• {amount} {unit} · {method_label} · {st}"
            + (f" · {masked}" if masked else "")
        )
        rows.append([InlineKeyboardButton(
            f"🔍 {amount} {unit} · {st}",
            callback_data=f"platega_payout:{pid}")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            rows + [
                [InlineKeyboardButton("➕ Новая выплата", callback_data="platega_payout_new"),
                 InlineKeyboardButton("💰 Баланс", callback_data="platega_balance")],
                [InlineKeyboardButton("🔁 Обновить", callback_data="platega_payouts"),
                 InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
            ]),
    )


async def handle_platega_payout(query, context: ContextTypes.DEFAULT_TYPE,
                                payout_id: int):
    """Одна выплата из истории бота."""
    from core.database import get_payout_record
    row = await get_payout_record(payout_id)
    if not row:
        await query.answer("Выплата не найдена", show_alert=True)
        return
    import services.platega_api as pg
    (pid, _prov, ext_id, method, amount, currency, status,
     masked, created) = row
    method_label = pg.PAYOUT_METHODS.get(method, method or "")
    unit = "USDT" if currency == "USDT" else "₽"
    st = _PAYOUT_STATUS.get((status or "").lower(), status or "")
    lines = ["💸 <b>Выплата</b>", "",
             f"<blockquote>Статус: <b>{st}</b>\n"
             f"Сумма: <b>{amount} {unit}</b>\n"
             f"Способ: {method_label}\n"
             f"Реквизиты: <code>{masked or '—'}</code>\n"
             f"Создана: {str(created)[:19]}"
             + (f"\nID в Platega: <code>{ext_id}</code>" if ext_id else "")
             + f"\nID: <code>{pid}</code></blockquote>", "",
             "<i>Статус выплаты Platega по API не отдаёт — здесь то, "
             "что вернулось при создании.</i>"]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_payouts")],
        ]),
    )


# ── Создание выплаты: сумма → способ → (банк) → реквизиты → подтверждение ──
# Реквизиты (номер карты / телефон / адрес кошелька) в боте НЕ хранятся —
# только в этой заявке. После ввода сообщение с реквизитами лучше удалить
# из чата.

async def handle_platega_payout_new(query, context: ContextTypes.DEFAULT_TYPE):
    import services.platega_api as pg
    if not pg.is_payout_configured():
        await query.edit_message_text(
            "❌ <b>Выплаты не настроены</b>\n\n"
            "<i>Задай секрет Payout API в «💳 Платёжная система» и внеси "
            "IP сервера в белый список в кабинете Platega.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
            ]),
        )
        return
    context.user_data["state"] = AWAITING_PAYOUT_AMOUNT
    context.user_data.pop("payout", None)
    r = await pg.get_balance()
    rub = r.get("rub") if r.get("ok") else None
    text = (
        "💸 <b>Новая выплата</b>\n\n"
        "<i>Пришли сумму: рубли — для карты и СБП, USDT — для крипты. "
        "Целое число или с копейками.</i>\n\n"
        + (f"Баланс: <b>{_fmt_money(rub)}</b>\n" if rub is not None else "")
        + "Карта РФ и СБП — от 1 000 до 100 000 ₽, USDT — от 1 до 100 000."
    )
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_payouts")],
        ]),
    )


async def apply_payout_amount(message, context: ContextTypes.DEFAULT_TYPE,
                              raw: str):
    import services.platega_api as pg
    text = (raw or "").strip().replace(" ", "").replace(",", ".")
    try:
        amount = float(text)
    except ValueError:
        await message.reply_text(
            "❌ <b>Сумма — число</b>\n\n"
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
    rows = [[InlineKeyboardButton(label, callback_data=f"platega_payout_method:{code}")]
            for code, label in pg.PAYOUT_METHODS.items()]
    rows.append([InlineKeyboardButton("◀️ Отмена", callback_data="platega_payouts")])
    unit = "₽" if amount >= 1000 else "USDT"
    await message.reply_text(
        f"💸 <b>Выплата {_fmt_amount(amount, unit)}</b>\n\n<i>Куда выводим?</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_platega_payout_method(query, context: ContextTypes.DEFAULT_TYPE,
                                       method: str):
    import services.platega_api as pg
    payout = context.user_data.get("payout") or {}
    if method not in pg.PAYOUT_METHODS:
        await query.answer("Неизвестный способ", show_alert=True)
        return
    low, high = pg.payout_limits(method)
    if not low <= float(payout.get("amount", 0)) <= high:
        unit = "₽" if method in ("card", "sbp") else "USDT"
        await query.edit_message_text(
            f"❌ <b>Сумма не подходит</b>\n\n"
            f"<i>{pg.PAYOUT_METHODS[method]} — от {low:,} до {high:,} {unit}.</i>"
            .replace(",", " "),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="platega_payout_new")],
            ]),
        )
        return
    payout["method"] = method
    context.user_data["payout"] = payout
    if method == "sbp":
        # для СБП нужен банк получателя — показываем справочник
        await query.edit_message_text("🏦 Запрашиваю список банков…")
        r = await pg.get_sbp_banks()
        if not r.get("ok"):
            await query.edit_message_text(
                _platega_error_text(r["error"]), parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="platega_payout_new")],
                ]),
            )
            return
        items = r.get("items", [])
        if not items:
            await query.edit_message_text(
                "❌ <b>Список банков пуст</b> — попробуй позже.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="platega_payout_new")],
                ]),
            )
            return
        rows = []
        for b in items[:30]:
            bid = str(b.get("id") or b.get("bankId") or "")
            name = b.get("name") or b.get("bankName") or bid
            if bid:
                rows.append([InlineKeyboardButton(
                    str(name)[:40], callback_data=f"platega_payout_bank:{bid}")])
        rows.append([InlineKeyboardButton("◀️ Отмена", callback_data="platega_payouts")])
        context.user_data["payout_banks"] = {
            str(b.get("id") or b.get("bankId")): (b.get("name") or b.get("bankName") or "")
            for b in items if b.get("id") or b.get("bankId")
        }
        await query.edit_message_text(
            "🏦 <b>Выбери банк получателя</b>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
        )
        return
    context.user_data["state"] = AWAITING_PAYOUT_ADDRESS
    if method == "card":
        hint = ("<i>Пришли полный номер карты РФ одним сообщением "
                "(пробелы допустимы). CVV и PIN никогда не нужны.</i>")
    else:
        hint = ("<i>Пришли адрес кошелька USDT в этой сети одним "
                "сообщением.</i>")
    await query.edit_message_text(
        f"{pg.PAYOUT_METHODS[method]}\n\n{hint}\n\n"
        "⚠️ Сообщение с реквизитами лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_payouts")],
        ]),
    )


async def handle_platega_payout_bank(query, context: ContextTypes.DEFAULT_TYPE,
                                     bank_id: str):
    """Банк для СБП выбран — теперь просим телефон."""
    payout = context.user_data.get("payout") or {}
    if payout.get("method") != "sbp":
        await query.answer("Сначала выбери способ СБП", show_alert=True)
        return
    banks = context.user_data.get("payout_banks") or {}
    payout["bank_id"] = bank_id
    payout["bank_name"] = banks.get(bank_id, "")
    context.user_data["payout"] = payout
    context.user_data["state"] = AWAITING_PAYOUT_ADDRESS
    await query.edit_message_text(
        f"📱 <b>СБП</b> · {banks.get(bank_id, '')}\n\n"
        "<i>Пришли телефон получателя одним сообщением — 11 цифр, "
        "начинается с 7 или 8.</i>\n\n"
        "⚠️ Сообщение с реквизитами лучше потом удалить из чата.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_payouts")],
        ]),
    )


def _address_ok(method: str, address: str) -> str | None:
    """Возвращает текст ошибки или None, если реквизиты похожи на правду."""
    a = (address or "").strip()
    if not a:
        return "Пустое значение"
    if method == "card":
        digits = "".join(ch for ch in a if ch.isdigit())
        if not (13 <= len(digits) <= 19):
            return "Номер карты — 13–19 цифр"
        return None
    if method == "sbp":
        digits = "".join(ch for ch in a if ch.isdigit())
        if len(digits) != 11 or digits[0] not in "78":
            return "Телефон — 11 цифр, начинается с 7 или 8"
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
    import services.platega_api as pg
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
    unit = "₽" if method in ("card", "sbp") else "USDT"
    bank_line = (f"\nБанк: {payout.get('bank_name')}"
                 if payout.get("bank_name") else "")
    await message.reply_text(
        "💸 <b>Проверь выплату</b>\n\n"
        f"<blockquote>Сумма: <b>{_fmt_amount(amount, unit)}</b>\n"
        f"Куда: {pg.PAYOUT_METHODS[method]}{bank_line}\n"
        f"Реквизиты: <code>{_mask_address(method, address)}</code>"
        "</blockquote>\n\n"
        "<i>Выплата создаётся сразу после подтверждения. "
        "Сообщение с реквизитами лучше удалить из чата.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Вывести", callback_data="platega_payout_do"),
             InlineKeyboardButton("❌ Отмена", callback_data="platega_payouts")],
        ]),
    )


async def handle_platega_payout_do(query, context: ContextTypes.DEFAULT_TYPE):
    import services.platega_api as pg
    from core.database import add_payout_record
    payout = context.user_data.pop("payout", None)
    if not payout or not payout.get("address"):
        await query.edit_message_text(
            "❌ <b>Заявка потерялась</b> — начни выплату заново.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Выплаты", callback_data="platega_payouts")],
            ]),
        )
        return
    await query.edit_message_text("💸 Создаю выплату в Platega…")
    r = await pg.create_payout(
        payout["amount"], payout["method"], payout["address"],
        bank_id=payout.get("bank_id"),
    )
    if not r.get("ok"):
        await query.edit_message_text(
            _platega_error_text(r["error"]), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Выплаты", callback_data="platega_payouts"),
                 InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
            ]),
        )
        return
    method = payout["method"]
    unit = "₽" if method in ("card", "sbp") else "USDT"
    await add_payout_record(
        "platega", r.get("id"), method, payout["amount"], unit,
        r.get("status"), _mask_address(method, payout["address"]))
    lines = [
        "✅ <b>Выплата создана</b>", "",
        f"<blockquote>ID: <code>{r.get('id')}</code>\n"
        f"Сумма: <b>{_fmt_amount(payout['amount'], unit)}</b>\n"
        f"Статус: {_PAYOUT_STATUS.get((r.get('status') or '').lower(), r.get('status'))}\n"
        f"Реквизиты: <code>{_mask_address(method, payout['address'])}</code></blockquote>",
    ]
    if r.get("amount") is not None:
        lines.append(f"\nСписано с баланса: <b>{r['amount']} USDT</b>")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Выплаты", callback_data="platega_payouts"),
             InlineKeyboardButton("💰 Баланс", callback_data="platega_balance")],
        ]),
    )


# ── Настройки Platega ─────────────────────────────────────────────────────
# ВНИМАНИЕ: эти значения API Platega не отдаёт — их нельзя ни прочитать,
# ни изменить из бота. Экран показывает их так, как надо настроить
# в кабинете. Поменяешь что-то в кабинете — сверь и этот экран.
# Callback URL — единственный, общий для всех событий.

async def handle_platega_settings(query, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    lines = [
        "🏬 <b>Настройки Platega</b>", "",
        "<i>Эти настройки живут только в кабинете Platega — API их не отдаёт, "
        "поэтому бот показывает, как должно быть настроено. "
        "Меняется всё только в кабинете.</i>", "",
        "<blockquote>"
        f"Merchant ID: <code>{_mask(cfg.get('platega_merchant_id'))}</code>\n"
        "Способы оплаты: СБП, карта, крипта — выбирает плательщик на форме\n"
        "После оплаты: https://vpn.drbl.tech/pay/success/\n"
        "При неуспехе: https://vpn.drbl.tech/pay/fail/\n"
        "Кнопка «вернуться»: https://vpn.drbl.tech/pay/back/\n"
        "Колбэк (Callback URL): https://vpn.drbl.tech/api/webhooks/platega\n"
        "Логотип формы: https://vpn.drbl.tech/logo.png"
        "</blockquote>", "",
        "<i>Бот сам подставляет адреса /pay/* в каждый счёт, но впиши "
        "Callback URL в кабинете — без него оплаты подтверждаются "
        "только опросом раз в минуту.</i>",
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть кабинет Platega",
                                  url="https://app.platega.io/")],
            [InlineKeyboardButton("◀️ Назад", callback_data="platega_menu")],
        ]),
    )
