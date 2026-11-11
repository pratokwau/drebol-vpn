"""Раздел «Оплаты»: сводка по деньгам и список платежей."""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.database import (
    payments_summary, list_payments, get_payment_full, user_payments,
)
from paidsub.time_parser import fmt_duration

PROVIDER_LABELS = {
    "anore": "Anore",
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

    # Оплаты теперь живут внутри Финансов: админ возвращается туда,
    # а помощник — в свою панель (admin_panel показывает её помощникам,
    # а pay_provider_menu им закрыт — там ключи API).
    from config import ADMIN_ID
    if query.from_user.id == ADMIN_ID:
        back_btn = InlineKeyboardButton("◀️ В Финансы",
                                        callback_data="pay_provider_menu")
    else:
        back_btn = InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")
    kb.append([InlineKeyboardButton("📈 По дням", callback_data="payment_stats:30"),
               back_btn])

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
    if provider == "platega" and ext_id and not ext_id.startswith("manual-"):
        kb.append([InlineKeyboardButton("🔍 Проверить в Platega",
                                        callback_data=f"platega_payment:{ext_id}")])
    if status == "pending" and pay_url:
        kb.append([InlineKeyboardButton("🔗 Ссылка на оплату", url=pay_url)])
    kb.append([InlineKeyboardButton("◀️ К оплатам", callback_data="payments:paid:1")])

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


# ── Подтверждение оплаты ───────────────────────────────────────────────────

async def confirm_provider_payment(bot, p) -> dict:
    """Засчитывает оплаченный счёт.

    p — строка get_pending_payments / get_payment_by_external:
    (id, tg_id, provider, external_id, amount, period, promo,
    created_at, kind, extra, gift_tg_id). Общая для опроса и вебхука.

    Двойное начисление исключено атомарным claim: кто первым перевёл
    счёт из pending в paid, тот и начисляет; второй подтверждающий
    (вебхук и опрос одновременно) получает {"already": True} и не трогает
    ни подписку, ни журнал. Раньше статус ставился безусловным UPDATE —
    опрос, уже взявший счёт в список pending, подтверждал его второй раз.
    """
    from types import SimpleNamespace

    from config import ADMIN_ID
    from core.database import claim_payment_paid, record_payment_credit, set_payment_status
    from paidsub.handlers import (
        apply_paid_payment, apply_devices_payment, apply_gift_payment,
    )

    pay_id, tg_id, amount, period, promo = p[0], p[1], p[4], p[5], p[6]
    kind = p[8] if len(p) > 8 else "period"
    extra = p[9] if len(p) > 9 else 0
    gift_tg = p[10] if len(p) > 10 else None

    # атомарный захват счёта: второй подтверждающий сюда не пройдёт
    if not await claim_payment_paid(pay_id):
        return {"ok": False, "already": True}
    # apply_* ждут context с .bot — бот напрямую им не подходит
    ctx = SimpleNamespace(bot=bot)
    try:
        if kind == "devices":
            res = await apply_devices_payment(tg_id, extra, ctx, amount)
        elif gift_tg:
            res = await apply_gift_payment(
                gift_tg, tg_id, amount, ctx, promo_code=promo,
                source="Platega", period_seconds=period,
            )
        else:
            res = await apply_paid_payment(
                tg_id, amount, ctx, promo_code=promo,
                source="Platega", period_seconds=period,
            )
            # в счёте за срок ехал выбор устройств на новый период:
            # ставим ровно столько, сколько взяли. Ноль — человек от
            # них отказался, и это не ошибка
            if res.get("ok") and kind == "period_dev":
                dev = await apply_devices_payment(tg_id, extra, ctx, 0, mode="set")
                if not dev.get("ok"):
                    # срок начислен, слоты нет — молчать нельзя,
                    # человек за них заплатил
                    await set_payment_status(
                        pay_id, "paid",
                        f"устройства не начислены: {dev.get('error')}")
                    await bot.send_message(
                        chat_id=ADMIN_ID,
                        text=(
                            "⚠️ <b>Срок продлён, устройства не применены</b>\n\n"
                            f"👤 <code>{tg_id}</code> · выбрано {extra} устр.\n"
                            f"<code>{dev.get('error')}</code>\n\n"
                            "Добавь слоты вручную."
                        ),
                        parse_mode="HTML",
                    )
        if not res.get("ok"):
            await set_payment_status(pay_id, "paid", res.get("error"))
            gift_line = (f"🎁 Подарок для <code>{gift_tg}</code>\n"
                         if gift_tg else "")
            tail = ("Выдай подписку получателю вручную."
                    if gift_tg else "Продли подписку вручную.")
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ <b>Оплата получена, но не засчитана</b>\n\n"
                    f"👤 <code>{tg_id}</code> · {amount} ₽\n"
                    f"{gift_line}"
                    f"<code>{res.get('error')}</code>\n\n"
                    f"{tail}"
                ),
                parse_mode="HTML",
            )
            return {"ok": False, "error": res.get("error")}
    except Exception as e:
        await set_payment_status(pay_id, "paid", str(e)[:120])
        return {"ok": False, "error": str(e)[:120]}
    # начисление прошло — пишем в журнал: один счёт, одна запись.
    # Если запись уже есть (не должно случиться после claim) — молча пропускаем.
    await record_payment_credit(pay_id, tg_id, amount, period or 0)
    return {"ok": True}


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



async def finalize_refund(context, payment_id: int, revoke: bool | None = None) -> None:
    """Доводит возврат до конца: статус, срок, уведомления.

    revoke=None — берётся выбор, сохранённый при запуске возврата из бота. Если
    его нет (возврат сделали в личном кабинете), решает настройка
    refund_revokes_period.
    """
    from config import load_config, ADMIN_ID
    from core.database import claim_refund, get_refund_revoke
    from core.log_channel import send_log

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
        if not rv.get("ok"):
            period_line = f"\n⚠️ Срок отозвать не удалось: {rv.get('error')}"
        else:
            period_line = f"\n📅 Срок отозван, новая дата: <b>{rv['expire']}</b>"
            if rv.get("panel_error"):
                # молчать тут нельзя: в базе срок уменьшен, а в панели остался
                # старый — значит доступ у человека ещё живой
                from html import escape as _esc
                period_line += ("\n⚠️ <b>Панель не подтвердила</b>: "
                                f"<code>{_esc(str(rv['panel_error']))}</code>\n"
                                "Проверь срок клиента в панели руками.")
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
