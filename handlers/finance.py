"""Раздел «Финансы» → «🖥 Серверы»: учёт ежемесячных расходов.

Админ добавляет серверы, за которые платит (название, цена в рублях,
день месяца). В день оплаты в 23:00 бот спрашивает, оплачен ли сервер,
и записывает ответ. Экран «Финансы» сводит доходы (оплаченные счета)
и расходы (серверы) за месяц в прибыль.
"""

import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.database import (
    add_server, delete_server, finance_summary, get_server,
    get_server_payment, servers_with_status,
    set_server_payment, update_server_field,
)
from core.states import (
    AWAITING_SERVER_DAY, AWAITING_SERVER_EDIT_DAY,
    AWAITING_SERVER_EDIT_PRICE, AWAITING_SERVER_NAME, AWAITING_SERVER_PRICE,
)

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
MSK = ZoneInfo("Europe/Moscow")


def current_period() -> str:
    """Текущий месяц 'YYYY-MM' по Москве."""
    return datetime.now(MSK).strftime("%Y-%m")


def month_title(period: str | None = None) -> str:
    """«Ноябрь 2026» для текущего месяца или заданного 'YYYY-MM'."""
    now = datetime.now(MSK)
    if period:
        year, month = map(int, period.split("-"))
    else:
        year, month = now.year, now.month
    return f"{MONTHS_RU[month - 1]} {year}"


def fmt_price(value: int) -> str:
    """1 500 ₽ — с пробелами-разделителями."""
    return f"{int(value):,}".replace(",", " ") + " ₽"


def _is_due_day(pay_day: int, today: datetime) -> bool:
    """День оплаты сегодня? 31-е в коротком месяце — в последний день."""
    last = calendar.monthrange(today.year, today.month)[1]
    return today.day == pay_day or (pay_day > last and today.day == last)


def _status_text(status: str | None, day: int, today_day: int) -> str:
    if status == "paid":
        return "✅ оплачен"
    if status == "unpaid":
        return "❌ не оплачен"
    if day == today_day:
        return "⏳ сегодня"
    if day > today_day:
        return f"📅 {day} числа"
    return "❓ не отмечен"


async def handle_servers_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    """Список серверов со статусом оплаты за текущий месяц."""
    if context:
        context.user_data.pop("state", None)
    period = current_period()
    today = datetime.now(MSK)
    rows = await servers_with_status(period)
    summary = await finance_summary(period)

    lines = ["🖥 <b>Серверы</b>", "",
             f"📅 {month_title(period)}: расходы "
             f"<b>{fmt_price(summary['expenses'])}</b> в месяц", ""]
    if not rows:
        lines.append("<i>Пока нет ни одного сервера — добавь первый.</i>")
    for s in rows:
        lines.append(f"• <b>{s['name']}</b> — {fmt_price(s['price'])} · "
                     f"{s['day']} числа · {_status_text(s['status'], s['day'], today.day)}")

    kb = []
    for s in rows:
        kb.append([InlineKeyboardButton(
            f"🖥 {s['name']} — {fmt_price(s['price'])}",
            callback_data=f"server_view:{s['id']}")])
    kb.append([InlineKeyboardButton("➕ Добавить сервер", callback_data="server_add")])
    kb.append([InlineKeyboardButton("◀️ К финансам", callback_data="pay_provider_menu")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def handle_server_view(query, server_id: int):
    """Карточка сервера: цена, день оплаты, статус за месяц, действия."""
    s = await get_server(server_id)
    if not s:
        await query.answer("Сервер не найден", show_alert=True)
        return
    _id, name, price, day, _active = s
    period = current_period()
    today = datetime.now(MSK)
    status = await get_server_payment(_id, period)
    lines = [f"🖥 <b>{name}</b>", "",
             f"💵 Цена: <b>{fmt_price(price)}</b> в месяц",
             f"📅 День оплаты: <b>{day} числа</b>",
             f"📆 {month_title(period)}: <b>{_status_text(status, day, today.day)}</b>"]
    kb = [
        [InlineKeyboardButton("✅ Оплачен", callback_data=f"server_mark:{_id}:paid"),
         InlineKeyboardButton("❌ Не оплачен", callback_data=f"server_mark:{_id}:unpaid")],
        [InlineKeyboardButton("✏️ Цена", callback_data=f"server_edit_price:{_id}"),
         InlineKeyboardButton("📅 День", callback_data=f"server_edit_day:{_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"server_del:{_id}")],
        [InlineKeyboardButton("◀️ К серверам", callback_data="servers_menu")],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True,
    )


async def handle_server_add(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_SERVER_NAME
    context.user_data.pop("server_new", None)
    await query.edit_message_text(
        "➕ <b>Новый сервер</b>\n\nПришли <b>название</b> сервера одним сообщением "
        "(например, <code>Финляндия</code> или <code>violent-child</code>).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К серверам", callback_data="servers_menu")],
        ]),
    )


async def handle_server_edit_price(query, context: ContextTypes.DEFAULT_TYPE,
                                   server_id: int):
    s = await get_server(server_id)
    if not s:
        await query.answer("Сервер не найден", show_alert=True)
        return
    context.user_data["state"] = AWAITING_SERVER_EDIT_PRICE
    context.user_data["server_edit_id"] = server_id
    await query.edit_message_text(
        f"✏️ <b>{s[1]}</b>\n\nТекущая цена: <b>{fmt_price(s[2])}</b> в месяц.\n"
        "Пришли <b>новую цену в рублях</b> одним сообщением (только число).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data=f"server_view:{server_id}")],
        ]),
    )


async def handle_server_edit_day(query, context: ContextTypes.DEFAULT_TYPE,
                                 server_id: int):
    s = await get_server(server_id)
    if not s:
        await query.answer("Сервер не найден", show_alert=True)
        return
    context.user_data["state"] = AWAITING_SERVER_EDIT_DAY
    context.user_data["server_edit_id"] = server_id
    await query.edit_message_text(
        f"📅 <b>{s[1]}</b>\n\nТекущий день оплаты: <b>{s[3]} числа</b>.\n"
        "Пришли <b>новый день месяца</b> одним сообщением (число от 1 до 31).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data=f"server_view:{server_id}")],
        ]),
    )


async def handle_server_del(query, server_id: int):
    s = await get_server(server_id)
    if not s:
        await query.answer("Сервер не найден", show_alert=True)
        return
    await query.edit_message_text(
        f"🗑 Удалить сервер <b>{s[1]}</b> ({fmt_price(s[2])} в месяц)?\n\n"
        "История оплат за прошлые месяцы останется в базе.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Да, удалить",
                                  callback_data=f"server_del_ok:{server_id}")],
            [InlineKeyboardButton("◀️ Отмена", callback_data=f"server_view:{server_id}")],
        ]),
    )


async def handle_server_del_ok(query, server_id: int):
    await delete_server(server_id)
    await query.answer("Сервер удалён")
    await handle_servers_menu(query)


async def handle_server_mark(query, server_id: int, status: str):
    """Ручная отметка: оплачен / не оплачен за текущий месяц."""
    s = await get_server(server_id)
    if not s:
        await query.answer("Сервер не найден", show_alert=True)
        return
    await set_server_payment(server_id, current_period(), status,
                             marked_by=query.from_user.id)
    await query.answer("✅ Оплачен" if status == "paid" else "❌ Не оплачен")
    await handle_server_view(query, server_id)


async def handle_server_paid_answer(query, server_id: int, answer: str):
    """Ответ на вечерний вопрос «оплачен?»: записывает и правит сообщение."""
    s = await get_server(server_id)
    if not s:
        await query.answer("Сервер не найден", show_alert=True)
        return
    status = "paid" if answer == "yes" else "unpaid"
    await set_server_payment(server_id, current_period(), status,
                             marked_by=query.from_user.id)
    text = (f"✅ <b>{s[1]}</b> — оплачен, {fmt_price(s[2])}."
            if status == "paid" else
            f"❌ <b>{s[1]}</b> — НЕ оплачен, {fmt_price(s[2])}. "
            "Отметь, когда оплатишь: Финансы → Серверы.")
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К серверам", callback_data="servers_menu")],
        ]),
    )


def _parse_price(text: str) -> int | None:
    cleaned = text.strip().replace(" ", "").replace("\u00a0", "").rstrip("₽р")
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if value > 0 else None


def _parse_day(text: str) -> int | None:
    cleaned = text.strip()
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if 1 <= value <= 31 else None


async def apply_server_step(message, context: ContextTypes.DEFAULT_TYPE,
                            state: str, text: str):
    """Шаги мастера добавления сервера и правки цены/дня. Вызывается из
    handle_text по состоянию из core.states."""
    if state == AWAITING_SERVER_NAME:
        name = text.strip()
        if not name or len(name) > 64:
            await message.reply_text(
                "Название — от 1 до 64 символов. Пришли ещё раз.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ К серверам", callback_data="servers_menu")],
                ]),
            )
            return
        context.user_data["server_new"] = {"name": name}
        context.user_data["state"] = AWAITING_SERVER_PRICE
        await message.reply_text(
            f"Сервер: <b>{name}</b>\n\nПришли <b>цену в рублях в месяц</b> "
            "одним сообщением (только число).",
            parse_mode="HTML",
        )
        return

    if state == AWAITING_SERVER_PRICE:
        price = _parse_price(text)
        if price is None:
            await message.reply_text(
                "Цена — только число больше нуля, например <code>1500</code>. "
                "Пришли ещё раз.")
            return
        context.user_data["server_new"]["price"] = price
        context.user_data["state"] = AWAITING_SERVER_DAY
        await message.reply_text(
            "Пришли <b>день месяца</b>, когда оплачиваешь сервер "
            "(число от 1 до 31).",
            parse_mode="HTML",
        )
        return

    if state == AWAITING_SERVER_DAY:
        day = _parse_day(text)
        if day is None:
            await message.reply_text(
                "День — число от 1 до 31. Пришли ещё раз.")
            return
        new = context.user_data.pop("server_new", {})
        context.user_data.pop("state", None)
        sid = await add_server(new["name"], new["price"], day)
        await message.reply_text(
            f"✅ Сервер <b>{new['name']}</b> добавлен: "
            f"{fmt_price(new['price'])} в месяц, оплата {day} числа.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🖥 К серверам", callback_data="servers_menu")],
            ]),
        )
        return

    if state == AWAITING_SERVER_EDIT_PRICE:
        price = _parse_price(text)
        sid = context.user_data.get("server_edit_id")
        if price is None or not sid:
            await message.reply_text(
                "Цена — только число больше нуля, например <code>1500</code>. "
                "Пришли ещё раз.")
            return
        context.user_data.pop("state", None)
        await update_server_field(sid, "price_rub", price)
        s = await get_server(sid)
        await message.reply_text(
            f"✅ Цена сервера <b>{s[1]}</b> — теперь {fmt_price(price)} в месяц.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К серверу", callback_data=f"server_view:{sid}")],
            ]),
        )
        return

    if state == AWAITING_SERVER_EDIT_DAY:
        day = _parse_day(text)
        sid = context.user_data.get("server_edit_id")
        if day is None or not sid:
            await message.reply_text(
                "День — число от 1 до 31. Пришли ещё раз.")
            return
        context.user_data.pop("state", None)
        await update_server_field(sid, "pay_day", day)
        s = await get_server(sid)
        await message.reply_text(
            f"✅ День оплаты сервера <b>{s[1]}</b> — теперь {day} числа.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К серверу", callback_data=f"server_view:{sid}")],
            ]),
        )
        return


async def servers_due_today() -> list[dict]:
    """Активные серверы, у которых сегодня день оплаты и ещё нет отметки
    за текущий месяц. 31-е в коротком месяце — в последний день."""
    today = datetime.now(MSK)
    period = today.strftime("%Y-%m")
    due = []
    for s in await servers_with_status(period):
        if s["status"] is not None:
            continue
        if _is_due_day(s["day"], today):
            due.append(s)
    return due


async def server_payment_reminder_job(ctx):
    """23:00 мск в день оплаты: спрашивает админа, оплачен ли сервер.

    Задаётся в bot.py через job_queue.run_daily. Молчит, если сегодня
    никто не платится или отметка уже стоит.
    """
    due = await servers_due_today()
    if not due:
        return
    from config import ADMIN_ID
    for s in due:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Да, оплачен",
                                 callback_data=f"server_paid:{s['id']}:yes"),
            InlineKeyboardButton("❌ Нет",
                                 callback_data=f"server_paid:{s['id']}:no"),
        ]])
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🖥 <b>{s['name']}</b> — сегодня день оплаты: "
                     f"<b>{fmt_price(s['price'])}</b>.\nОплачен?",
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception:
            pass
