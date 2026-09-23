"""Выдача промокодов: лично человеку и пачкой по сегменту.

Личный код привязан к владельцу — чужому он не сработает, даже если его
переслали. Награда бывает двух видов: скидка в процентах на продление и
подаренные дни, которые начисляются сразу при вводе кода.

Обычные общие промокоды остались там же, где были: «🎟 Промокоды → Создать».
"""

from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID, load_config
from states import AWAITING_PROMO_CUSTOM, AWAITING_PROMO_GIVE_USER

DATE_FMT = "%d.%m.%Y %H:%M:%S"
DAY_FMT = "%d.%m.%Y"
# сколько дней действует выданный код, пока не введён
VALID_DAYS = 14
# пауза между отправками: Telegram режет всё, что быстрее ~30 сообщений в секунду
SEND_PAUSE = 0.05

PRESETS = [("percent", 10), ("percent", 20), ("percent", 30), ("percent", 50),
           ("days", 3), ("days", 7), ("days", 30)]

SEGMENTS = {
    "expired": "🔴 Истёкшие подписки",
    "trial": "🆓 Только триал",
    "paying": "⭐️ Платящие",
    "active": "🟢 Активные подписки",
    "no_sub": "🚫 Без подписки",
    "all": "🌍 Все пользователи",
}


def reward_label(kind: str, value: int) -> str:
    return f"+{value} дн." if kind == "days" else f"−{value}%"


def reward_text(kind: str, value: int) -> str:
    return f"{value} дней в подарок" if kind == "days" else f"скидка {value}% на продление"


def _who(u, tg_id) -> str:
    if not u:
        return f"<code>{tg_id}</code>"
    name = html.escape(str(u[1] or tg_id))
    return (f"{name} (@{html.escape(u[2])})" if u[2] else name) + f" · <code>{tg_id}</code>"


# ── Выдача ───────────────────────────────────────────────────────────────────

async def issue_code(tg_id: int, kind: str, value: int, source: str = "personal",
                     note: str | None = None) -> str | None:
    """Создаёт личный код для человека. Возвращает код или None."""
    from paidsub.storage import create_promo, unique_promo_code
    prefix = "GIFT" if kind == "days" else "VIP"
    code = await unique_promo_code(prefix)
    expires = (datetime.now() + timedelta(days=VALID_DAYS)).strftime(DAY_FMT)
    ok = await create_promo(
        code, value if kind == "percent" else 0, expires,
        owner_tg_id=tg_id, max_uses=1, kind=kind,
        days=value if kind == "days" else 0, note=note, source=source,
    )
    return code if ok else None


def gift_message(code: str, kind: str, value: int) -> tuple[str, InlineKeyboardMarkup]:
    expires = (datetime.now() + timedelta(days=VALID_DAYS)).strftime(DAY_FMT)
    if kind == "days":
        text = (f"🎁 <b>Вам подарок — {value} дней подписки!</b>\n\n"
                f"<blockquote>🎟 Промокод: <code>{code}</code>\n"
                f"📅 Действует до: <b>{expires}</b></blockquote>\n\n"
                "<i>Нажмите на код, чтобы скопировать, и введите его — дни добавятся сразу.</i>")
    else:
        text = (f"🎁 <b>Персональная скидка {value}%</b>\n\n"
                f"<blockquote>🎟 Промокод: <code>{code}</code>\n"
                f"📅 Действует до: <b>{expires}</b></blockquote>\n\n"
                "<i>Введите его перед оплатой — скидка применится к продлению.</i>")
    return text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🎟 Ввести промокод", callback_data="enter_promo"),
         InlineKeyboardButton("💳 Продлить", callback_data="renew_sub")],
    ])


async def give_to_user(bot, tg_id: int, kind: str, value: int,
                       source: str = "personal", note: str | None = None) -> dict:
    """Выдаёт код и отправляет его человеку."""
    code = await issue_code(tg_id, kind, value, source, note)
    if not code:
        return {"ok": False, "error": "не удалось создать код"}
    text, kb = gift_message(code, kind, value)
    delivered = True
    try:
        await bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        delivered = False
    from paidsub.storage import add_history
    await add_history(tg_id, "promo_issued", f"{reward_label(kind, value)} · код {code}"
                      + (f"\n{note}" if note else ""))
    return {"ok": True, "code": code, "delivered": delivered}


async def apply_days(tg_id: int, days: int, bot=None) -> dict:
    """Начисляет подаренные дни: продлевает подписку и включает клиента."""
    from paidsub.storage import (
        add_history, get_paid_sub_by_tg_id, parse_sub_date, set_expire_date, update_paid_sub_field,
    )
    from xui_api import get_client_info, move_client_inbound, toggle_client, update_client_expire

    row = await get_paid_sub_by_tg_id(tg_id)
    if not row:
        return {"ok": False, "error": "подписки нет"}
    sub_id, email, expire_str = row[0], row[2], row[6]
    exp = parse_sub_date(expire_str)
    # дни к остатку, а если срок уже вышел — считаем от сегодня
    base = exp if exp and exp > datetime.now() else datetime.now()
    until = (base + timedelta(days=int(days))).strftime(DATE_FMT)
    await set_expire_date(sub_id, until)
    await update_paid_sub_field(sub_id, "status", "active")
    await update_client_expire(email, until)
    info = await get_client_info(email)
    if info.get("success") and not info.get("enabled", True):
        await toggle_client(email, True)
    inbound_ids = load_config().get("paid_preset_inbound_ids") or []
    if inbound_ids:
        await move_client_inbound(email, inbound_ids)
    await add_history(tg_id, "promo_days", f"Начислено {days} дней\nДо: {until}")
    return {"ok": True, "until": until}


# ── Экраны админки ───────────────────────────────────────────────────────────

def _presets_kb(prefix: str, tail: str = "") -> list:
    rows, row = [], []
    for kind, value in PRESETS:
        row.append(InlineKeyboardButton(reward_label(kind, value),
                                        callback_data=f"{prefix}:{kind}:{value}{tail}"))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


async def handle_promo_give_start(query, context):
    """«Выдать лично» из меню промокодов — сначала спрашиваем кому."""
    context.user_data["state"] = AWAITING_PROMO_GIVE_USER
    await query.edit_message_text(
        "🎁 <b>Выдать промокод лично</b>\n\n"
        "<i>Пришли ID или @username человека — код будет работать только у него.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="promo_menu")]]),
    )


async def handle_promo_give_for(query, context, tg_id: int):
    """Выбор награды для конкретного человека."""
    from database import get_user_info
    from paidsub.storage import get_paid_sub_by_tg_id
    context.user_data.pop("state", None)
    u = await get_user_info(tg_id)
    sub = await get_paid_sub_by_tg_id(tg_id)
    if sub:
        status = {"active": "🟢 активна", "renewal": "🟡 ждёт продления",
                  "expired": "🔴 истекла"}.get(sub[11], sub[11])
        sub_line = f"💳 Подписка: <b>{status}</b>  ·  до {sub[6]}"
    else:
        sub_line = "💳 Подписки нет — подарочные дни начислить будет некуда"
    kb = _presets_kb(f"promo_give_pick:{tg_id}")
    kb.append([InlineKeyboardButton("✍️ Своя величина", callback_data=f"promo_give_custom:{tg_id}")])
    kb.append([InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")])
    await query.edit_message_text(
        f"🎁 <b>Промокод для человека</b>\n\n"
        f"<blockquote>👤 {_who(u, tg_id)}\n{sub_line}</blockquote>\n\n"
        f"<b>Выбери награду</b>\n"
        f"<i>Код личный, на одно применение, действует {VALID_DAYS} дней.</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_promo_give_custom(query, context, tg_id: int):
    context.user_data["state"] = AWAITING_PROMO_CUSTOM
    context.user_data["promo_target"] = tg_id
    await query.edit_message_text(
        "✍️ <b>Своя величина</b>\n\n"
        "<blockquote>Скидка — число процентов: <code>35</code>\n"
        "Подарочные дни — число со словом «дней»: <code>10 дней</code></blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data=f"promo_give_for:{tg_id}")]]),
    )


async def handle_promo_give_pick(query, context, tg_id: int, kind: str, value: int):
    """Подтверждение перед выдачей."""
    from database import get_user_info
    from handlers.confirm import confirm_keyboard
    u = await get_user_info(tg_id)
    await query.edit_message_text(
        f"🎁 <b>Выдать промокод?</b>\n\n"
        f"<blockquote>👤 {_who(u, tg_id)}\n"
        f"🎟 Награда: <b>{reward_text(kind, value)}</b>\n"
        f"📅 {VALID_DAYS} дней, одно применение, только у этого человека</blockquote>\n\n"
        "<i>Бот сразу отправит ему код сообщением.</i>",
        parse_mode="HTML",
        reply_markup=confirm_keyboard("🎁 Да, выдать", f"promo_give_do:{tg_id}:{kind}:{value}",
                                      f"promo_give_for:{tg_id}", "promo_menu"),
    )


async def handle_promo_give_do(query, context, tg_id: int, kind: str, value: int):
    res = await give_to_user(context.bot, tg_id, kind, value)
    if not res["ok"]:
        await query.edit_message_text(f"❌ <b>Не получилось</b>\n\n<i>{html.escape(str(res['error']))}</i>",
                                      parse_mode="HTML",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")]]))
        return
    from database import get_user_info
    from log_channel import send_log
    u = await get_user_info(tg_id)
    await send_log(context.bot, f"🎁 Выдан промокод {res['code']} ({reward_label(kind, value)}) "
                                f"· {_who(u, tg_id)}")
    tail = "" if res["delivered"] else "\n\n⚠️ <i>Сообщение не доставлено — возможно, бот заблокирован.</i>"
    await query.edit_message_text(
        "✅ <b>Промокод выдан</b>\n\n"
        f"<blockquote>👤 {_who(u, tg_id)}\n"
        f"🎟 <code>{res['code']}</code> — {reward_text(kind, value)}</blockquote>{tail}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{tg_id}"),
             InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")],
        ]),
    )


# ── Раздача сегменту ─────────────────────────────────────────────────────────

async def handle_promo_seg(query, context):
    context.user_data.pop("state", None)
    from database import get_users_by_segment
    kb = []
    for key, label in SEGMENTS.items():
        count = len(await get_users_by_segment(key))
        kb.append([InlineKeyboardButton(f"{label} · {count}", callback_data=f"promo_seg_pick:{key}")])
    kb.append([InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")])
    await query.edit_message_text(
        "📤 <b>Раздать промокоды</b>\n\n"
        "<i>Каждый получит свой личный код — переслать его другому не выйдет.</i>\n\n"
        "<b>Кому раздаём?</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_promo_seg_pick(query, context, segment: str):
    kb = _presets_kb("promo_seg_val", f":{segment}")
    kb.append([InlineKeyboardButton("◀️ К сегментам", callback_data="promo_seg")])
    await query.edit_message_text(
        f"📤 <b>Раздать промокоды</b>\n\n<blockquote>🎯 {SEGMENTS.get(segment, segment)}</blockquote>\n\n"
        "<b>Что раздаём?</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_promo_seg_preview(query, context, kind: str, value: int, segment: str):
    from database import get_users_by_segment
    from handlers.confirm import confirm_keyboard
    ids = await get_users_by_segment(segment)
    skipped = await _skip_ids(ids)
    context.user_data["promo_seg"] = {"kind": kind, "value": value, "segment": segment}
    await query.edit_message_text(
        f"📤 <b>Раздать промокоды?</b>\n\n"
        f"<blockquote>🎯 {SEGMENTS.get(segment, segment)}\n"
        f"🎟 Награда: <b>{reward_text(kind, value)}</b>\n"
        f"👥 Получат код: <b>{len(ids) - len(skipped)}</b>"
        + (f"\n⏭ Пропустим (бан, ЧС, заглушены): {len(skipped)}" if skipped else "")
        + f"\n📅 Коды действуют {VALID_DAYS} дней, каждый на одно применение</blockquote>\n\n"
          "<i>Отправка идёт с паузами, чтобы Telegram не начал резать сообщения.</i>",
        parse_mode="HTML",
        reply_markup=confirm_keyboard("📤 Да, раздать", "promo_seg_do",
                                      f"promo_seg_pick:{segment}", "promo_menu"),
    )


async def _skip_ids(ids: list) -> set:
    """Кому не раздаём: админ, забаненные, из ЧС и заглушённые."""
    from blacklist import blacklisted_ids
    from database import is_banned
    from paidsub.storage import get_muted_until
    skip = {ADMIN_ID} & set(ids)
    skip |= set(ids) & await blacklisted_ids()
    for tg_id in ids:
        if tg_id in skip:
            continue
        if await is_banned(tg_id) or await get_muted_until(tg_id):
            skip.add(tg_id)
    return skip


async def handle_promo_seg_do(query, context):
    plan = context.user_data.pop("promo_seg", None)
    if not plan:
        await handle_promo_seg(query, context)
        return
    from database import get_users_by_segment
    kind, value, segment = plan["kind"], plan["value"], plan["segment"]
    ids = await get_users_by_segment(segment)
    skip = await _skip_ids(ids)
    targets = [i for i in ids if i not in skip]
    await query.edit_message_text(
        f"📤 <b>Раздаю…</b>  0 из {len(targets)}", parse_mode="HTML")

    sent = failed = 0
    for n, tg_id in enumerate(targets, 1):
        res = await give_to_user(context.bot, tg_id, kind, value, source="segment",
                                 note=f"Раздача: {SEGMENTS.get(segment, segment)}")
        if res["ok"] and res["delivered"]:
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(SEND_PAUSE)
        if n % 25 == 0:
            try:
                await query.edit_message_text(f"📤 <b>Раздаю…</b>  {n} из {len(targets)}",
                                              parse_mode="HTML")
            except Exception:
                pass

    from log_channel import send_log
    await send_log(context.bot, f"📤 Раздача промокодов ({SEGMENTS.get(segment, segment)}, "
                                f"{reward_label(kind, value)}): доставлено {sent}, не дошло {failed}")
    await query.edit_message_text(
        "✅ <b>Раздача закончена</b>\n\n"
        f"<blockquote>🎯 {SEGMENTS.get(segment, segment)}  ·  {reward_text(kind, value)}\n"
        f"📨 Доставлено: <b>{sent}</b>"
        + (f"\n❌ Не дошло (бот заблокирован): <b>{failed}</b>" if failed else "")
        + (f"\n⏭ Пропущено: <b>{len(skip)}</b>" if skip else "") + "</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")]]),
    )


# ── Что принесли ─────────────────────────────────────────────────────────────

async def handle_promo_income(query):
    from paidsub.storage import promo_income_all
    rows = await promo_income_all()
    lines = ["📊 <b>Что принесли промокоды</b>", ""]
    if not rows:
        lines.append("<blockquote>Пока ни одного применения.</blockquote>")
    total_pays = total_sum = 0
    items = []
    for code, kind, percent, days, uses, pays, amount in rows:
        total_pays += pays or 0
        total_sum += amount or 0
        reward = reward_label(kind or "percent", days if kind == "days" else percent)
        items.append(f"🎟 <code>{html.escape(code)}</code> {reward} · применён "
                     f"<b>{uses}</b> · оплат <b>{pays}</b> на <b>{amount} ₽</b>")
    if items:
        lines.append("<blockquote expandable>" + "\n".join(items) + "</blockquote>")
    if total_pays:
        lines.append(f"\n💰 Итого с промокодами: <b>{total_pays}</b> оплат на <b>{total_sum} ₽</b>")
    lines.append("\n<i>Сумма — то, что реально заплатили со скидкой. "
                 "Подарочные дни денег не приносят, они держат людей.</i>")
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")]]),
    )


# ── Ввод текста ──────────────────────────────────────────────────────────────

async def handle_promo_input(update, context, state: str, text: str):
    msg = update.message
    if state == AWAITING_PROMO_GIVE_USER:
        from database import find_user_by_username, get_user_info
        token = text.split()[0] if text.split() else ""
        tg_id = int(token) if token.isdigit() else None
        if tg_id is None:
            u = await find_user_by_username(token)
            tg_id = u[0] if u else None
        if not tg_id or not await get_user_info(tg_id):
            await msg.reply_text(
                "🔍 <b>Не нашёл такого пользователя</b>\n\n<i>Пришли числовой ID или @username.</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отмена", callback_data="promo_menu")]]))
            return
        context.user_data.pop("state", None)
        await _ask_reward(msg, tg_id)
        return

    # своя величина: «35» — проценты, «10 дней» — подарочные дни
    tg_id = context.user_data.get("promo_target")
    raw = text.strip().lower()
    digits = "".join(c for c in raw if c.isdigit())
    if not tg_id or not digits:
        await msg.reply_text("❌ <b>Нужно число</b>\n\n<i>Например <code>35</code> или <code>10 дней</code></i>",
                             parse_mode="HTML",
                             reply_markup=InlineKeyboardMarkup([
                                 [InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")]]))
        return
    value = int(digits)
    kind = "days" if "дн" in raw or "day" in raw else "percent"
    if kind == "percent" and not (1 <= value <= 100):
        await msg.reply_text("❌ <b>Скидка — от 1 до 100 процентов</b>", parse_mode="HTML")
        return
    if kind == "days" and not (1 <= value <= 365):
        await msg.reply_text("❌ <b>Дней — от 1 до 365</b>", parse_mode="HTML")
        return
    context.user_data.pop("state", None)
    context.user_data.pop("promo_target", None)
    from database import get_user_info
    from handlers.confirm import confirm_keyboard
    u = await get_user_info(tg_id)
    await msg.reply_text(
        f"🎁 <b>Выдать промокод?</b>\n\n"
        f"<blockquote>👤 {_who(u, tg_id)}\n"
        f"🎟 Награда: <b>{reward_text(kind, value)}</b>\n"
        f"📅 {VALID_DAYS} дней, одно применение</blockquote>",
        parse_mode="HTML",
        reply_markup=confirm_keyboard("🎁 Да, выдать", f"promo_give_do:{tg_id}:{kind}:{value}",
                                      f"promo_give_for:{tg_id}", "promo_menu"),
    )


async def _ask_reward(msg, tg_id: int):
    from database import get_user_info
    u = await get_user_info(tg_id)
    kb = _presets_kb(f"promo_give_pick:{tg_id}")
    kb.append([InlineKeyboardButton("✍️ Своя величина", callback_data=f"promo_give_custom:{tg_id}")])
    kb.append([InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")])
    await msg.reply_text(
        f"🎁 <b>Промокод для человека</b>\n\n<blockquote>👤 {_who(u, tg_id)}</blockquote>\n\n"
        "<b>Выбери награду</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )
