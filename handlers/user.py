from html import escape

from config import ADMIN_ID, load_config
from keyboards import main_keyboard, back_main, back_info


async def handle_my_sub(query):
    user_id = query.from_user.id
    from adminsub.storage import get_sub_by_tg_id
    row = await get_sub_by_tg_id(user_id)
    if not row:
        await query.edit_message_text(
            "📋 <b>Админская подписка</b>\n\nУ вас пока нет активной подписки.",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return
    _, tg_id, email, uuid_val, sub_id, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at = row
    traffic = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    from panel import get_client_info
    info = await get_client_info(email)
    if info.get("success"):
        enabled = info.get("enabled", True)
        status_line = "🟢 Статус: <b>активна</b>" if enabled else "🔴 Статус: <b>отключена</b>"
    else:
        status_line = "⚪ Статус: <b>неизвестен</b>"

    await query.edit_message_text(
        "📋 <b>Админская подписка</b>\n\n"
        f"📅 Действует до: <b>{expire}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n"
        f"{status_line}\n\n"
        f"🔗 <b>Ссылка подписки:</b>\n<code>{sub_url}</code>\n\n"
        "Скопируй ссылку и вставь в приложение (INCY, Happ и др.)",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


def _fmt_bytes_user(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} КБ"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} МБ"
    return f"{b / 1024 ** 3:.2f} ГБ"


def _progress_bar(used_gb: float, total_gb: int) -> str:
    if total_gb <= 0:
        return ""
    ratio = min(used_gb / total_gb, 1.0)
    filled = int(ratio * 10)
    empty = 10 - filled
    bar = "▓" * filled + "░" * empty
    pct = int(ratio * 100)
    return f"[{bar}] {pct}%"


async def handle_my_paid_sub(query):
    """Действия с подпиской: сама информация живёт на главном экране."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user_id = query.from_user.id
    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub_by_tg_id(user_id)
    if not row:
        await query.edit_message_text(
            "⚙️ <b>Моя подписка</b>\n\n"
            "<blockquote>Подписки пока нет.</blockquote>",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return
    email, sub_url, limit_hwid = row[2], row[5], row[8]
    status = row[11] if len(row) > 11 else "active"
    renewed = row[12] if len(row) > 12 else 0

    from panel import get_client_info
    info = await get_client_info(email)
    enabled = info.get("enabled", True) if info.get("success") else True

    plan = "⭐️ Премиум" if renewed else "🆓 Пробный период"
    if status == "expired":
        mark = "🔴 Закончилась"
    elif not enabled:
        mark = "❄️ Заморожена"
    elif status == "renewal":
        mark = "🟡 Ждёт оплаты"
    else:
        mark = "🟢 Активна"

    # выключенные функции прячем от пользователей, админ видит всё
    import maintenance as mnt
    _is_adm = user_id == ADMIN_ID

    def _on(key: str) -> bool:
        return _is_adm or mnt.feature_enabled(key)

    kb_rows = []
    # Кнопка "Скопировать ссылку": CopyTextButton если поддерживается, иначе callback
    try:
        from telegram import CopyTextButton
        copy_btn = InlineKeyboardButton("📋 Скопировать ссылку", copy_text=CopyTextButton(text=sub_url))
    except (ImportError, TypeError):
        copy_btn = InlineKeyboardButton("📋 Скопировать ссылку", callback_data="copy_sub")
    kb_rows.append([copy_btn, InlineKeyboardButton("🔳 QR-код", callback_data="qr_code")])
    # продлевать можно в любой момент: остаток срока при оплате не сгорает
    if _on("payments"):
        kb_rows.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")])
    # устройства и перевыпуск — второстепенное, кладём парой в один ряд
    pair = []
    if limit_hwid and _on("subscription"):
        pair.append(InlineKeyboardButton("📱 Устройства", callback_data="my_devices"))
    # во время окна оплаты доступ ещё работает — перевыпуск должен быть доступен,
    # иначе при утечке ключа человеку нечего сделать до продления
    if status in ("active", "renewal") and enabled and _on("reissue"):
        pair.append(InlineKeyboardButton("🔁 Новый ключ", callback_data="reissue_key"))
    if pair:
        kb_rows.append(pair)
    kb_rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])

    await query.edit_message_text(
        "⚙️ <b>Моя подписка</b>\n\n"
        f"<blockquote>{plan}  ·  {mark}</blockquote>\n\n"
        "<i>Скопируйте ссылку, продлите подписку или управляйте устройствами.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows),
        disable_web_page_preview=True,
    )


async def _sub_end(row):
    """Когда кончается текущий срок и сколько его осталось.

    Остаток не сгорает — оплата прибавляется к этой дате, поэтому её видно
    и на выборе тарифа, и в карточке.
    """
    from datetime import datetime
    from paidsub.storage import get_paid_sub, parse_sub_date
    now = datetime.now()
    if not row:
        return now, 0
    full = await get_paid_sub(row[0])
    raw = full[18] if full and len(full) > 18 and full[18] else None
    end = parse_sub_date(raw) if raw else parse_sub_date(row[6])
    if not end or end <= now:
        return now, 0
    return end, int((end - now).total_seconds())


async def _left_line(row) -> str:
    """Строка про текущий остаток. Пусто, если переносить нечего."""
    _end, left = await _sub_end(row)
    if left < 60:
        return ""
    return "<i>Остаток не сгорит — дни прибавятся.</i>"


async def handle_renew_sub(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user = query.from_user
    cfg = load_config()

    from paidsub.storage import get_paid_sub_by_tg_id, sub_settings
    row = await get_paid_sub_by_tg_id(user.id)
    settings = sub_settings(row)
    price = settings["price"]
    pay_url = settings["pay_url"]
    pay_seconds = settings["pay_period"]
    from paidsub.time_parser import fmt_duration
    period_str = fmt_duration(pay_seconds)

    uname = f"@{user.username}" if user.username else f"id{user.id}"
    hint_text = f"{user.id} - {uname}"

    # Применённый промокод (если валиден)
    from paidsub.storage import get_pending_promo, update_paid_sub_field
    from paidsub.handlers import validate_promo, apply_discount
    promo_line = ""
    price_line = f"💵 Сумма: <b>{price} ₽</b>"
    promo_btn_row = [InlineKeyboardButton("🎟 Ввести промокод", callback_data="enter_promo")]
    pending = await get_pending_promo(user.id)
    if pending:
        promo, err = await validate_promo(pending, user.id)
        if promo:
            percent = promo[2]
            final_price = apply_discount(price, percent)
            price_line = f"💵 Сумма: <s>{price} ₽</s> → <b>{final_price} ₽</b>"
            promo_line = f"🎟 Промокод <b>{escape(str(promo[1]))}</b> · скидка <b>−{percent}%</b>"
            promo_btn_row = [InlineKeyboardButton("❌ Убрать промокод", callback_data="remove_promo")]
        else:
            # промокод стал невалидным — снимаем
            if row:
                await update_paid_sub_field(row[0], "pending_promo", None)

    from handlers.payprovider import current_provider
    provider = current_provider()

    # Platega: счёт выставляет бот, оплата засчитывается автоматически
    if provider == "platega":
        import platega_api as pg
        if pg.is_configured():
            from database import list_tariffs
            tariffs = await list_tariffs(only_active=True)

            # Есть тарифы — клиент выбирает срок сам
            if tariffs:
                discount = None
                if pending:
                    promo_ok, _ = await validate_promo(pending, user.id)
                    if promo_ok:
                        discount = promo_ok[2]

                kb = []
                for t_id, name, t_period, t_price, _a, _s in tariffs:
                    final = apply_discount(t_price, discount) if discount else t_price
                    label = f"{name}  ·  {final} ₽"
                    if discount:
                        label += f" (−{discount}%)"
                    kb.append([InlineKeyboardButton(
                        label, callback_data=f"tariff_pick:{t_id}"
                    )])
                kb.append(promo_btn_row)
                kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")])

                notes = [x for x in (promo_line, await _left_line(row)) if x]
                await query.edit_message_text(
                    "💳 <b>Продление подписки</b>\n\n"
                    "Выберите срок — оплата пройдёт прямо здесь, в боте."
                    + ("\n\n" + "\n".join(notes) if notes else ""),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(kb),
                )
                return

            # Тарифов нет — срок и цена берутся из самой подписки,
            # но экран тот же: там же добираются устройства
            await handle_tariff_pick(query, None, 0)
            return
        # ключи не заданы — не оставляем человека без вариантов
        pay_url = pay_url or ""

    kb = []
    if pay_url:
        kb.append([InlineKeyboardButton("💳 Оплатить", url=pay_url)])
    kb.append(promo_btn_row)
    kb.append([InlineKeyboardButton("✅ Я оплатил", callback_data="i_paid")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")])

    await query.edit_message_text(
        "💳 <b>Продление подписки</b>\n\n"
        f"<blockquote>⏱ Срок: <b>{period_str}</b>\n"
        f"{price_line}"
        + (f"\n{promo_line}" if promo_line else "") + "</blockquote>\n\n"
        "<b>В комментарии к оплате укажите:</b>\n"
        f"<code>{hint_text}</code>\n\n"
        "<i>После оплаты нажмите «✅ Я оплатил» — мы проверим и продлим подписку.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def _offer_devices(row) -> tuple:
    """Что предложить по устройствам: цена, сколько ещё можно докупить.

    Докуп идёт только там, где лимит устройств вообще есть: при нулевом
    лимите панель их не считает, и слот было бы не к чему прибавить.
    Возвращает (цена, сколько ещё можно взять, текущий лимит, докуплено).
    """
    price, max_extra, limit_now, bought = _device_state(row)
    free = max(0, max_extra - bought)
    if not price or not limit_now or not free:
        return 0, 0, limit_now, bought
    return price, free, limit_now, bought


def _device_state(row) -> tuple:
    """Цена слота, потолок докупа, текущий лимит и сколько слотов оплачено."""
    cfg = load_config()
    price = int(cfg.get("device_price", 0) or 0)
    max_extra = int(cfg.get("device_max_extra", 0) or 0)
    limit_now = int(row[8] or 0) if row else 0
    bought = int(row[18] or 0) if row and len(row) > 18 else 0
    return price, max_extra, limit_now, bought


async def handle_tariff_pick(query, context, tariff_id: int = 0, devices=None):
    """Карточка тарифа: цена, до какого числа продлится, устройства — и сразу оплата."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import timedelta
    from database import get_tariff
    from paidsub.storage import get_paid_sub_by_tg_id, sub_settings, get_pending_promo
    from paidsub.handlers import validate_promo, apply_discount
    from paidsub.time_parser import fmt_duration

    user = query.from_user
    row = await get_paid_sub_by_tg_id(user.id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    settings = sub_settings(row)

    if tariff_id:
        t = await get_tariff(tariff_id)
        if not t or not t[4]:
            await query.answer("Тариф больше недоступен", show_alert=True)
            await handle_renew_sub(query)
            return
        name, pay_seconds, price = t[1], t[2], int(t[3])
    else:
        name, pay_seconds, price = "Подписка", settings["pay_period"], int(settings["price"])

    # Промокод действует на срок, устройства считаются отдельно —
    # иначе скидка растекается на разовую покупку слотов
    discount = None
    promo_btn = [InlineKeyboardButton("🎟 Есть промокод", callback_data="enter_promo")]
    pending = await get_pending_promo(user.id)
    if pending:
        promo, _err = await validate_promo(pending, user.id)
        if promo:
            discount = promo[2]
            promo_btn = [InlineKeyboardButton(f"❌ Убрать промокод −{discount}%",
                                              callback_data="remove_promo")]
    period_price = apply_discount(price, discount) if discount else price

    # Устройства выбираются на новый период: по умолчанию столько же,
    # сколько сейчас, но можно отказаться и не платить за них
    from paidsub.storage import base_hwid as _base_hwid
    dev_price, dev_max, limit_now, bought = _device_state(row)
    own_limit = _base_hwid(limit_now, bought)
    if not own_limit:
        dev_price = 0
    devices = bought if devices is None else int(devices)
    devices = max(0, min(devices, dev_max))
    dev_sum = devices * dev_price
    total = period_price + dev_sum

    end, _left = await _sub_end(row)
    new_end = end + timedelta(seconds=pay_seconds)

    price_line = (f"💵 Цена: <s>{price} ₽</s> <b>{period_price} ₽</b>  (−{discount}%)"
                  if discount else f"💵 Цена: <b>{price} ₽</b>")
    card = [
        f"⏱ Срок: <b>{fmt_duration(pay_seconds)}</b>",
        price_line,
        f"📅 Продлится до: <b>{new_end.strftime('%d.%m.%Y')}</b>",
    ]
    lines = []

    kb = []
    if dev_price:
        dev_line = f"📱 Устройств: <b>{own_limit + devices}</b>"
        if devices:
            dev_line += f"  (+{devices} · {dev_sum} ₽)"
        card.append(dev_line)
        lines += ["<i>Нужно больше устройств? Добавьте места кнопками ниже.</i>"]
        row_btns = [InlineKeyboardButton(
            "✅ Без доп." if devices == 0 else "Без доп.",
            callback_data=f"tariff_pick:{tariff_id}:0")]
        for n in range(1, dev_max + 1):
            row_btns.append(InlineKeyboardButton(
                f"{'✅ ' if devices == n else ''}+{n}",
                callback_data=f"tariff_pick:{tariff_id}:{n}"))
            if len(row_btns) == 4:
                kb.append(row_btns)
                row_btns = []
        if row_btns:
            kb.append(row_btns)

    lines = ([f"💳 <b>Тариф «{escape(str(name))}»</b>", "",
              "<blockquote>" + "\n".join(card) + "</blockquote>", ""]
             + lines + ([""] if lines else [])
             + [f"💰 К оплате: <b>{total} ₽</b>"])

    kb.append(promo_btn)
    kb.append([InlineKeyboardButton(f"💳 Оплатить {total} ₽",
                                    callback_data=f"pay_invoice:{tariff_id}:{devices}")])
    kb.append([InlineKeyboardButton("◀️ К тарифам", callback_data="renew_sub")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_pay_invoice(query, context, tariff_id: int | None = None,
                             devices=None):
    """Создаёт счёт в Platega и отдаёт ссылку на оплату."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import platega_api as pg
    from database import add_payment, get_active_payment, get_tariff
    from paidsub.storage import get_paid_sub_by_tg_id, sub_settings, get_pending_promo
    from paidsub.handlers import validate_promo, apply_discount

    user = query.from_user
    if not pg.is_configured():
        await query.answer("Оплата временно недоступна", show_alert=True)
        return

    row = await get_paid_sub_by_tg_id(user.id)
    settings = sub_settings(row)

    # Тариф задаёт и цену, и срок; иначе берём условия самой подписки
    tariff_name = None
    if tariff_id:
        t = await get_tariff(tariff_id)
        if not t or not t[4]:
            await query.answer("Тариф больше недоступен", show_alert=True)
            await handle_renew_sub(query)
            return
        tariff_name, pay_seconds, price = t[1], t[2], int(t[3])
    else:
        price = int(settings["price"])
        pay_seconds = settings["pay_period"]

    promo_code = None
    pending = await get_pending_promo(user.id)
    if pending:
        promo, err = await validate_promo(pending, user.id)
        if promo:
            promo_code = promo[1]
            price = apply_discount(price, promo[2])

    # Устройства едут тем же счётом: сколько выбрал, столько и будет
    # на новый период. Количество перепроверяем здесь — callback можно
    # прислать и руками, а слоты это деньги
    from paidsub.storage import base_hwid as _base_hwid
    dev_price, dev_max, limit_now, bought = _device_state(row)
    if not _base_hwid(limit_now, bought):
        dev_price = 0
    devices = bought if devices is None else int(devices)
    devices = max(0, min(devices, dev_max if dev_price else 0))
    dev_sum = devices * dev_price
    price += dev_sum
    # по этой пометке фоновая задача поймёт, что в счёте был выбор устройств
    pay_kind = "period_dev" if dev_price else "period"

    # уже есть неоплаченный счёт на ту же сумму, срок и набор устройств —
    # переиспользуем ссылку, чтобы не плодить счета при повторных нажатиях
    existing = await get_active_payment(user.id, "platega")
    same_extra = (len(existing) < 12 or existing[11] == devices) if existing else False
    if existing and existing[4] == price and existing[5] == pay_seconds and existing[8] and same_extra:
        await _send_invoice(query, existing[8], price, tariff_name, pay_seconds, devices)
        return

    await query.edit_message_text("⏳ Готовлю счёт…")
    desc = f"Подписка Drebol VPN"
    if tariff_name:
        desc += f" · {tariff_name}"
    if devices:
        desc += f" · +{devices} устр."
    result = await pg.create_payment(
        amount=price,
        description=f"{desc} · {user.id}",
        tg_id=user.id,
        username=user.username,
    )
    if not result["ok"]:
        await query.edit_message_text(
            "😕 <b>Не получилось создать счёт</b>\n\n"
            "<blockquote>Платёжная система не ответила. Деньги не списаны.</blockquote>\n\n"
            "<i>Попробуйте ещё раз через минуту или напишите нам.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Попробовать ещё раз",
                                      callback_data=f"pay_invoice:{tariff_id or 0}:{devices}")],
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open"),
                 InlineKeyboardButton("◀️ Назад", callback_data="renew_sub")],
            ]),
        )
        from config import ADMIN_ID
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ <b>Ошибка создания счёта Platega</b>\n\n"
                    f"👤 <code>{user.id}</code>\n"
                    f"<code>{result['error']}</code>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    await add_payment(
        tg_id=user.id, provider="platega",
        external_id=result["transaction_id"], amount=price,
        period_seconds=pay_seconds, pay_url=result["url"],
        promo_code=promo_code, kind=pay_kind, extra=devices,
    )
    await _send_invoice(query, result["url"], price, tariff_name, pay_seconds, devices)


async def _send_invoice(query, url: str, price: int,
                        tariff_name: str | None = None,
                        period_seconds: int | None = None,
                        devices: int = 0):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.time_parser import fmt_duration
    from html import escape as _esc

    parts = []
    if tariff_name:
        parts.append(_esc(str(tariff_name)))
    # срок дописываем, только если название тарифа его не называет («3 месяца»)
    if period_seconds and not any(ch.isdigit() for ch in str(tariff_name or "")):
        parts.append(fmt_duration(period_seconds))
    if devices:
        parts.append(f"+{devices} устр.")
    what = "  ·  ".join(parts)

    await query.edit_message_text(
        "🧾 <b>Счёт готов</b>\n\n"
        f"<blockquote>💰 Сумма: <b>{price} ₽</b>"
        + (f"\n📦 {what}" if what else "") + "</blockquote>\n\n"
        "<i>Оплатите по кнопке ниже — подписка продлится сама, "
        "как только платёж пройдёт.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💳 Оплатить {price} ₽", url=url)],
            [InlineKeyboardButton("◀️ Назад", callback_data="renew_sub")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_enter_promo(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_PROMO_CODE
    context.user_data["state"] = AWAITING_PROMO_CODE
    await query.edit_message_text(
        "🎟 <b>Промокод</b>\n\n"
        "Отправьте код одним сообщением — скидка сразу применится к оплате.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К оплате", callback_data="renew_sub")]
        ]),
    )


async def handle_remove_promo(query, context):
    context.user_data.pop("state", None)
    from paidsub.storage import get_paid_sub_by_tg_id, update_paid_sub_field
    row = await get_paid_sub_by_tg_id(query.from_user.id)
    if row:
        await update_paid_sub_field(row[0], "pending_promo", None)
    await handle_renew_sub(query)


async def handle_i_paid(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import datetime
    user = query.from_user

    from paidsub.storage import is_payment_pending, get_paid_sub_by_tg_id, update_paid_sub_field, get_muted_until, get_paid_sub
    muted = await get_muted_until(user.id)
    if muted:
        muted_dt = None
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                muted_dt = datetime.strptime(muted, fmt)
                break
            except ValueError:
                continue
        if muted_dt and datetime.now() < muted_dt:
            await query.edit_message_text(
                "🔇 <b>Заявки временно недоступны</b>\n\n"
                f"<blockquote>Можно будет отправить после <b>{muted}</b>.</blockquote>\n\n"
                "<i>Если это ошибка — напишите в поддержку.</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
                ]),
            )
            return

    if await is_payment_pending(user.id):
        await query.edit_message_text(
            "⏳ <b>Заявка уже у нас</b>\n\n"
            "<blockquote>Мы проверяем оплату. Как только всё подтвердится — "
            "подписка продлится, а вам придёт уведомление.</blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
            ]),
        )
        return

    row = await get_paid_sub_by_tg_id(user.id)
    if row:
        await update_paid_sub_field(row[0], "payment_pending", 1)

    uname = f"@{user.username}" if user.username else f"id{user.id}"

    await query.edit_message_text(
        "✅ <b>Заявка отправлена</b>\n\n"
        "<blockquote>Мы проверим оплату и продлим подписку. "
        "Уведомление придёт сюда, в бот.</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
        ]),
    )

    from config import ADMIN_ID
    row = await get_paid_sub_by_tg_id(user.id)
    sub_info = ""
    if row:
        sub_info = f"📧 <code>{row[2]}</code>\n📅 Подписка до: <b>{row[6]}</b>\n"

    cfg = load_config()
    # цена по условиям самой подписки, дальше применится промокод
    from paidsub.storage import sub_settings
    price = sub_settings(row)["price"]

    from paidsub.storage import get_pending_promo
    from paidsub.handlers import validate_promo, apply_discount
    promo_admin_line = ""
    pending = await get_pending_promo(user.id)
    if pending:
        promo, err = await validate_promo(pending, user.id)
        if promo:
            percent = promo[2]
            final_price = apply_discount(price, percent)
            promo_admin_line = (
                f"🎟 Промокод: <b>{escape(str(promo[1]))}</b> (−{percent}%)\n"
                f"💵 К оплате: <s>{price} ₽</s> → <b>{final_price} ₽</b>"
            )
    if not promo_admin_line:
        promo_admin_line = f"💵 К оплате: <b>{price} ₽</b>"

    if user.username:
        link_line = f'⛓‍💥 <a href="https://t.me/{user.username}">Написать</a>'
    else:
        link_line = f'⛓‍💥 <a href="tg://user?id={user.id}">Написать</a>'

    from paidsub.keyboards import payment_approve_keyboard
    kb = payment_approve_keyboard(user.id)

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"💰 <b>Заявка на оплату</b>\n\n"
            f'👤 <a href="tg://user?id={user.id}">{escape(str(user.first_name or user.id))}</a> '
            f"({escape(str(uname))})  ·  <code>{user.id}</code>\n"
            f"{link_line}\n\n"
            f"<blockquote>{sub_info}{promo_admin_line}</blockquote>\n\n"
            "<i>Проверьте поступление и подтвердите или отклоните.</i>"
        ),
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


async def handle_news(query):
    await query.edit_message_text(
        "📰 <b>Новости</b>\n\n"
        "<blockquote>Новостей пока нет — загляните позже.</blockquote>",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def handle_how_to(query):
    await query.edit_message_text(
        "❓ <b>Как подключиться</b>\n"
        "Четыре шага, пара минут.\n\n"
        "<b>1️⃣ Установите INCY</b>  <i>— рекомендуем</i>\n"
        "<blockquote>"
        "<a href=\"https://apps.apple.com/ru/app/incy/id6756943388\">iOS</a>  ·  "
        "<a href=\"https://play.google.com/store/apps/details?id=llc.itdev.incy\">Android</a>  ·  "
        "<a href=\"https://github.com/INCY-DEV/incy-platforms/releases/latest/download/incy-windows-setup.exe\">Windows</a>  ·  "
        "<a href=\"https://apps.apple.com/ru/app/incy/id6756943388\">macOS</a>"
        "</blockquote>\n\n"
        "<b>2️⃣ Скопируйте ссылку подписки</b>\n"
        "На главном экране нажмите на ссылку — она скопируется.\n\n"
        "<b>3️⃣ Вставьте её в приложение</b>\n"
        "Серверы подтянутся сами.\n\n"
        "<b>4️⃣ Выберите сервер и включите VPN</b> ✅\n\n"
        "🔄 <b>Если INCY не подошёл — Happ</b>\n"
        "<blockquote>"
        "<a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">iOS</a>  ·  "
        "<a href=\"https://play.google.com/store/apps/details?id=com.happproxy\">Android</a>  ·  "
        "<a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe\">Windows</a>  ·  "
        "<a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">macOS</a>"
        "</blockquote>\n"
        "<i>Дальше всё так же: скопируйте ссылку и вставьте её в Happ.</i>",
        parse_mode="HTML",
        reply_markup=back_info(),
        disable_web_page_preview=True,
    )


async def handle_buy(query):
    await query.edit_message_text(
        "🛒 <b>Покупка VPN</b>\n\n<blockquote>Раздел скоро появится.</blockquote>",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def handle_about(query):
    cfg = load_config()
    privacy_url = cfg.get("privacy_url", "")
    terms_url = cfg.get("terms_url", "")

    lines = [
        "📕 <b>О сервисе</b>",
        "<b>Drebol VPN</b> — быстрый VPN без логов, который живёт в Telegram.", "",
        "<blockquote>🖥 <b>Любая платформа</b>\n"
        "iOS, Android, Windows и macOS\n\n"
        "🛡 <b>Без логов</b>\n"
        "Не храним данные о вашей активности\n\n"
        "💳 <b>Честные платежи</b>\n"
        "Без скрытых списаний и автопродления</blockquote>",
    ]
    docs = []
    if privacy_url:
        docs.append(f'<a href="{privacy_url}">Политика конфиденциальности</a>')
    if terms_url:
        docs.append(f'<a href="{terms_url}">Пользовательское соглашение</a>')
    if docs:
        lines += ["", "📄 " + "  ·  ".join(docs)]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_info(),
        disable_web_page_preview=True,
    )


async def handle_prices(query):
    """Витрина цен: сколько стоит и что входит."""
    from paidsub.time_parser import fmt_duration
    cfg = load_config()

    price = cfg.get("paid_price", 0) or 0
    pay_period = cfg.get("paid_pay_period")
    trial_period = cfg.get("paid_trial_period")
    traffic = int(cfg.get("paid_preset_traffic", 0) or 0)
    # устройства — это лимит HWID из настроек платных подписок
    devices = int(cfg.get("paid_preset_hwid", 0) or 0)
    device_price = int(cfg.get("device_price", 0) or 0)

    lines = ["💰 <b>Цены</b>", ""]
    if trial_period:
        lines += [f"🆓 <b>Пробный период</b> — {fmt_duration(trial_period)} бесплатно", ""]

    # Тарифы — то же, что человек увидит при продлении.
    # Пока их нет, показываем одну цену из общих настроек.
    from database import list_tariffs
    tariffs = await list_tariffs(only_active=True)
    if tariffs:
        lines.append("💳 <b>Тарифы</b>")
        rows = []
        base = None
        for _id, name, t_period, t_price, _a, _s in tariffs:
            per_month = t_price / (t_period / 2592000) if t_period else None
            note = ""
            # выгода длинных тарифов относительно самого короткого
            if base and per_month and per_month < base * 0.97:
                note = f"  <i>выгода {round((1 - per_month / base) * 100)}%</i>"
            if base is None and per_month:
                base = per_month
            rows.append(f"{escape(str(name))} — <b>{t_price} ₽</b>{note}")
        lines.append("<blockquote>" + "\n".join(rows) + "</blockquote>")
    elif price:
        lines.append("💳 <b>Подписка</b>")
        period = f" за {fmt_duration(pay_period)}" if pay_period else ""
        lines.append(f"<blockquote><b>{price} ₽</b>{period}</blockquote>")

    if devices > 0:
        word = "устройства" if devices % 10 == 1 and devices % 100 != 11 else "устройств"
        dev_line = f"📱 До {devices} {word} одновременно"
    else:
        dev_line = "📱 Без ограничения устройств"
    perks = [dev_line,
             "📶 Безлимитный трафик" if traffic <= 0 else f"📶 {traffic} ГБ трафика",
             "🖥 iOS, Android, Windows, macOS"]
    if devices > 0 and device_price > 0:
        perks.append(f"➕ Доп. устройство — {device_price} ₽")
    lines += ["", "✨ <b>В каждом тарифе</b>",
              "<blockquote>" + "\n".join(perks) + "</blockquote>"]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_info(),
    )


async def handle_copy_sub(query, context):
    """Фолбэк для старых версий Telegram: присылает ссылку отдельным сообщением."""
    user_id = query.from_user.id
    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub_by_tg_id(user_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    sub_url = row[5]
    await context.bot.send_message(
        chat_id=user_id,
        text=f"<code>{sub_url}</code>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def handle_qr_code(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_paid_sub_by_tg_id
    user_id = query.from_user.id
    row = await get_paid_sub_by_tg_id(user_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    sub_url = row[5]
    try:
        import qrcode
        from io import BytesIO
        qr = qrcode.make(sub_url)
        buf = BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)
        await context.bot.send_photo(
            chat_id=user_id,
            photo=buf,
            caption="🔳 <b>QR-код подписки</b>\n\n"
                    "<i>Отсканируйте его в INCY или Happ — подписка добавится сама.</i>",
            parse_mode="HTML",
        )
        await query.answer()
    except ImportError:
        await query.answer("QR-генератор недоступен на сервере", show_alert=True)


async def handle_reissue_key(query, context):
    """Спрашивает подтверждение: перевыпуск рвёт доступ на всех устройствах."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub_by_tg_id(query.from_user.id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    await query.edit_message_text(
        "🔁 <b>Перевыпустить ключ?</b>\n\n"
        "<blockquote>⚠️ Старая ссылка перестанет работать на всех устройствах. "
        "Новую нужно будет заново вставить в приложение.</blockquote>\n\n"
        "<i>Пригодится, если ссылка попала в чужие руки.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Да, перевыпустить", callback_data="reissue_do")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="my_paid_sub")],
        ]),
    )


async def handle_reissue_do(query, context):
    """Меняет ссылку подписки: новый subId и UUID, данные подписки на месте."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_paid_sub_by_tg_id, update_paid_sub_field, add_history
    from log_channel import send_log

    user_id = query.from_user.id
    row = await get_paid_sub_by_tg_id(user_id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    sub_id, email = row[0], row[2]

    await query.edit_message_text("⏳ Перевыпускаю ключ…")

    from panel import reissue_subscription
    result = await reissue_subscription(email)
    if not result["success"]:
        # техническая причина нужна админу, человеку — что делать дальше
        await send_log(context.bot,
            f"⚠️ Перевыпуск не удался: <code>{user_id}</code>\n"
            f"<code>{escape(str(result['error']))}</code>")
        await query.edit_message_text(
            "😕 <b>Не получилось</b>\n\n"
            "<blockquote>Ничего не сломалось — старая ссылка продолжает работать.</blockquote>\n\n"
            "<i>Попробуйте чуть позже или напишите в поддержку.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open"),
                 InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")],
            ]),
        )
        return

    new_url = result["sub_url"]
    await update_paid_sub_field(sub_id, "uuid", result["new_uuid"])
    await update_paid_sub_field(sub_id, "sub_id", result["sub_id"])
    await update_paid_sub_field(sub_id, "sub_url", new_url)
    await add_history(user_id, "key_reissued", f"Новая ссылка: {new_url}")

    # Часть инбаундов могла не принять правку: там останется старый доступ,
    # и человек этого не увидит — зовём админа
    missed = result.get("failed_inbounds") or []
    await send_log(context.bot,
        f"🔁 Перевыпуск ключа: <code>{user_id}</code>\n"
        f"🔗 {escape(new_url)}"
        + (f"\n⚠️ Не приняли инбаунды: <code>{missed}</code>" if missed else "")
    )

    try:
        from telegram import CopyTextButton
        copy_btn = InlineKeyboardButton("📋 Скопировать ссылку",
                                        copy_text=CopyTextButton(text=new_url))
    except (ImportError, TypeError):
        copy_btn = InlineKeyboardButton("📋 Скопировать ссылку", callback_data="copy_sub")

    await query.edit_message_text(
        "✅ <b>Ключ перевыпущен</b>\n\n"
        "🔑 <b>Новая ссылка</b>\n"
        f"<code>{escape(new_url)}</code>\n\n"
        "<i>Удалите старую подписку в приложении и вставьте эту.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [copy_btn, InlineKeyboardButton("🔳 QR-код", callback_data="qr_code")],
            [InlineKeyboardButton("◀️ К подписке", callback_data="my_paid_sub")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_referral(query, context):
    user = query.from_user
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"

    from paidsub.storage import get_referral_stats, get_referral_list
    from paidsub.time_parser import fmt_duration
    from database import get_user_info

    stats = await get_referral_stats(user.id)
    ref_rows = await get_referral_list(user.id)
    cfg = load_config()
    bonus = cfg.get("referral_bonus")
    invited_bonus = cfg.get("referral_invited_bonus")
    head = ["👥 <b>Приглашайте друзей</b>",
            "И получайте дни к подписке за каждого."]
    gifts = []
    if bonus:
        gifts.append(f"🎁 Вам: <b>+{fmt_duration(bonus)}</b> за каждого друга")
    if invited_bonus:
        gifts.append(f"🤝 Другу: <b>+{fmt_duration(invited_bonus)}</b> при регистрации")
    if gifts:
        head += ["", "<blockquote>" + "\n".join(gifts) + "</blockquote>"]

    stat = [f"👤 Приглашено: <b>{stats['total']}</b>",
            f"✅ Получили бонус: <b>{stats['rewarded']}</b>"]
    if stats["total_bonus"] > 0:
        stat.append(f"⏱ Вам начислено: <b>+{fmt_duration(stats['total_bonus'])}</b>")
    body = ["📊 <b>Ваша статистика</b>",
            "<blockquote>" + "\n".join(stat) + "</blockquote>"]

    link = ["🔗 <b>Ваша ссылка</b>",
            f"<code>{ref_link}</code>",
            "<i>Нажмите, чтобы скопировать, или поделитесь кнопкой ниже.</i>"]

    blocks = ["\n".join(head), "\n".join(body), "\n".join(link)]

    if ref_rows:
        invited = []
        for tg_id, rewarded, bonus_sec, created_at in ref_rows[:10]:
            u_info = await get_user_info(tg_id)
            name = escape(str(u_info[1] if u_info and u_info[1] else tg_id))
            when = _ref_date(created_at)
            mark = "✅" if rewarded else "⏳"
            gift = (f"+{fmt_duration(bonus_sec)}" if rewarded and bonus_sec
                    else "бонус после оплаты")
            invited.append(f"{mark} <b>{name}</b> · {when} · {gift}")
        if len(ref_rows) > 10:
            invited.append(f"<i>…и ещё {len(ref_rows) - 10}</i>")
        blocks.append("👥 <b>Приглашённые</b>\n<blockquote expandable>"
                      + "\n".join(invited) + "</blockquote>")

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    share_text = "Попробуй Drebol VPN — быстрый и безопасный VPN!"
    share_url = f"https://t.me/share/url?url={ref_link}&text={share_text}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Поделиться с другом", url=share_url)],
        [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")],
    ])

    await query.edit_message_text(
        "\n\n".join(blocks),
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


def _ref_date(raw) -> str:
    """Дата приглашения в привычном виде. База хранит её как YYYY-MM-DD."""
    from datetime import datetime
    text = str(raw or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return text


async def handle_info(query):
    """Раздел «Инфо»: как подключиться, цены, документы."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        "ℹ️ <b>Информация</b>\n\n"
        "<i>Как подключиться, сколько стоит и кто мы.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❓ Как подключиться", callback_data="how_to")],
            [InlineKeyboardButton("💰 Цены", callback_data="prices"),
             InlineKeyboardButton("📕 О сервисе", callback_data="about")],
            [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")],
        ]),
    )


# Приложения, которыми подключаются: как оно представляется → как показываем.
# Панель кладёт название по-разному (userAgent, appName…), поэтому ищем по всему
_APPS = (
    ("happ", "Happ"), ("incy", "INCY"), ("hiddify", "Hiddify"),
    ("streisand", "Streisand"), ("shadowrocket", "Shadowrocket"),
    ("v2rayng", "v2RayNG"), ("v2rayn", "v2RayN"), ("v2box", "V2Box"),
    ("nekobox", "NekoBox"), ("nekoray", "NekoRay"), ("sing-box", "sing-box"),
    ("singbox", "sing-box"), ("clash", "Clash"), ("foxray", "FoXray"),
    ("karing", "Karing"), ("exclave", "Exclave"), ("throne", "Throne"),
    ("husi", "Husi"), ("loon", "Loon"), ("stash", "Stash"), ("quantumult", "Quantumult"),
)

_OS_ICONS = (("ios", "🍎"), ("mac", "🍎"), ("iphone", "🍎"), ("ipad", "🍎"),
             ("android", "🤖"), ("windows", "🪟"), ("win", "🪟"),
             ("linux", "🐧"), ("tv", "📺"))


def _pick(item: dict, *keys) -> str:
    for k in keys:
        val = item.get(k)
        if val:
            return str(val).strip()
    return ""


def _device_app(item: dict) -> str:
    """Каким приложением подключались — Happ, INCY и так далее."""
    blob = " ".join(str(item.get(k, "")) for k in
                    ("userAgent", "user_agent", "ua", "appName", "app", "client",
                     "clientName", "deviceApp", "software", "platform")).lower()
    for needle, name in _APPS:
        if needle in blob:
            return name
    # «Happ/2.1.0 (iPhone)» — берём то, что стоит до слеша
    raw = _pick(item, "userAgent", "user_agent", "ua", "appName", "client")
    head = raw.split("/")[0].strip()
    return head if 1 < len(head) <= 20 else ""


def _device_title(item: dict) -> str:
    """Что за устройство: модель и система, насколько панель их знает."""
    model = _pick(item, "deviceModel", "model", "deviceName", "device", "name")
    system = _pick(item, "deviceOs", "os", "osVersion", "system", "platform")
    parts = [p for p in (model, system) if p]
    # «Windows 11 · Windows» или «iPhone · iPhone 15» — оставляем подробное
    if len(parts) == 2:
        a, b = parts[0].lower(), parts[1].lower()
        if a in b:
            parts.pop(0)
        elif b in a:
            parts.pop(1)
    return " · ".join(parts) or "устройство"


def _os_icon(text: str) -> str:
    low = text.lower()
    for needle, icon in _OS_ICONS:
        if needle in low:
            return icon
    return "📱"


async def handle_my_devices(query, context=None):
    """Устройства клиента: что подключено, откуда и чем — и что можно отключить."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_paid_sub_by_tg_id
    from panel import get_client_hwids
    user = query.from_user
    row = await get_paid_sub_by_tg_id(user.id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    email, limit = row[2], int(row[8] or 0)
    await query.edit_message_text("📱 Смотрю устройства…")
    r = await get_client_hwids(email)
    cfg = load_config()
    price = int(cfg.get("device_price") or 0)
    max_extra = int(cfg.get("device_max_extra") or 5)
    bought = int(row[18]) if len(row) > 18 and row[18] else 0

    kb = []
    if not limit:
        lines = ["📱 <b>Устройства</b>", "",
                 "<blockquote>Без ограничений — подключайте сколько нужно.</blockquote>"]
    elif not r.get("ok"):
        lines = ["📱 <b>Устройства</b>", "",
                 f"<blockquote>Можно подключить: <b>до {limit}</b></blockquote>", "",
                 "<i>Список сейчас недоступен — загляните чуть позже.</i>"]
    else:
        items = r["items"]
        lines = ["📱 <b>Устройства</b>",
                 f"Подключено <b>{len(items)} из {limit}</b>", ""]
        for i, d in enumerate(items[:10], 1):
            title = _device_title(d)
            app = _device_app(d)
            when = _when_ms(_pick(d, "lastSeen", "lastUpdate", "updatedAt",
                                  "lastOnline", "createdAt", "time"))
            lines.append(f"{i}. {_os_icon(title)} <b>{escape(title)}</b>")
            tail = " · ".join(x for x in (f"📲 {escape(app)}" if app else "",
                                          f"был {when}" if when else "") if x)
            if tail:
                lines.append(f"      <i>{tail}</i>")
            # на кнопке только модель: длинный хвост с системой всё равно обрежется
            short = title.split(" · ")[0]
            if len(short) > 16:
                short = short[:15].rstrip() + "…"
            kb.append([InlineKeyboardButton(
                f"🗑 Отключить {i} · {short}",
                callback_data=f"dev_del:{str(d.get('id'))[:20]}")])
        if not items:
            lines.append("<blockquote>Пока ни одного — подключитесь в приложении.</blockquote>")
        else:
            if len(items) >= limit:
                lines += ["", "<blockquote>⚠️ Все места заняты — отключите лишнее "
                          "или добавьте ещё.</blockquote>"]
            lines += ["", "<i>Не узнали устройство? Отключите его "
                      "и перевыпустите ключ.</i>"]
    if limit and price > 0 and bought < max_extra:
        kb.append([InlineKeyboardButton(f"➕ Добавить место · {price} ₽",
                                        callback_data="dev_buy_menu")])
    kb.append([InlineKeyboardButton("◀️ К подписке", callback_data="my_paid_sub")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


def _when_ms(value) -> str:
    """Когда устройство было на связи.

    Панель отдаёт то миллисекунды, то секунды, то строку с датой —
    разбираем все варианты, а непонятное просто не показываем.
    """
    from datetime import datetime
    if value in (None, "", 0, "0"):
        return ""
    try:
        num = int(float(value))
        # секунды это или миллисекунды — видно по порядку числа
        if num > 10 ** 12:
            num //= 1000
        if num <= 0:
            return ""
        dt = datetime.fromtimestamp(num)
    except (TypeError, ValueError, OSError, OverflowError):
        text = str(value).strip().replace("T", " ")[:19]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S",
                    "%d.%m.%Y %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return ""
    today = datetime.now().date()
    if dt.date() == today:
        return f"сегодня в {dt.strftime('%H:%M')}"
    return dt.strftime("%d.%m в %H:%M")


async def handle_dev_del(query, context, ref: str):
    """Клиент сам отключает своё устройство и освобождает слот."""
    from paidsub.storage import get_paid_sub_by_tg_id
    from panel import delete_client_hwid, resolve_hwid
    row = await get_paid_sub_by_tg_id(query.from_user.id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
        return
    hwid_id = await resolve_hwid(row[2], ref)
    if hwid_id is None:
        await query.answer("Это устройство уже отключено", show_alert=True)
        await handle_my_devices(query, context)
        return
    res = await delete_client_hwid(row[2], hwid_id)
    await query.answer("Устройство отключено" if res.get("success")
                       else "Не получилось, попробуйте позже", show_alert=not res.get("success"))
    await handle_my_devices(query, context)


async def handle_dev_buy_menu(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_paid_sub_by_tg_id
    cfg = load_config()
    price = int(cfg.get("device_price") or 0)
    max_extra = int(cfg.get("device_max_extra") or 5)
    row = await get_paid_sub_by_tg_id(query.from_user.id)
    if not row or price <= 0:
        await query.answer("Сейчас недоступно", show_alert=True)
        return
    bought = int(row[18]) if len(row) > 18 and row[18] else 0
    left = max(0, max_extra - bought)
    if left <= 0:
        await query.answer("Больше устройств добавить нельзя", show_alert=True)
        return
    kb = [[InlineKeyboardButton(f"+{n} — {n * price} ₽", callback_data=f"dev_buy:{n}")]
          for n in range(1, min(3, left) + 1)]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_devices")])
    await query.edit_message_text(
        "➕ <b>Добавить устройства</b>\n\n"
        f"<blockquote>Одно место — <b>{price} ₽</b>\n"
        "Действует до конца оплаченного срока.</blockquote>\n\n"
        "<i>Сколько мест добавить?</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_dev_buy(query, context, count: int):
    """Счёт на докуп устройств — теми же платежами, что и продление."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import platega_api as pg
    from database import add_payment
    from paidsub.storage import get_paid_sub_by_tg_id
    user = query.from_user
    cfg = load_config()
    price = int(cfg.get("device_price") or 0)
    max_extra = int(cfg.get("device_max_extra") or 5)
    row = await get_paid_sub_by_tg_id(user.id)
    if not row or price <= 0 or not int(row[8] or 0):
        await query.answer("Сейчас недоступно", show_alert=True)
        return
    bought = int(row[18]) if len(row) > 18 and row[18] else 0
    count = max(1, min(int(count), max(0, max_extra - bought)))
    if not count:
        await query.answer("Больше устройств добавить нельзя", show_alert=True)
        return
    if not pg.is_configured():
        await query.edit_message_text(
            "➕ <b>Оплата сейчас недоступна</b>\n\n"
            "<blockquote>Напишите в поддержку — добавим устройства вручную.</blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open")],
                [InlineKeyboardButton("◀️ Назад", callback_data="my_devices")],
            ]),
        )
        return

    amount = count * price
    await query.edit_message_text("⏳ Готовлю счёт…")
    result = await pg.create_payment(
        amount=amount, description=f"Устройства Drebol VPN · +{count} · {user.id}",
        tg_id=user.id, username=user.username,
    )
    if not result["ok"]:
        await query.edit_message_text(
            "😕 <b>Не получилось создать счёт</b>\n\n"
            "<blockquote>Платёжная система не ответила. Деньги не списаны.</blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Попробовать ещё раз", callback_data="dev_buy_menu")],
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open")],
            ]),
        )
        return
    await add_payment(
        tg_id=user.id, provider="platega", external_id=result["transaction_id"],
        amount=amount, period_seconds=None, pay_url=result["url"],
        kind="devices", extra=count,
    )
    await query.edit_message_text(
        "🧾 <b>Счёт готов</b>\n\n"
        f"<blockquote>💰 Сумма: <b>{amount} ₽</b>\n"
        f"📱 Устройств: <b>+{count}</b></blockquote>\n\n"
        "<i>Оплатите по кнопке ниже — места добавятся сами.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💳 Оплатить {amount} ₽", url=result["url"])],
            [InlineKeyboardButton("📱 Мои устройства", callback_data="my_devices")],
        ]),
    )


# ── Главный экран ─────────────────────────────────────────────────────────────

# Кому прямо сейчас выдаётся триал: двойное нажатие «Я подписался» иначе
# создало бы в панели два клиента на одного человека
_ISSUING: set = set()


async def ensure_trial(user, context, on_start=None) -> bool:
    """Выдаёт пробный период сразу, без нажатия «Моя подписка».

    Срабатывает, только когда выдача без одобрения включена (⚡ Авто-триал),
    выдача триалов не выключена в техработах и пресеты заполнены. Админу и
    помощникам не выдаём. True — подписку только что создали.
    on_start вызывается перед созданием: показать «⏳ …», пока идёт панель.
    """
    from staff import is_helper
    if user.id == ADMIN_ID or is_helper(user.id):
        return False
    from paidsub.storage import (get_paid_sub_by_tg_id, get_muted_until,
                                 get_pending_request, add_request, resolve_request,
                                 add_history, parse_sub_date)
    if await get_paid_sub_by_tg_id(user.id):
        return False
    cfg = load_config()
    if not cfg.get("auto_approve_trial", False):
        return False
    import maintenance as mnt
    if not mnt.feature_enabled("trial"):
        return False
    from paidsub.handlers import _paid_presets_ready, do_create_paid_sub, _process_referral_bonus
    if not _paid_presets_ready(cfg):
        return False
    muted = await get_muted_until(user.id)
    if muted:
        from datetime import datetime
        until = parse_sub_date(muted)
        if until and datetime.now() < until:
            return False
    if user.id in _ISSUING:
        return False

    _ISSUING.add(user.id)
    try:
        if await get_paid_sub_by_tg_id(user.id):
            return False
        if on_start:
            try:
                await on_start()
            except Exception:
                pass
        if not await get_pending_request(user.id):
            await add_request(user.id)
        await resolve_request(user.id, "approved")
        await add_history(user.id, "trial_approved", "Авто-выдача при входе")

        replies = []

        async def _collect(text, **kw):
            replies.append(text)

        await do_create_paid_sub(None, user.id, context, _collect, trial=True, for_user=True)
        created = bool(await get_paid_sub_by_tg_id(user.id))

        from log_channel import send_log
        uname = escape(f"@{user.username}" if user.username else f"id{user.id}")
        who = escape(str(user.first_name or user.id))
        if created:
            await _process_referral_bonus(user.id, context)
            await send_log(context.bot,
                f"⚡ Триал выдан при входе: {who} ({uname}) · <code>{user.id}</code>")
        else:
            # панель не ответила — человек увидит обычное меню, а админ причину
            reason = escape(replies[-1][:300]) if replies else "неизвестно"
            await send_log(context.bot,
                f"⚠️ Не удалось выдать триал при входе: {who} · <code>{user.id}</code>\n"
                f"{reason}")
        return created
    finally:
        _ISSUING.discard(user.id)


async def _sub_summary(row, frozen: bool = False, extra=None) -> tuple:
    """Карточка подписки для главного экрана — цитатой, чтобы читалась блоком.

    extra — строки с трафиком и устройствами из _sub_facts (могут быть пустыми).
    Ссылку сюда не кладём: она идёт отдельным блоком под карточкой.
    Возвращает (карточка, работает_ли_доступ) — у закончившейся ссылку
    не показываем, там одна дорога: продлить.
    """
    from datetime import datetime
    from paidsub.storage import get_paid_sub, parse_sub_date
    from paidsub.time_parser import fmt_duration_precise
    status = row[11] if len(row) > 11 else "active"
    renewed = row[12] if len(row) > 12 else 0
    plan = "⭐️ <b>Премиум</b>" if renewed else "🆓 <b>Пробный период</b>"

    full = await get_paid_sub(row[0])
    end = parse_sub_date(full[18]) if full and len(full) > 18 and full[18] else None
    end = end or parse_sub_date(row[6])
    left = int((end - datetime.now()).total_seconds()) if end else 0

    if status == "expired" or (left <= 0 and status != "renewal"):
        return (f"<blockquote>{plan}  ·  🔴 Закончилась\n"
                "Продлите — доступ вернётся сразу.</blockquote>"), False

    if frozen:
        mark = "❄️ Заморожена"
    elif status == "renewal":
        mark = "🟡 Ждёт оплаты"
    else:
        mark = "🟢 Активна"
    until = end.strftime("%d.%m.%Y, %H:%M") if end else escape(str(row[6]))
    lines = [f"{plan}  ·  {mark}", "",
             f"⏳ Осталось: <b>{fmt_duration_precise(max(left, 0))}</b>",
             f"📅 Действует до: <b>{until}</b>"]
    lines += extra or []
    return "<blockquote>" + "\n".join(lines) + "</blockquote>", True


async def _sub_facts(row) -> list:
    """Трафик и устройства — то, что человек хочет видеть сразу.

    Панель может не ответить: тогда просто не показываем строку,
    а не пугаем ошибкой на главном экране.
    """
    email, limit_hwid, total_gb = row[2], int(row[8] or 0), int(row[9] or 0)
    lines = []
    try:
        from panel import get_client_traffic
        t = await get_client_traffic(email)
        if t.get("success"):
            used = t.get("up", 0) + t.get("down", 0)
            if total_gb > 0:
                lines.append(f"📊 Трафик: <b>{_fmt_bytes_user(used)}</b> из {total_gb} ГБ")
                lines.append(f"<code>{_progress_bar(used / 1024 ** 3, total_gb)}</code>")
            else:
                lines.append(f"📊 Трафик: <b>{_fmt_bytes_user(used)}</b> · без лимита")
    except Exception:
        pass
    if limit_hwid:
        lines.append(f"📱 Устройства: <b>до {limit_hwid}</b>")
    return lines


def _link_block(sub_url) -> str:
    """Ссылка подписки отдельным блоком: нажатие по <code> копирует её."""
    return ("🔑 <b>Ссылка для подключения</b>\n"
            f"<code>{escape(str(sub_url))}</code>\n"
            "<i>Нажмите на ссылку — она скопируется.</i>")


async def start_screen(user, fresh: bool = False):
    """Главный экран: приветствие, состояние подписки и меню."""
    from staff import is_helper
    from adminsub.storage import get_sub_by_tg_id
    from paidsub.storage import get_paid_sub_by_tg_id
    is_admin = user.id == ADMIN_ID
    has_sub = bool(await get_sub_by_tg_id(user.id))
    row = await get_paid_sub_by_tg_id(user.id)
    paid_status = (row[11] if len(row) > 11 else "active") if row else ""
    name = escape(str(user.first_name or user.id))

    if row:
        enabled = True
        try:
            from panel import get_client_info
            info = await get_client_info(row[2])
            enabled = info.get("enabled", True) if info.get("success") else True
        except Exception:
            pass
        card, alive = await _sub_summary(row, frozen=not enabled, extra=await _sub_facts(row))
        if fresh:
            text = (f"🎉 <b>{name}, пробный период активирован!</b>\n"
                    "Остался один шаг — подключиться.\n\n"
                    f"{card}\n\n"
                    f"{_link_block(row[5])}\n\n"
                    "<b>Как подключиться</b>\n"
                    "1️⃣ Скопируйте ссылку выше\n"
                    "2️⃣ Откройте приложение INCY и вставьте её\n"
                    "3️⃣ Включите VPN — готово ✅")
        else:
            text = (f"👋 Привет, {name}!\n"
                    "Ваша подписка <b>Drebol VPN</b>:\n\n"
                    f"{card}"
                    + (f"\n\n{_link_block(row[5])}" if alive else ""))
    else:
        text = (f"👋 Привет, {name}!\n"
                "Это <b>Drebol VPN</b> — быстрый VPN без логов 🔒\n\n"
                "<blockquote>⚡ Подключение за минуту\n"
                "📱 iOS · Android · Windows · macOS\n"
                "💬 Поддержка прямо в боте</blockquote>\n\n"
                "Выберите, что сделать 👇")
    return text, main_keyboard(is_admin, has_sub, paid_status, is_helper(user.id))


async def handle_back_start(query, user):
    text, markup = await start_screen(user)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup,
                                  disable_web_page_preview=True)


