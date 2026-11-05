"""Winback: возвращаем тех, у кого подписка закончилась.

Две волны. Первая уходит через несколько дней после окончания — с небольшой
скидкой. Если человек не вернулся, через заданный срок идёт вторая, со скидкой
побольше: это последняя попытка, дальше бот молчит.

Промокод у каждого свой и живёт недолго — иначе письмо превращается в вечный
купон, и повода возвращаться сейчас у человека нет.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from config import load_config, save_config
from states import (
    AWAITING_WINBACK_DAYS, AWAITING_WINBACK_PERCENT,
    AWAITING_WINBACK_DAYS2, AWAITING_WINBACK_PERCENT2, AWAITING_WINBACK_LIFE,
)

DATE_FMT = "%d.%m.%Y %H:%M:%S"


def settings() -> dict:
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("winback_enabled", False)),
        "days": int(cfg.get("winback_days", 3) or 3),
        "percent": int(cfg.get("winback_percent", 20) or 20),
        # вторая волна: 0 в днях — выключена
        "days2": int(cfg.get("winback_days2", 0) or 0),
        "percent2": int(cfg.get("winback_percent2", 35) or 35),
        "life_days": int(cfg.get("winback_life_days", 3) or 3),
        "paid_only": bool(cfg.get("winback_paid_only", False)),
    }


def code_for(tg_id: int, stage: int) -> str:
    return f"BACK{tg_id}" if stage == 1 else f"BACK{tg_id}X{stage}"


async def _send_wave(bot, tg_id: int, stage: int, percent: int, life_days: int) -> str:
    """Готовит личный промокод и зовёт человека обратно. Возвращает код."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_promo, create_promo

    code = code_for(tg_id, stage)
    until = (datetime.now() + timedelta(days=life_days)).strftime(DATE_FMT)
    if not await get_promo(code):
        await create_promo(code, percent, until, owner_tg_id=tg_id,
                           max_uses=1, note="Winback", source="winback")

    head = ("🎯 <b>Возвращайтесь — мы сделали скидку</b>" if stage == 1
            else "🎯 <b>Последнее предложение</b>")
    tail = ("<i>Промокод личный и сгорит вместе с предложением.</i>" if stage == 1
            else "<i>Больше писать не будем — промокод сгорит, и на этом всё.</i>")
    await bot.send_message(
        chat_id=tg_id,
        text=(f"{head}\n\n"
              f"<blockquote>🎟 Промокод: <code>{code}</code>\n"
              f"💯 Скидка: <b>{percent}%</b>\n"
              f"⏳ Действует до: <b>{until[:16]}</b></blockquote>\n\n"
              "Введите его при продлении — цена пересчитается сразу.\n\n"
              + tail),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Продлить со скидкой", callback_data="renew_sub")],
            [InlineKeyboardButton("🎟 Ввести промокод", callback_data="enter_promo")],
        ]),
    )
    return code


async def winback_tick(context):
    """Разбирает истёкшие подписки и рассылает волны."""
    from database import winback_stage, mark_winback_sent
    from paidsub.storage import get_expired_paid_subs, parse_sub_date
    from blacklist import is_blacklisted
    from log_channel import send_log

    s = settings()
    if not s["enabled"]:
        return

    now = datetime.now()
    for row in await get_expired_paid_subs():
        tg_id, expire_str, status = row[1], row[6], row[7]
        times_renewed = row[8] if len(row) > 8 else 0
        if status != "expired" or not tg_id:
            continue
        if s["paid_only"] and not times_renewed:
            continue

        end = parse_sub_date(expire_str)
        if not end:
            continue
        gone = (now - end).days

        # какая волна подходит: считаем от поздней, чтобы при простое бота
        # человек получил одно письмо, а не два подряд
        target = 0
        if gone >= s["days"]:
            target = 1
        if s["days2"] and gone >= s["days2"]:
            target = 2
        if not target or target <= await winback_stage(tg_id):
            continue
        if await is_blacklisted(tg_id):
            continue

        percent = s["percent"] if target == 1 else s["percent2"]
        try:
            code = await _send_wave(context.bot, tg_id, target, percent, s["life_days"])
        except Exception:
            # заблокировал бота — помечаем, чтобы не долбиться каждый час
            await mark_winback_sent(tg_id, target)
            continue
        await mark_winback_sent(tg_id, target)
        await send_log(context.bot,
                       f"🎯 Winback (волна {target}): <code>{tg_id}</code> · "
                       f"промокод <b>{code}</b> (−{percent}%)")


# ── Экран в админке ───────────────────────────────────────────────────────────

async def handle_winback_settings(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import winback_stats
    s = settings()
    st = await winback_stats()
    status = "🟢 включён" if s["enabled"] else "🔴 выключен"
    wave2 = (f"через <b>{s['days2']}</b> дн. · скидка <b>{s['percent2']}%</b>"
             if s["days2"] else "выключена")

    await query.edit_message_text(
        "🎯 <b>Winback — возврат ушедших</b>\n\n"
        f"<blockquote>Статус: <b>{status}</b>\n"
        f"1️⃣ Первая волна: через <b>{s['days']}</b> дн. · скидка <b>{s['percent']}%</b>\n"
        f"2️⃣ Вторая волна: {wave2}\n"
        f"⏳ Промокод живёт: <b>{s['life_days']}</b> дн.\n"
        f"👤 Кому: <b>{'только платившим' if s['paid_only'] else 'всем ушедшим'}</b>"
        "</blockquote>\n\n"
        "<blockquote>Итоги\n"
        f"📨 Отправлено писем: <b>{st['sent']}</b>  ·  людям: <b>{st['people']}</b>\n"
        f"🎟 Промокод применили: <b>{st['used']}</b>\n"
        f"💰 Вернулись и заплатили: <b>{st['returned']}</b> ({st['percent']}%)"
        "</blockquote>\n\n"
        "<i>Бот пишет тем, у кого подписка закончилась, и даёт личный промокод "
        "с коротким сроком. Людям из чёрного списка не пишет.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Выключить" if s["enabled"] else "🟢 Включить",
                                  callback_data="toggle_winback"),
             InlineKeyboardButton("📨 Прислать пример", callback_data="winback_test")],
            [InlineKeyboardButton("1️⃣ Дни", callback_data="set_winback_days"),
             InlineKeyboardButton("1️⃣ Скидка", callback_data="set_winback_percent")],
            [InlineKeyboardButton("2️⃣ Дни", callback_data="set_winback_days2"),
             InlineKeyboardButton("2️⃣ Скидка", callback_data="set_winback_percent2")],
            [InlineKeyboardButton("⏳ Срок промокода", callback_data="set_winback_life"),
             InlineKeyboardButton(f"👤 {'Платившим' if s['paid_only'] else 'Всем'}",
                                  callback_data="toggle_winback_paid")],
            [InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")],
        ]),
    )


async def handle_toggle_winback(query):
    cfg = load_config()
    cfg["winback_enabled"] = not cfg.get("winback_enabled", False)
    save_config(cfg)
    await handle_winback_settings(query)


async def handle_toggle_winback_paid(query):
    cfg = load_config()
    cfg["winback_paid_only"] = not cfg.get("winback_paid_only", False)
    save_config(cfg)
    await handle_winback_settings(query)


_ASK = {
    "days": (AWAITING_WINBACK_DAYS, "1️⃣ <b>Первая волна</b>",
             "Через сколько дней после окончания писать?\n\n"
             "<blockquote>Пришли число дней.</blockquote>"),
    "percent": (AWAITING_WINBACK_PERCENT, "1️⃣ <b>Скидка первой волны</b>",
                "Какую скидку дать?\n\n<blockquote>Число от 1 до 100.</blockquote>"),
    "days2": (AWAITING_WINBACK_DAYS2, "2️⃣ <b>Вторая волна</b>",
              "Через сколько дней после окончания уходит вторая, последняя попытка?\n\n"
              "<blockquote>Число дней. <code>0</code> — вторую волну не слать.</blockquote>"),
    "percent2": (AWAITING_WINBACK_PERCENT2, "2️⃣ <b>Скидка второй волны</b>",
                 "Обычно больше первой — это последнее предложение.\n\n"
                 "<blockquote>Число от 1 до 100.</blockquote>"),
    "life": (AWAITING_WINBACK_LIFE, "⏳ <b>Срок жизни промокода</b>",
             "Сколько дней действует личный промокод?\n\n"
             "<blockquote>Короткий срок работает лучше: есть повод вернуться "
             "сейчас, а не «когда-нибудь».</blockquote>"),
}


async def handle_set_winback(query, context, which: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    state, title, body = _ASK[which]
    cur = {
        "days": settings()["days"], "percent": settings()["percent"],
        "days2": settings()["days2"], "percent2": settings()["percent2"],
        "life": settings()["life_days"],
    }[which]
    context.user_data["state"] = state
    await query.edit_message_text(
        f"{title}\n\n<blockquote>Сейчас: <b>{cur}</b></blockquote>\n\n{body}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="winback_settings")],
        ]),
    )


async def handle_winback_test(query, context):
    """Присылает админу то же письмо, что получит ушедший клиент."""
    s = settings()
    try:
        await _send_wave(context.bot, query.from_user.id, 1, s["percent"], s["life_days"])
        await query.answer("Пример отправлен сюда же")
    except Exception as e:
        await query.answer(f"Не отправилось: {type(e).__name__}", show_alert=True)
