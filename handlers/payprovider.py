"""Раздел «Платёжная система»: настройки приёма платежей через Platega.

Бот сам выставляет счёт и сам засчитывает оплату — подтверждать вручную
не нужно. Другого способа приёма платежей в боте нет.

Способ оплаты (СБП, карта, крипта) человек выбирает сам на форме Platega
(счёт создаётся через /v2 без заданного способа). Настройки кассы
(способы, комиссия, редиректы, Callback URL) живут только в кабинете
Platega — API их не отдаёт и не меняет, поэтому в боте они показаны
отдельным экраном «🏬 Настройки Platega» как справка. А вот баланс
и возвраты — живые данные из API.

Возвраты у Platega ЕСТЬ (в отличие от anore): проверка → запуск →
итог приходит колбэком (статус CHARGEBACKED) или виден опросом.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config, save_config
from core.keyboards import back_admin
from core.states import (
    AWAITING_PLATEGA_MERCHANT, AWAITING_PLATEGA_SECRET,
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
    return f"💳 Platega  ·  merchant <code>{_mask(merchant)}</code>"


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
    """Экран «Платёжная система»: ключи, баланс, возвраты."""
    if context:
        context.user_data.pop("state", None)
    cfg = load_config()

    import services.platega_api as pg
    ready = pg.is_configured()
    lines = ["💳 <b>Платёжная система</b>", "",
             f"<blockquote>Приём платежей: <b>Platega</b>\n"
             f"🏬 Merchant ID: <code>{_mask(cfg.get('platega_merchant_id'))}</code>\n"
             f"🔑 API ключ: <code>{_mask(cfg.get('platega_secret'))}</code></blockquote>", "",
             "<i>Бот сам выставляет счёт и сам засчитывает оплату — "
             "подтверждать вручную не нужно.</i>",
             "<i>Оплата подтверждается колбэком мгновенно, опрос — "
             "страховка, если колбэк не дойдёт. Счёт живёт 15 минут.</i>",
             "<i>Возвраты работают через API: кнопка «↩️ Вернуть» "
             "на карточке оплаченного счёта в «💰 Оплаты».</i>"]
    if not ready:
        lines.append("\n⚠️ <b>Не хватает данных</b> — заполни Merchant ID "
                     "и API ключ из кабинета Platega (Настройки → API-ключи). "
                     "Пока их нет, клиенты не смогут оплатить подписку.")

    rows = [
        [InlineKeyboardButton("🏬 Merchant ID", callback_data="platega_set_merchant"),
         InlineKeyboardButton("🔑 API ключ", callback_data="platega_set_secret")],
        [InlineKeyboardButton("🔌 Проверить", callback_data="platega_test"),
         InlineKeyboardButton("💰 Баланс", callback_data="platega_balance")],
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
        "🔑 <b>API ключ Platega</b>\n\n"
        "<i>Пришли API ключ из личного кабинета Platega "
        "(Настройки → API-ключи) одним сообщением.</i>\n\n"
        "⚠️ Сообщение с ключом лучше потом удалить из чата.",
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
            "<i>Проверь Merchant ID и API ключ в личном кабинете Platega.</i>"
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
    """Сохраняет Merchant ID или API ключ, введённый в чате."""
    value = (raw or "").strip()
    labels = {
        "platega_merchant_id": "Merchant ID",
        "platega_secret": "API ключ",
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


# ── Баланс и счета ────────────────────────────────────────────────────────
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
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
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
