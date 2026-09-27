"""Промокоды: раздел целиком — общие коды, личные, партии и раздачи.

Награда бывает двух видов: скидка в процентах на продление и подаренные дни,
которые начисляются сразу при вводе кода.

• общий код работает у любого, кто его узнает; личный привязан к владельцу и
  у чужого не сработает, даже если его переслали;
• у кода есть срок, лимит применений и переключатель «только тем, кто ещё не
  платил» — им удобно звать новых, не давая скидку постоянным;
• партия делает пачку одноразовых кодов на акцию — их можно раздать где угодно;
• в карточке видно, кто применял код и сколько денег он принёс;
• мёртвые коды (выключенные и просроченные) без применений убираются одной
  кнопкой, а те, которыми пользовались, остаются ради статистики.
"""

from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_ID
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
    from panel import get_client_info, toggle_client, update_client_expire

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
        status = {"active": "🟢 активна", "expired": "🔴 истекла"}.get(sub[11], sub[11])
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
        + (f"\n⏭ Пропустим (бан, ЧС): {len(skipped)}" if skipped else "")
        + f"\n📅 Коды действуют {VALID_DAYS} дней, каждый на одно применение</blockquote>\n\n"
          "<i>Отправка идёт с паузами, чтобы Telegram не начал резать сообщения.</i>",
        parse_mode="HTML",
        reply_markup=confirm_keyboard("📤 Да, раздать", "promo_seg_do",
                                      f"promo_seg_pick:{segment}", "promo_menu"),
    )


async def _skip_ids(ids: list) -> set:
    """Кому не раздаём: админ, забаненные и те, кто в чёрном списке."""
    from blacklist import blacklisted_ids
    from database import is_banned
    skip = {ADMIN_ID} & set(ids)
    skip |= set(ids) & await blacklisted_ids()
    for tg_id in ids:
        if tg_id in skip:
            continue
        if await is_banned(tg_id):
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

def _value_from_text(raw: str):
    """«35» → скидка 35%, «10 дней» → 10 подарочных дней. None — не понял."""
    low = (raw or "").strip().lower()
    digits = "".join(c for c in low if c.isdigit())
    if not digits:
        return None
    value = int(digits)
    kind = "days" if "дн" in low or "day" in low else "percent"
    if kind == "percent" and not (1 <= value <= 100):
        return None
    if kind == "days" and not (1 <= value <= 365):
        return None
    return kind, value


async def handle_promo_admin_input(update, context, state: str, text: str) -> bool:
    """Ввод в разделе промокодов. True — разобрались сами."""
    from states import (
        AWAITING_PROMO_FIND, AWAITING_PROMO_NEW_CODE, AWAITING_PROMO_NEW_EXPIRE,
        AWAITING_PROMO_NEW_LIMIT, AWAITING_PROMO_NEW_VALUE,
    )
    msg = update.message
    back = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К промокодам",
                                                      callback_data="promo_menu")]])

    if state == AWAITING_PROMO_FIND:
        await handle_promo_search(msg, context, text)
        return True

    if state == AWAITING_PROMO_NEW_CODE:
        from paidsub.storage import get_promo
        code = text.strip().upper()
        if not code or len(code) > 32 or " " in code:
            await msg.reply_text("❌ <b>Код без пробелов, до 32 символов</b>\n\n"
                                 "<i>Пришли ещё раз.</i>", parse_mode="HTML", reply_markup=back)
            return True
        if await get_promo(code):
            await msg.reply_text("❌ <b>Такой код уже есть</b>\n\n<i>Придумай другой.</i>",
                                 parse_mode="HTML", reply_markup=back)
            return True
        context.user_data["new_promo"] = {"code": code}
        await handle_promo_draft(msg, context, edit=False)
        return True

    if state == AWAITING_PROMO_NEW_VALUE:
        parsed = _value_from_text(text)
        if not parsed:
            await msg.reply_text("❌ <b>Не понял величину</b>\n\n"
                                 "<i>Скидка — <code>35</code>, дни — <code>10 дней</code>.</i>",
                                 parse_mode="HTML", reply_markup=back)
            return True
        d = _draft(context)
        d["kind"], d["value"] = parsed
        await handle_promo_draft(msg, context, edit=False)
        return True

    if state == AWAITING_PROMO_NEW_LIMIT:
        if not text.strip().isdigit():
            await msg.reply_text("❌ <b>Нужно число</b>\n\n<i><code>0</code> — без лимита.</i>",
                                 parse_mode="HTML", reply_markup=back)
            return True
        limit = int(text.strip())
        edit = context.user_data.pop("promo_edit", None)
        if edit:
            from paidsub.storage import promo_set
            await promo_set(edit["id"], "max_uses", limit)
            context.user_data.pop("state", None)
            await msg.reply_text(
                f"✅ <b>Лимит: {limit if limit else 'без лимита'}</b>", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎟 К промокоду",
                                          callback_data=f"promo_view:{edit['id']}")]]))
            return True
        _draft(context)["max_uses"] = limit
        await handle_promo_draft(msg, context, edit=False)
        return True

    if state == AWAITING_PROMO_NEW_EXPIRE:
        raw = text.strip()
        until = None
        if raw != "-":
            try:
                datetime.strptime(raw, DAY_FMT)
                until = raw
            except ValueError:
                await msg.reply_text("❌ <b>Формат даты</b>\n\n"
                                     "<i><code>31.12.2026</code> или <code>-</code> — без срока.</i>",
                                     parse_mode="HTML", reply_markup=back)
                return True
        edit = context.user_data.pop("promo_edit", None)
        if edit:
            from paidsub.storage import promo_set
            await promo_set(edit["id"], "expires_at", until)
            context.user_data.pop("state", None)
            await msg.reply_text(
                f"✅ <b>Срок: {until if until else 'без срока'}</b>", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎟 К промокоду",
                                          callback_data=f"promo_view:{edit['id']}")]]))
            return True
        _draft(context)["expires_at"] = until
        await handle_promo_draft(msg, context, edit=False)
        return True

    return False


async def handle_promo_input(update, context, state: str, text: str):
    msg = update.message
    if await handle_promo_admin_input(update, context, state, text):
        return
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


# ── Раздел «Промокоды»: список, карточка, создание ───────────────────────────

TABS = {"common": "🌍 Общие", "personal": "🎯 Личные", "dead": "🪦 Мёртвые", "all": "📋 Все"}
PER_PAGE = 10
# Лимиты применений и сроки под кнопку: 0 — без ограничения
LIMITS = [1, 5, 10, 50, 0]
TERM_DAYS = [7, 14, 30, 90, 0]
BATCH_SIZES = [5, 10, 25, 50]


def _reward_of(row) -> str:
    """Награда из строки списка: (…, kind, days) — скидка или дни."""
    kind, days, percent = row[7], row[8], row[2]
    return reward_label(kind or "percent", days if kind == "days" else percent)


def _expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        return datetime.strptime(expires_at.strip()[:10], DAY_FMT) < datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return False


def _promo_line(row) -> str:
    """Кнопка кода: состояние, награда, применения и срок."""
    pid, code, _percent, expires_at, active, owner, max_uses = row[:7]
    first_only = row[9]
    uses = row[10]
    mark = "🔴" if not active else ("⏳" if _expired(expires_at) else "🟢")
    who = "🎯" if owner else ("🆕" if first_only else "🌍")
    limit = f"/{max_uses}" if max_uses else ""
    exp = f" · до {str(expires_at)[:10]}" if expires_at else ""
    return f"{mark}{who} {code} · {_reward_of(row)} · {uses}{limit}{exp}"[:60]


async def handle_promo_menu(query, context=None, note: str = ""):
    from paidsub.storage import promo_dead_ids, promo_stats, promo_tab_counts
    if context:
        context.user_data.pop("state", None)
        context.user_data.pop("new_promo", None)
    st = await promo_stats()
    counts = await promo_tab_counts()
    dead_free = len(await promo_dead_ids())

    lines = ["🎟 <b>Промокоды</b>", ""]
    if note:
        lines += [note, ""]
    lines.append(
        "<blockquote>"
        f"🎫 Всего кодов: <b>{st['total']}</b>  ·  🟢 активных: <b>{st['active']}</b>  ·  "
        f"🎯 личных: <b>{st['personal']}</b>\n"
        f"🙋 Применений: <b>{st['uses']}</b>  ·  за 30 дней: <b>{st['uses_30d']}</b>\n"
        f"💰 Оплат с кодом: <b>{st['pays']}</b> на <b>{st['revenue']} ₽</b>"
        "</blockquote>")
    lines.append(
        "\n<i>🌍 общий — сработает у любого, кто узнает код\n"
        "🎯 личный — привязан к человеку, у чужого не сработает\n"
        "🆕 только новым — сработает лишь у тех, кто ещё не платил\n"
        "Награда — скидка в % на продление или подаренные дни.</i>")

    kb = [
        [InlineKeyboardButton(f"🌍 Общие · {counts['common']}", callback_data="promo_list:common:1"),
         InlineKeyboardButton(f"🎯 Личные · {counts['personal']}", callback_data="promo_list:personal:1")],
        [InlineKeyboardButton(f"🪦 Мёртвые · {counts['dead']}", callback_data="promo_list:dead:1"),
         InlineKeyboardButton("🔍 Найти код", callback_data="promo_find")],
        [InlineKeyboardButton("➕ Создать общий", callback_data="promo_create"),
         InlineKeyboardButton("🎬 Партия кодов", callback_data="promo_batch")],
        [InlineKeyboardButton("🎁 Выдать лично", callback_data="promo_give"),
         InlineKeyboardButton("📤 Раздать сегменту", callback_data="promo_seg")],
        [InlineKeyboardButton("📊 Что принесли", callback_data="promo_income")],
    ]
    if dead_free:
        kb.append([InlineKeyboardButton(f"🧹 Убрать мёртвые · {dead_free}",
                                        callback_data="promo_clean")])
    kb.append([InlineKeyboardButton("◀️ К подпискам", callback_data="paid_subs")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_promo_list(query, tab: str = "common", page: int = 1):
    from paidsub.storage import list_promos_page
    if tab not in TABS:
        tab = "common"
    rows, pages, total = await list_promos_page(tab, page, PER_PAGE)
    page = min(max(1, page), pages)
    kb = [[InlineKeyboardButton(_promo_line(r), callback_data=f"promo_view:{r[0]}")] for r in rows]
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"promo_list:{tab}:{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"promo_list:{tab}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(("• " if k == tab else "") + label,
                                    callback_data=f"promo_list:{k}:1")
               for k, label in TABS.items()])
    kb.append([InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")])
    body = (f"Всего во вкладке: <b>{total}</b>  ·  стр. {page} из {pages}"
            if rows else "Пусто.")
    await query.edit_message_text(
        f"🎟 <b>{TABS[tab]}</b>\n\n<blockquote>{body}</blockquote>\n\n"
        "<i>🟢 работает · ⏳ срок вышел · 🔴 выключен\n"
        "Дальше: награда · применений/лимит · срок.</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_promo_view(query, promo_id: int, note: str = ""):
    """Карточка кода: условия, итоги и всё, что можно поменять."""
    from paidsub.storage import get_promo_by_id, promo_income, promo_use_count
    promo = await get_promo_by_id(promo_id)
    if not promo:
        await query.answer("Промокод не найден", show_alert=True)
        return
    (pid, code, percent, expires_at, active, created_at, owner, max_uses,
     kind, days, note_text, source) = promo[:12]
    first_only = promo[12] if len(promo) > 12 else 0
    used = await promo_use_count(code)
    pays, income = await promo_income(code)

    state = ("🔴 выключен" if not active
             else "⏳ срок вышел" if _expired(expires_at) else "🟢 работает")
    cond = [f"🎁 Награда: <b>{reward_text(kind or 'percent', days if kind == 'days' else percent)}</b>",
            f"📌 Состояние: <b>{state}</b>"]
    if owner:
        from database import get_user_info
        u = await get_user_info(owner)
        cond.append(f"🎯 Личный код: {_who(u, owner)}")
    else:
        cond.append("🌍 Общий код — сработает у любого, кто его узнает")
    cond.append(f"🆕 Только тем, кто ещё не платил: <b>{'да' if first_only else 'нет'}</b>")
    cond.append(f"📅 Срок: <b>{expires_at if expires_at else 'без срока'}</b>")
    cond.append(f"🔢 Лимит применений: <b>{max_uses if max_uses else 'без лимита'}</b>")

    facts = [f"🙋 Применён: <b>{used}</b>" + (f" из <b>{max_uses}</b>" if max_uses else " раз"),
             f"💰 Оплат с ним: <b>{pays}</b> на <b>{income} ₽</b>",
             f"🕐 Создан: {created_at[:16] if created_at else '?'}  ·  откуда: {source or 'manual'}"]

    lines = [f"🎟 <b>Промокод</b> <code>{html.escape(code)}</code>", ""]
    if note:
        lines += [note, ""]
    lines.append("<blockquote>" + "\n".join(cond) + "</blockquote>")
    lines.append("\n📊 <b>Итоги</b>\n<blockquote>" + "\n".join(facts) + "</blockquote>")
    if note_text:
        lines.append(f"\n📝 <i>{html.escape(str(note_text))}</i>")

    kb = [[InlineKeyboardButton("🔴 Выключить" if active else "🟢 Включить",
                                callback_data=f"promo_toggle:{pid}"),
           InlineKeyboardButton("🗑 Удалить", callback_data=f"promo_delete:{pid}")],
          [InlineKeyboardButton("📅 Срок", callback_data=f"promo_edit:{pid}:date"),
           InlineKeyboardButton("🔢 Лимит", callback_data=f"promo_edit:{pid}:limit")],
          [InlineKeyboardButton(f"🆕 Только новым · {'да ✅' if first_only else 'нет'}",
                                callback_data=f"promo_first:{pid}")]]
    if used:
        kb.append([InlineKeyboardButton(f"👥 Кто применял · {used}",
                                        callback_data=f"promo_uses:{pid}")])
    if owner:
        kb.append([InlineKeyboardButton("👤 Профиль", callback_data=f"user_profile:{owner}")])
    kb.append([InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_promo_uses(query, promo_id: int):
    """Кто применял код и сколько с него заплатили."""
    from paidsub.storage import get_promo_by_id, promo_users
    promo = await get_promo_by_id(promo_id)
    if not promo:
        await query.answer("Промокод не найден", show_alert=True)
        return
    code = promo[1]
    rows = await promo_users(code, 25)
    lines = [f"👥 <b>Кто применял</b> <code>{html.escape(code)}</code>", ""]
    if not rows:
        lines.append("<blockquote>Пока никто.</blockquote>")
    else:
        items = []
        for tg_id, fn, un, used_at, paid in rows:
            name = html.escape(str(fn or tg_id))
            who = f"{name} (@{html.escape(un)})" if un else name
            money = f" · <b>{paid} ₽</b>" if paid else ""
            items.append(f"<code>{str(used_at)[8:10]}.{str(used_at)[5:7]} "
                         f"{str(used_at)[11:16]}</code> {who}{money}")
        lines.append("<blockquote expandable>" + "\n".join(items) + "</blockquote>")
    kb = [[InlineKeyboardButton("◀️ К промокоду", callback_data=f"promo_view:{promo_id}")]]
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


async def handle_promo_toggle(query, promo_id: int):
    from paidsub.storage import toggle_promo
    await toggle_promo(promo_id)
    await handle_promo_view(query, promo_id)


async def handle_promo_first(query, promo_id: int):
    """Тумблер «только тем, кто ещё не платил»."""
    from paidsub.storage import get_promo_by_id, promo_set
    promo = await get_promo_by_id(promo_id)
    if not promo:
        await query.answer("Промокод не найден", show_alert=True)
        return
    cur = promo[12] if len(promo) > 12 else 0
    await promo_set(promo_id, "first_only", 0 if cur else 1)
    await handle_promo_view(query, promo_id)


async def handle_promo_delete(query, promo_id: int):
    from paidsub.storage import delete_promo
    await delete_promo(promo_id)
    await query.answer("Промокод удалён 🗑")
    await handle_promo_menu(query)


async def handle_promo_edit(query, context, promo_id: int, what: str):
    """Правка срока или лимита у готового кода."""
    from states import AWAITING_PROMO_NEW_EXPIRE, AWAITING_PROMO_NEW_LIMIT
    context.user_data["promo_edit"] = {"id": promo_id, "what": what}
    if what == "date":
        context.user_data["state"] = AWAITING_PROMO_NEW_EXPIRE
        text = ("📅 <b>Срок действия</b>\n\n"
                "<blockquote>Пришли дату в виде <code>31.12.2026</code>\n"
                "или <code>-</code> — без срока.</blockquote>")
    else:
        context.user_data["state"] = AWAITING_PROMO_NEW_LIMIT
        text = ("🔢 <b>Лимит применений</b>\n\n"
                "<blockquote>Пришли число применений или <code>0</code> — без лимита.</blockquote>")
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data=f"promo_view:{promo_id}")]]),
    )


async def handle_promo_clean(query, context):
    from paidsub.storage import promo_dead_ids
    ids = await promo_dead_ids()
    if not ids:
        await handle_promo_menu(query, context, note="<i>Мёртвых кодов без применений нет.</i>")
        return
    from handlers.confirm import confirm_keyboard
    await query.edit_message_text(
        f"🧹 <b>Убрать мёртвые коды?</b>\n\n"
        f"<blockquote>Под нож пойдут <b>{len(ids)}</b> кодов: выключенные и просроченные, "
        "которыми ни разу не воспользовались.</blockquote>\n\n"
        "<i>Коды с применениями останутся — по ним считается статистика.</i>",
        parse_mode="HTML",
        reply_markup=confirm_keyboard("🧹 Да, убрать", "promo_clean_do",
                                      "promo_menu", "promo_menu"),
    )


async def handle_promo_clean_do(query, context):
    from paidsub.storage import promo_clean_dead
    gone = await promo_clean_dead()
    await handle_promo_menu(query, context, note=f"<i>🧹 Убрано кодов: {gone}.</i>")


# ── Создание общего кода: один экран, всё правится кнопками ──────────────────

def _draft(context) -> dict:
    return context.user_data.setdefault("new_promo", {})


async def handle_promo_create(query, context):
    from states import AWAITING_PROMO_NEW_CODE
    context.user_data["state"] = AWAITING_PROMO_NEW_CODE
    context.user_data.pop("new_promo", None)
    await query.edit_message_text(
        "➕ <b>Новый общий промокод</b>\n\n"
        "<blockquote>Пришли текст кода: латиница и цифры, до 32 символов, "
        "например <code>SUMMER20</code>.</blockquote>\n\n"
        "<i>Награду, лимит и срок выберешь кнопками на следующем экране.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="promo_menu")]]),
    )


async def handle_promo_draft(target, context, edit: bool = True, note: str = ""):
    """Черновик кода: видно всё сразу, каждая строка меняется кнопкой."""
    d = _draft(context)
    context.user_data.pop("state", None)
    if not d.get("code"):
        text = "➕ <b>Черновик потерялся</b>\n\n<i>Начни заново.</i>"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К промокодам",
                                                        callback_data="promo_menu")]])
    else:
        kind, value = d.get("kind", "percent"), int(d.get("value", 0) or 0)
        reward = reward_text(kind, value) if value else "не выбрана"
        limit = int(d.get("max_uses", 0) or 0)
        until = d.get("expires_at")
        lines = ["➕ <b>Новый промокод</b>", ""]
        if note:
            lines += [note, ""]
        lines.append("<blockquote>"
                     f"🎟 Код: <code>{html.escape(d['code'])}</code>\n"
                     f"🎁 Награда: <b>{reward}</b>\n"
                     f"🔢 Лимит применений: <b>{limit if limit else 'без лимита'}</b>\n"
                     f"📅 Срок: <b>{until if until else 'без срока'}</b>\n"
                     f"🆕 Только тем, кто ещё не платил: "
                     f"<b>{'да' if d.get('first_only') else 'нет'}</b>"
                     "</blockquote>")
        lines.append("\n<i>Нажми на строку, чтобы поменять. «Создать» сохранит код.</i>")
        text = "\n".join(lines)
        rows = [[InlineKeyboardButton("🎁 Награда", callback_data="promo_new_ask:reward"),
                 InlineKeyboardButton("🔢 Лимит", callback_data="promo_new_ask:limit")],
                [InlineKeyboardButton("📅 Срок", callback_data="promo_new_ask:date"),
                 InlineKeyboardButton(f"🆕 Только новым · {'да ✅' if d.get('first_only') else 'нет'}",
                                      callback_data="promo_new_first")]]
        if value:
            rows.append([InlineKeyboardButton("✅ Создать", callback_data="promo_new_save")])
        rows.append([InlineKeyboardButton("❌ Отмена", callback_data="promo_menu")])
        kb = InlineKeyboardMarkup(rows)
    if edit:
        await target.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def handle_promo_new_ask(query, context, what: str):
    """Выбор награды, лимита или срока для черновика."""
    from states import AWAITING_PROMO_NEW_EXPIRE, AWAITING_PROMO_NEW_LIMIT
    if what == "reward":
        kb = _presets_kb("promo_new_reward")
        kb.append([InlineKeyboardButton("✍️ Своя величина", callback_data="promo_new_ask:own")])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="promo_new_back")])
        await query.edit_message_text(
            "🎁 <b>Награда промокода</b>\n\n"
            "<blockquote>−% — скидка на продление\n+дн. — дни в подарок сразу при вводе</blockquote>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return
    if what == "own":
        from states import AWAITING_PROMO_NEW_VALUE
        context.user_data["state"] = AWAITING_PROMO_NEW_VALUE
        await query.edit_message_text(
            "✍️ <b>Своя величина</b>\n\n"
            "<blockquote>Скидка — число процентов: <code>35</code>\n"
            "Подарочные дни — число со словом «дней»: <code>10 дней</code></blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="promo_new_back")]]))
        return
    if what == "limit":
        row = [InlineKeyboardButton("без лимита" if n == 0 else str(n),
                                    callback_data=f"promo_new_limit:{n}") for n in LIMITS]
        kb = [row[:3], row[3:], [InlineKeyboardButton("✍️ Своё число",
                                                      callback_data="promo_new_ask:limit_own")],
              [InlineKeyboardButton("◀️ Назад", callback_data="promo_new_back")]]
        await query.edit_message_text(
            "🔢 <b>Сколько раз кодом можно воспользоваться?</b>\n\n"
            "<blockquote>Считается по людям: один человек применяет код один раз.</blockquote>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return
    if what == "limit_own":
        context.user_data["state"] = AWAITING_PROMO_NEW_LIMIT
        await query.edit_message_text(
            "✍️ <b>Лимит применений</b>\n\n"
            "<blockquote>Пришли число или <code>0</code> — без лимита.</blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="promo_new_back")]]))
        return
    if what == "date_own":
        context.user_data["state"] = AWAITING_PROMO_NEW_EXPIRE
        await query.edit_message_text(
            "✍️ <b>Своя дата</b>\n\n"
            "<blockquote>Пришли дату в виде <code>31.12.2026</code> "
            "или <code>-</code> — без срока.</blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="promo_new_back")]]))
        return
    # срок
    row = [InlineKeyboardButton("без срока" if n == 0 else f"{n} дн.",
                                callback_data=f"promo_new_days:{n}") for n in TERM_DAYS]
    kb = [row[:3], row[3:], [InlineKeyboardButton("✍️ Своя дата",
                                                  callback_data="promo_new_ask:date_own")],
          [InlineKeyboardButton("◀️ Назад", callback_data="promo_new_back")]]
    await query.edit_message_text(
        "📅 <b>Сколько код живёт?</b>\n\n"
        "<blockquote>Короткий срок работает лучше: есть повод воспользоваться сейчас.</blockquote>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def handle_promo_new_set(query, context, field: str, value: str):
    d = _draft(context)
    if field == "reward":
        kind, val = value.split(":")
        d["kind"], d["value"] = kind, int(val)
    elif field == "limit":
        d["max_uses"] = int(value)
    elif field == "days":
        days = int(value)
        d["expires_at"] = ((datetime.now() + timedelta(days=days)).strftime(DAY_FMT)
                           if days else None)
    elif field == "first":
        d["first_only"] = 0 if d.get("first_only") else 1
    await handle_promo_draft(query, context)


async def handle_promo_new_save(query, context):
    from paidsub.storage import create_promo, get_promo
    d = _draft(context)
    code, value = d.get("code"), int(d.get("value", 0) or 0)
    if not code or not value:
        await handle_promo_draft(query, context, note="<i>Сначала выбери награду.</i>")
        return
    if await get_promo(code):
        await handle_promo_draft(query, context, note="<i>Такой код уже есть — поменяй текст.</i>")
        return
    kind = d.get("kind", "percent")
    ok = await create_promo(
        code, value if kind == "percent" else 0, d.get("expires_at"),
        max_uses=int(d.get("max_uses", 0) or 0), kind=kind,
        days=value if kind == "days" else 0, source="manual",
        first_only=int(d.get("first_only", 0) or 0),
    )
    context.user_data.pop("new_promo", None)
    if not ok:
        await handle_promo_menu(query, context, note="<i>❌ Не удалось создать код.</i>")
        return
    from log_channel import send_log
    await send_log(context.bot, f"🎟 Создан промокод <b>{code}</b> "
                                f"({reward_label(kind, value)})")
    await handle_promo_menu(query, context,
                            note=f"<i>✅ Код <code>{html.escape(code)}</code> создан — "
                                 f"{reward_text(kind, value)}.</i>")


# ── Партия кодов на акцию ────────────────────────────────────────────────────

async def handle_promo_batch(query, context):
    context.user_data.pop("state", None)
    kb = [[InlineKeyboardButton(f"{n} кодов", callback_data=f"promo_batch_n:{n}")
           for n in BATCH_SIZES[:2]],
          [InlineKeyboardButton(f"{n} кодов", callback_data=f"promo_batch_n:{n}")
           for n in BATCH_SIZES[2:]],
          [InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")]]
    await query.edit_message_text(
        "🎬 <b>Партия кодов</b>\n\n"
        "<blockquote>Бот сделает пачку одноразовых кодов с одной наградой — "
        f"их можно раздать где угодно. Каждый живёт {VALID_DAYS} дней "
        "и срабатывает один раз.</blockquote>\n\n"
        "<b>Сколько кодов сделать?</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def handle_promo_batch_n(query, context, count: int):
    kb = _presets_kb("promo_batch_go", f":{count}")
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="promo_batch")])
    await query.edit_message_text(
        f"🎬 <b>Партия из {count} кодов</b>\n\n<b>Какая награда?</b>\n"
        "<blockquote>−% — скидка на продление, +дн. — дни в подарок</blockquote>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def handle_promo_batch_go(query, context, kind: str, value: int, count: int):
    """Делает пачку кодов и сразу отдаёт их списком — копировать и раздавать."""
    from paidsub.storage import create_promo, unique_promo_code
    await query.edit_message_text(f"🎬 Делаю {count} кодов…", parse_mode="HTML")
    expires = (datetime.now() + timedelta(days=VALID_DAYS)).strftime(DAY_FMT)
    made = []
    for _ in range(int(count)):
        code = await unique_promo_code("AKC")
        ok = await create_promo(code, value if kind == "percent" else 0, expires,
                                max_uses=1, kind=kind,
                                days=value if kind == "days" else 0, source="batch",
                                note=f"Партия {datetime.now().strftime(DAY_FMT)}")
        if ok:
            made.append(code)
    from log_channel import send_log
    await send_log(context.bot, f"🎬 Партия промокодов: {len(made)} шт. "
                                f"({reward_label(kind, value)})")
    await query.edit_message_text(
        f"✅ <b>Готово: {len(made)} кодов</b>\n\n"
        f"<blockquote>🎁 Награда: <b>{reward_text(kind, value)}</b>\n"
        f"📅 Действуют до: <b>{expires}</b>\n"
        "🔢 Каждый — на одно применение</blockquote>\n\n"
        "<blockquote expandable>" + "\n".join(f"<code>{c}</code>" for c in made)
        + "</blockquote>\n\n<i>Нажми на код, чтобы скопировать.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Ещё партию", callback_data="promo_batch"),
             InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")]]))


# ── Поиск кода ───────────────────────────────────────────────────────────────

async def handle_promo_find(query, context):
    from states import AWAITING_PROMO_FIND
    context.user_data["state"] = AWAITING_PROMO_FIND
    await query.edit_message_text(
        "🔍 <b>Найти промокод</b>\n\n"
        "<blockquote>Пришли код или его часть: <code>SUMMER</code>, <code>BACK</code>, "
        "<code>AKC</code>.</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="promo_menu")]]))


async def handle_promo_search(msg, context, needle: str):
    from paidsub.storage import find_promos
    rows = await find_promos(needle, 20)
    context.user_data.pop("state", None)
    kb = [[InlineKeyboardButton(_promo_line(r), callback_data=f"promo_view:{r[0]}")] for r in rows]
    kb.append([InlineKeyboardButton("◀️ К промокодам", callback_data="promo_menu")])
    head = (f"🔍 <b>Нашёл: {len(rows)}</b>" if rows else "🔍 <b>Ничего не нашёл</b>")
    await msg.reply_text(
        f"{head}\n\n<blockquote>Запрос: <code>{html.escape(needle[:40])}</code></blockquote>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
