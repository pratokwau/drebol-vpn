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
    "cloudpayments": "CloudPayments",
}

STATUS_LABELS = {
    "paid": "✅ оплачен",
    "pending": "⏳ ожидает оплаты",
    "canceled": "❌ отменён",
    "expired": "⌛️ просрочен",
    "error": "⚠️ ошибка",
    "chargebacked": "↩️ возврат",
}

FILTERS = {
    "paid": "✅ Оплаченные",
    "pending": "⏳ Ожидают",
    "failed": "❌ Неуспешные",
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
    name = first_name or str(tg_id)
    return f"{name} (@{username})" if username else name


async def handle_payments_menu(query, context: ContextTypes.DEFAULT_TYPE = None,
                               status: str = "paid", page: int = 1):
    if context:
        context.user_data.pop("state", None)

    s = await payments_summary()
    rows, total_pages = await list_payments(page, status)

    lines = ["💰 <b>Оплаты</b>\n"]
    lines.append(f"📅 Сегодня: <b>{s['today'][0]}</b> · <b>{s['today'][1]} ₽</b>")
    lines.append(f"📆 7 дней: <b>{s['week'][0]}</b> · <b>{s['week'][1]} ₽</b>")
    lines.append(f"🗓 30 дней: <b>{s['month'][0]}</b> · <b>{s['month'][1]} ₽</b>")
    lines.append(f"💵 Всего: <b>{s['total_count']}</b> · <b>{s['total_sum']} ₽</b>")
    lines.append(f"🧾 Средний чек: <b>{s['avg']} ₽</b> · платящих: <b>{s['payers']}</b>")

    if s["by_provider"]:
        parts = [f"{PROVIDER_LABELS.get(p, p)} {c} ({sm} ₽)"
                 for p, c, sm in s["by_provider"]]
        lines.append(f"💳 {' · '.join(parts)}")

    if s["pending_count"]:
        lines.append(
            f"\n⏳ Ожидают оплаты: <b>{s['pending_count']}</b> "
            f"на <b>{s['pending_sum']} ₽</b>"
        )
    if s["failed_count"]:
        lines.append(f"❌ Неуспешных: <b>{s['failed_count']}</b>")

    lines.append(f"\n<b>{FILTERS.get(status, '')}</b> — стр. {page}/{total_pages}")
    if not rows:
        lines.append("\nЗдесь пока пусто.")

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

    kb.append([InlineKeyboardButton("📊 По дням", callback_data="payment_stats:30")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])

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
