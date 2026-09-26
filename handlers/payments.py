"""Раздел «Оплаты»: сводка по деньгам и список платежей."""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import (
    payments_summary, list_payments, get_payment_full, user_payments,
)
from paidsub.time_parser import fmt_duration

PROVIDER_LABELS = {
    "platega": "Platega",
    "manual": "вручную",
}

STATUS_LABELS = {
    "paid": "✅ оплачен",
    "pending": "⏳ ожидает оплаты",
    "canceled": "❌ отменён",
    "expired": "⌛️ просрочен",
    "error": "⚠️ ошибка",
    "chargebacked": "↩️ возврат",
    "refunded": "↩️ возвращён",
    "refund_pending": "⏳ возврат в обработке",
}

FILTERS = {
    "paid": "✅ Оплаченные",
    "pending": "⏳ Ожидают",
    "failed": "❌ Неуспешные",
    "refunds": "↩️ Возвраты",
    "all": "📋 Все",
}


def _fmt_ts(raw: str) -> str:
    if not raw:
        return "—"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).strftime("%d.%m %H:%M")
        except ValueError:
            continue
    return raw[:16]


def _who(first_name, username, tg_id) -> str:
    # имя человек задаёт сам: без экранирования «<» ломает всю разметку экрана
    from html import escape
    name = escape(str(first_name or tg_id))
    return f"{name} (@{escape(username)})" if username else name


async def handle_payments_menu(query, context: ContextTypes.DEFAULT_TYPE = None,
                               status: str = "paid", page: int = 1):
    if context:
        context.user_data.pop("state", None)

    s = await payments_summary()
    rows, total_pages = await list_payments(page, status)

    money = [
        f"📅 Сегодня: <b>{s['today'][1]} ₽</b>  ·  {s['today'][0]} шт.",
        f"📆 7 дней: <b>{s['week'][1]} ₽</b>  ·  {s['week'][0]} шт.",
        f"🗓 30 дней: <b>{s['month'][1]} ₽</b>  ·  {s['month'][0]} шт.",
        f"💵 Всего: <b>{s['total_sum']} ₽</b>  ·  {s['total_count']} шт.",
        f"🧾 Средний чек: <b>{s['avg']} ₽</b>  ·  платящих: <b>{s['payers']}</b>",
    ]
    if s["by_provider"]:
        parts = [f"{PROVIDER_LABELS.get(p, p)} {c} ({sm} ₽)"
                 for p, c, sm in s["by_provider"]]
        money.append(f"💳 {' · '.join(parts)}")
    lines = ["💰 <b>Оплаты</b>", "", "<blockquote>" + "\n".join(money) + "</blockquote>"]

    issues = []
    if s["pending_count"]:
        issues.append(f"⏳ Ожидают оплаты: <b>{s['pending_count']}</b> на <b>{s['pending_sum']} ₽</b>")
    if s["failed_count"]:
        issues.append(f"❌ Неуспешных: <b>{s['failed_count']}</b>")
    if s.get("refund_count"):
        issues.append(f"↩️ Возвратов: <b>{s['refund_count']}</b> на <b>{s['refund_sum']} ₽</b>")
    if issues:
        lines += [""] + issues

    lines.append(f"\n<b>{FILTERS.get(status, '')}</b>  ·  <i>стр. {page} из {total_pages}</i>")
    if not rows:
        lines.append("<blockquote>Здесь пока пусто.</blockquote>")

    kb = []
    for (p_id, tg_id, provider, amount, st, ts,
         first_name, username, promo, period) in rows:
        icon = STATUS_LABELS.get(st, st).split()[0]
        promo_mark = " 🎟" if promo else ""
        kb.append([InlineKeyboardButton(
            f"{icon} {amount} ₽{promo_mark} · {_who(first_name, username, tg_id)} · {_fmt_ts(ts)}",
            callback_data=f"payment_view:{p_id}",
        )])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"payments:{status}:{page - 1}"))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"payments:{status}:{page + 1}"))
    if nav:
        kb.append(nav)

    switch = [InlineKeyboardButton(
        ("• " if key == status else "") + label.split()[1],
        callback_data=f"payments:{key}:1",
    ) for key, label in FILTERS.items()]
    kb.append(switch[:2])
    kb.append(switch[2:])

    kb.append([InlineKeyboardButton("📈 По дням", callback_data="payment_stats:30"),
               InlineKeyboardButton("◀️ В админку", callback_data="admin_panel")])

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def handle_payment_view(query, payment_id: int):
    p = await get_payment_full(payment_id)
    if not p:
        await query.answer("Платёж не найден", show_alert=True)
        return
    (p_id, tg_id, provider, ext_id, amount, period, promo,
     status, pay_url, error, created, paid, first_name, username) = p

    lines = [
        f"💰 <b>Платёж #{p_id}</b>\n",
        f'👤 <a href="tg://user?id={tg_id}">{_who(first_name, username, tg_id)}</a>',
        f"🆔 <code>{tg_id}</code>",
        f"💵 Сумма: <b>{amount} ₽</b>",
    ]
    if period:
        lines.append(f"⏱ Оплачен период: <b>{fmt_duration(period)}</b>")
    if promo:
        lines.append(f"🎟 Промокод: <b>{promo}</b>")
    lines.append(f"💳 Способ: <b>{PROVIDER_LABELS.get(provider, provider)}</b>")
    lines.append(f"📌 Статус: <b>{STATUS_LABELS.get(status, status)}</b>")
    lines.append(f"🕐 Создан: {_fmt_ts(created)}")
    if paid:
        lines.append(f"✅ Оплачен: {_fmt_ts(paid)}")
    if ext_id and not ext_id.startswith("manual-"):
        lines.append(f"🔖 ID транзакции:\n<code>{ext_id}</code>")
    if error:
        lines.append(f"\n⚠️ <code>{error}</code>")

    kb = [[InlineKeyboardButton("🔍 Профиль юзера", callback_data=f"user_profile:{tg_id}")]]
    if status == "pending" and pay_url:
        kb.append([InlineKeyboardButton("🔗 Ссылка на оплату", url=pay_url)])
    if provider == "platega" and status == "paid" and ext_id:
        kb.append([InlineKeyboardButton("💸 Вернуть деньги", callback_data=f"refund_start:{p_id}")])
    kb.append([InlineKeyboardButton("◀️ К оплатам", callback_data="payments:paid:1")])

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def user_payments_block(tg_id: int) -> str:
    """Короткая сводка по оплатам для карточки юзера."""
    rows, cnt, total = await user_payments(tg_id, limit=5)
    if not cnt and not rows:
        return ""
    lines = [f"\n💰 Оплат: <b>{cnt}</b> на <b>{total} ₽</b>"]
    for _id, provider, amount, status, ts, promo in rows:
        if status != "paid":
            continue
        promo_mark = f" 🎟{promo}" if promo else ""
        lines.append(
            f"     {amount} ₽ · {PROVIDER_LABELS.get(provider, provider)} "
            f"· {_fmt_ts(ts)}{promo_mark}"
        )
    return "\n".join(lines)


# ── Возвраты ─────────────────────────────────────────────────────────────────

async def handle_refund_start(query, payment_id: int):
    """Проверяет, можно ли вернуть платёж, и спрашивает, что делать со сроком."""
    import platega_api as pg
    p = await get_payment_full(payment_id)
    if not p:
        await query.answer("Платёж не найден", show_alert=True)
        return
    (p_id, tg_id, provider, ext_id, amount, period, promo,
     status, _url, _err, _created, _paid, first_name, username) = p
    if provider != "platega" or status != "paid" or not ext_id:
        await query.answer("Возврат доступен только для оплаченных через Platega",
                           show_alert=True)
        return

    back = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ К платежу", callback_data=f"payment_view:{p_id}")],
    ])
    await query.edit_message_text("🔎 Проверяю возможность возврата...")
    chk = await pg.refund_supported(ext_id)
    if not chk["ok"]:
        await query.edit_message_text(
            f"❌ Не удалось проверить возврат:\n<code>{chk['error']}</code>",
            parse_mode="HTML", reply_markup=back)
        return
    if not chk["supported"]:
        reason = chk.get("block_reason") or "Platega не сообщила причину"
        await query.edit_message_text(
            f"⛔ <b>Возврат недоступен</b>\n\nПричина: <code>{reason}</code>\n\n"
            "Частая причина — на балансе мерчанта не хватает средств: "
            "возврат оплачивается с баланса Platega.",
            parse_mode="HTML", reply_markup=back)
        return

    lines = [
        f"💸 <b>Возврат платежа #{p_id}</b>\n",
        f"👤 {_who(first_name, username, tg_id)}",
        f"💵 Вернётся клиенту: <b>{amount} ₽</b>",
    ]
    if chk.get("deduct_usdt") is not None:
        lines.append(f"🏦 Спишется с баланса: <b>{chk['deduct_usdt']} USDT</b>")
    if chk.get("penalty_usdt"):
        lines.append(f"⚠️ Штраф: <b>{chk['penalty_usdt']} USDT</b>")
    if period:
        lines.append(f"\nОплаченный период: <b>{fmt_duration(period)}</b>")
    lines.append("\nЧто сделать с подпиской?")

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Вернуть и отозвать срок",
                                  callback_data=f"refund_do:{p_id}:1")],
            [InlineKeyboardButton("💸 Вернуть, срок оставить",
                                  callback_data=f"refund_do:{p_id}:0")],
            [InlineKeyboardButton("❌ Нет", callback_data=f"payment_view:{p_id}"),
             InlineKeyboardButton("◀️ Назад", callback_data="payments:paid:1")],
        ]),
    )


async def handle_refund_do(query, context: ContextTypes.DEFAULT_TYPE,
                           payment_id: int, revoke: bool):
    import platega_api as pg
    from database import mark_refund_pending

    p = await get_payment_full(payment_id)
    if not p or p[7] != "paid":
        await query.answer("Платёж уже не в статусе «оплачен»", show_alert=True)
        return

    back = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ К платежу", callback_data=f"payment_view:{payment_id}")],
    ])
    await query.edit_message_text("⏳ Отправляю возврат в Platega...")
    res = await pg.refund(p[3])
    if not res["ok"]:
        await query.edit_message_text(
            f"❌ Возврат не прошёл:\n<code>{res['error']}</code>",
            parse_mode="HTML", reply_markup=back)
        return

    # выбор фиксируем сразу: итог может прийти позже статусом CHARGEBACKED,
    # и довести возврат должна фоновая сверка — даже после перезапуска бота
    await mark_refund_pending(payment_id, revoke)

    if res["accepted"]:
        await finalize_refund(context, payment_id, revoke)
        await query.edit_message_text(
            "✅ <b>Возврат выполнен</b>\n" +
            ("Оплаченный срок отозван." if revoke else "Срок подписки оставлен."),
            parse_mode="HTML", reply_markup=back)
        return

    msg = res.get("message") or "Возврат в обработке"
    await query.edit_message_text(
        f"⏳ <b>Возврат принят в обработку</b>\n\n{msg}\n\n"
        "Как только Platega его проведёт, бот сам обновит платёж"
        + (" и отзовёт срок." if revoke else "."),
        parse_mode="HTML", reply_markup=back)


async def finalize_refund(context, payment_id: int, revoke: bool | None = None) -> None:
    """Доводит возврат до конца: статус, срок, уведомления.

    revoke=None — берётся выбор, сохранённый при запуске возврата из бота. Если
    его нет (возврат сделали в личном кабинете), решает настройка
    refund_revokes_period.
    """
    from config import load_config, ADMIN_ID
    from database import claim_refund, get_refund_revoke
    from log_channel import send_log

    p = await get_payment_full(payment_id)
    if not p:
        return
    (p_id, tg_id, _prov, _ext, amount, period, _promo,
     _status, _url, _err, _created, _paid, first_name, username) = p

    if revoke is None:
        stored = await get_refund_revoke(p_id)
        revoke = bool(stored) if stored is not None else bool(
            load_config().get("refund_revokes_period", True))

    # атомарный переход: если возврат уже довели, второй раз ничего не делаем
    if not await claim_refund(p_id):
        return

    period_line = ""
    if revoke and period:
        from paidsub.handlers import revoke_paid_period
        rv = await revoke_paid_period(tg_id, period, context,
                                      reason=f"Возврат платежа #{p_id}")
        period_line = (f"\n📅 Срок отозван, новая дата: <b>{rv['expire']}</b>"
                       if rv.get("ok") else
                       f"\n⚠️ Срок отозвать не удалось: {rv.get('error')}")
    elif period:
        period_line = "\n📅 Срок подписки оставлен без изменений"

    admin_text = (
        f"↩️ <b>Возврат по платежу #{p_id}</b>\n\n"
        f"👤 {_who(first_name, username, tg_id)} (<code>{tg_id}</code>)\n"
        f"💵 {amount} ₽{period_line}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="HTML")
    except Exception:
        pass
    await send_log(context.bot, admin_text)

    user_text = (
        f"↩️ <b>Возврат {amount} ₽ оформлен.</b>\n\n"
        "Деньги вернутся плательщику — срок зачисления зависит от банка."
    )
    if revoke and period:
        user_text += "\nОплаченный срок подписки отменён."
    try:
        await context.bot.send_message(chat_id=tg_id, text=user_text, parse_mode="HTML")
    except Exception:
        pass
