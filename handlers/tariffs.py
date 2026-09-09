"""Тарифы: варианты продления, которые клиент выбирает при оплате.

Пока ни одного активного тарифа нет, бот работает по старой схеме —
одна цена и один период из общих настроек.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import load_config
from keyboards import back_admin
from database import (
    add_tariff, list_tariffs, get_tariff, update_tariff_field, delete_tariff,
)
from paidsub.time_parser import parse_duration, fmt_duration
from states import (
    AWAITING_TARIFF_NAME, AWAITING_TARIFF_PERIOD, AWAITING_TARIFF_PRICE,
    AWAITING_TARIFF_EDIT_NAME, AWAITING_TARIFF_EDIT_PERIOD, AWAITING_TARIFF_EDIT_PRICE,
)

_PERIOD_HINT = (
    "Введи срок в свободной форме:\n"
    "<code>1 месяц</code>, <code>30 дней</code>, <code>3 месяца</code>, "
    "<code>1 год</code>, <code>7 дней</code>"
)


def _back_kb(cb: str = "tariffs_menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К тарифам", callback_data=cb)]])


async def handle_tariffs_menu(query, context: ContextTypes.DEFAULT_TYPE = None):
    if context:
        context.user_data.pop("state", None)
        context.user_data.pop("new_tariff", None)
    rows = await list_tariffs()
    cfg = load_config()

    lines = ["💰 <b>Тарифы</b>\n"]
    if not rows:
        price = cfg.get("paid_price", 0)
        period = cfg.get("paid_pay_period")
        lines.append(
            "Тарифов нет — клиент видит одну цену из общих настроек:\n"
            f"<b>{price} ₽</b> за <b>{fmt_duration(period) if period else '—'}</b>\n\n"
            "Добавь тарифы, чтобы клиент выбирал срок сам."
        )
    else:
        active = sum(1 for r in rows if r[4])
        lines.append(f"Всего: <b>{len(rows)}</b> · показываются клиенту: <b>{active}</b>\n")
        if not active:
            lines.append("⚠️ Ни один тариф не активен — клиент увидит цену из общих настроек.\n")
        lines.append("Нажми на тариф, чтобы изменить.")

    kb = []
    for t_id, name, period, price, is_active, _ in rows:
        mark = "✅" if is_active else "❌"
        kb.append([InlineKeyboardButton(
            f"{mark} {name} · {price} ₽ · {fmt_duration(period)}",
            callback_data=f"tariff_view:{t_id}",
        )])
    kb.append([InlineKeyboardButton("➕ Добавить тариф", callback_data="tariff_add")])
    kb.append([InlineKeyboardButton("◀️ К настройкам", callback_data="paid_sub_presets")])

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )


async def handle_tariff_view(query, tariff_id: int):
    t = await get_tariff(tariff_id)
    if not t:
        await query.answer("Тариф не найден", show_alert=True)
        return
    _, name, period, price, is_active, _ = t
    state = "✅ показывается клиенту" if is_active else "❌ скрыт от клиента"

    await query.edit_message_text(
        f"💰 <b>{name}</b>\n\n"
        f"💵 Цена: <b>{price} ₽</b>\n"
        f"⏱ Срок: <b>{fmt_duration(period)}</b>\n"
        f"📌 Статус: <b>{state}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "❌ Деактивировать" if is_active else "✅ Активировать",
                callback_data=f"tariff_toggle:{tariff_id}",
            )],
            [
                InlineKeyboardButton("💵 Цена", callback_data=f"tariff_price:{tariff_id}"),
                InlineKeyboardButton("⏱ Срок", callback_data=f"tariff_period:{tariff_id}"),
            ],
            [InlineKeyboardButton("✏️ Название", callback_data=f"tariff_name:{tariff_id}")],
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"tariff_del:{tariff_id}")],
            [InlineKeyboardButton("◀️ К тарифам", callback_data="tariffs_menu")],
        ]),
    )


async def handle_tariff_toggle(query, context, tariff_id: int):
    t = await get_tariff(tariff_id)
    if not t:
        await query.answer("Тариф не найден", show_alert=True)
        return
    await update_tariff_field(tariff_id, "active", 0 if t[4] else 1)
    await query.answer("Показывается клиенту" if not t[4] else "Скрыт от клиента")
    await handle_tariff_view(query, tariff_id)


async def handle_tariff_delete(query, tariff_id: int):
    t = await get_tariff(tariff_id)
    if not t:
        await query.answer("Тариф не найден", show_alert=True)
        return
    await query.edit_message_text(
        f"🗑 Удалить тариф <b>{t[1]}</b> ({t[3]} ₽ · {fmt_duration(t[2])})?\n\n"
        "<i>На уже оплаченные подписки это не влияет.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Да, удалить", callback_data=f"tariff_del_ok:{tariff_id}")],
            [InlineKeyboardButton("◀️ Отмена", callback_data=f"tariff_view:{tariff_id}")],
        ]),
    )


async def handle_tariff_delete_confirm(query, context, tariff_id: int):
    await delete_tariff(tariff_id)
    await query.answer("Тариф удалён")
    await handle_tariffs_menu(query, context)


# ── Добавление ───────────────────────────────────────────────────────────────

async def handle_tariff_add(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = AWAITING_TARIFF_NAME
    context.user_data["new_tariff"] = {}
    await query.edit_message_text(
        "➕ <b>Новый тариф</b>\n\n"
        "Шаг 1 из 3 — название, его увидит клиент.\n\n"
        "Например: <code>1 месяц</code>, <code>Полгода</code>, <code>Год</code>",
        parse_mode="HTML", reply_markup=_back_kb(),
    )


async def apply_new_step(message, context: ContextTypes.DEFAULT_TYPE, state: str, text: str):
    """Шаги мастера создания тарифа."""
    data = context.user_data.setdefault("new_tariff", {})

    if state == AWAITING_TARIFF_NAME:
        name = text.strip()
        if not name or len(name) > 40:
            await message.reply_text(
                "❌ Название до 40 символов. Ещё раз:", reply_markup=_back_kb()
            )
            context.user_data["state"] = AWAITING_TARIFF_NAME
            return
        data["name"] = name
        context.user_data["state"] = AWAITING_TARIFF_PERIOD
        await message.reply_text(
            f"✅ Название: <b>{name}</b>\n\nШаг 2 из 3 — срок.\n\n{_PERIOD_HINT}",
            parse_mode="HTML", reply_markup=_back_kb(),
        )
        return

    if state == AWAITING_TARIFF_PERIOD:
        seconds = parse_duration(text)
        if not seconds:
            await message.reply_text(
                f"❌ Не понял срок.\n\n{_PERIOD_HINT}",
                parse_mode="HTML", reply_markup=_back_kb(),
            )
            context.user_data["state"] = AWAITING_TARIFF_PERIOD
            return
        data["period"] = seconds
        context.user_data["state"] = AWAITING_TARIFF_PRICE
        await message.reply_text(
            f"✅ Срок: <b>{fmt_duration(seconds)}</b>\n\n"
            "Шаг 3 из 3 — цена в рублях (число):",
            parse_mode="HTML", reply_markup=_back_kb(),
        )
        return

    if state == AWAITING_TARIFF_PRICE:
        if not text.isdigit() or int(text) <= 0:
            await message.reply_text(
                "❌ Цена — целое число больше нуля. Ещё раз:", reply_markup=_back_kb()
            )
            context.user_data["state"] = AWAITING_TARIFF_PRICE
            return
        price = int(text)
        name, period = data.get("name"), data.get("period")
        context.user_data.pop("state", None)
        context.user_data.pop("new_tariff", None)
        if not name or not period:
            await message.reply_text("❌ Данные потеряны, начни заново.", reply_markup=back_admin())
            return

        await add_tariff(name, period, price)
        await message.reply_text(
            f"✅ <b>Тариф создан</b>\n\n"
            f"💰 {name}\n💵 {price} ₽\n⏱ {fmt_duration(period)}\n\n"
            "Он уже активен и виден клиентам.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Ещё тариф", callback_data="tariff_add")],
                [InlineKeyboardButton("◀️ К тарифам", callback_data="tariffs_menu")],
            ]),
        )


# ── Редактирование ───────────────────────────────────────────────────────────

async def handle_tariff_edit(query, context: ContextTypes.DEFAULT_TYPE,
                             tariff_id: int, field: str):
    t = await get_tariff(tariff_id)
    if not t:
        await query.answer("Тариф не найден", show_alert=True)
        return
    context.user_data["edit_tariff_id"] = tariff_id

    if field == "price":
        context.user_data["state"] = AWAITING_TARIFF_EDIT_PRICE
        body = f"💵 <b>Цена тарифа «{t[1]}»</b>\n\nСейчас: <b>{t[3]} ₽</b>\n\nВведи новую цену:"
    elif field == "period":
        context.user_data["state"] = AWAITING_TARIFF_EDIT_PERIOD
        body = f"⏱ <b>Срок тарифа «{t[1]}»</b>\n\nСейчас: <b>{fmt_duration(t[2])}</b>\n\n{_PERIOD_HINT}"
    else:
        context.user_data["state"] = AWAITING_TARIFF_EDIT_NAME
        body = f"✏️ <b>Название тарифа</b>\n\nСейчас: <b>{t[1]}</b>\n\nВведи новое:"

    await query.edit_message_text(
        body, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Отмена", callback_data=f"tariff_view:{tariff_id}")],
        ]),
    )


async def apply_edit(message, context: ContextTypes.DEFAULT_TYPE, state: str, text: str):
    tariff_id = context.user_data.pop("edit_tariff_id", None)
    context.user_data.pop("state", None)
    if not tariff_id:
        await message.reply_text("❌ Тариф потерян, начни заново.", reply_markup=back_admin())
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ К тарифу", callback_data=f"tariff_view:{tariff_id}")],
    ])

    if state == AWAITING_TARIFF_EDIT_PRICE:
        if not text.isdigit() or int(text) <= 0:
            await message.reply_text("❌ Цена — целое число больше нуля.", reply_markup=kb)
            return
        await update_tariff_field(tariff_id, "price", int(text))
        await message.reply_text(f"✅ Цена: <b>{text} ₽</b>", parse_mode="HTML", reply_markup=kb)

    elif state == AWAITING_TARIFF_EDIT_PERIOD:
        seconds = parse_duration(text)
        if not seconds:
            await message.reply_text(f"❌ Не понял срок.\n\n{_PERIOD_HINT}",
                                     parse_mode="HTML", reply_markup=kb)
            return
        await update_tariff_field(tariff_id, "period_seconds", seconds)
        await message.reply_text(f"✅ Срок: <b>{fmt_duration(seconds)}</b>",
                                 parse_mode="HTML", reply_markup=kb)

    else:
        name = text.strip()
        if not name or len(name) > 40:
            await message.reply_text("❌ Название до 40 символов.", reply_markup=kb)
            return
        await update_tariff_field(tariff_id, "name", name)
        await message.reply_text(f"✅ Название: <b>{name}</b>", parse_mode="HTML", reply_markup=kb)
