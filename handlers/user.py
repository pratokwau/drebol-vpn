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

    from xui_api import get_client_info
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
            "⚙️ <b>Действия с подпиской</b>\n\nПодписки пока нет.",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return
    email, sub_url, limit_hwid = row[2], row[5], row[8]
    status = row[11] if len(row) > 11 else "active"
    renewed = row[12] if len(row) > 12 else 0

    from xui_api import get_client_info
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
    kb_rows.append([copy_btn, InlineKeyboardButton("📱 QR-код", callback_data="qr_code")])
    if limit_hwid and _on("subscription"):
        kb_rows.append([InlineKeyboardButton("📱 Мои устройства", callback_data="my_devices")])
    # продлевать можно в любой момент: остаток срока при оплате не сгорает
    if _on("payments"):
        kb_rows.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")])
    # во время окна оплаты доступ ещё работает — перевыпуск должен быть доступен,
    # иначе при утечке ключа человеку нечего сделать до продления
    if status in ("active", "renewal") and enabled and _on("reissue"):
        kb_rows.append([InlineKeyboardButton("🔁 Перевыпуск ключа", callback_data="reissue_key")])
    kb_rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])

    await query.edit_message_text(
        f"⚙️ <b>Действия с подпиской</b>\n\n{plan} · {mark}",
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
    price_line = f"💵 Сумма: <b>{price} ₽</b>\n"
    promo_btn_row = [InlineKeyboardButton("🎟 Ввести промокод", callback_data="enter_promo")]
    pending = await get_pending_promo(user.id)
    if pending:
        promo, err = await validate_promo(pending, user.id)
        if promo:
            percent = promo[2]
            final_price = apply_discount(price, percent)
            price_line = f"💵 Сумма: <s>{price} ₽</s> → <b>{final_price} ₽</b>\n"
            promo_line = f"🎟 Промокод <b>{promo[1]}</b>: скидка <b>−{percent}%</b>\n"
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
                    label = f"{name} — {final} ₽"
                    if discount:
                        label += f" (−{discount}%)"
                    kb.append([InlineKeyboardButton(
                        label, callback_data=f"tariff_pick:{t_id}"
                    )])
                kb.append(promo_btn_row)
                kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")])

                extra = (promo_line + await _left_line(row)).strip()
                await query.edit_message_text(
                    "💳 <b>Выберите тариф</b>" + (f"\n\n{extra}" if extra else ""),
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
        f"💳 <b>Продление · {period_str}</b>\n\n"
        f"{price_line}"
        f"{promo_line}\n"
        "В комментарии к оплате укажите:\n"
        f"<code>{hint_text}</code>\n\n"
        "Потом нажмите «✅ Я оплатил».",
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
    promo_btn = [InlineKeyboardButton("🎟 Промокод", callback_data="enter_promo")]
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

    price_line = (f"💵 <s>{price}</s> <b>{period_price} ₽</b>" if discount
                  else f"💵 <b>{price} ₽</b>")
    lines = [
        f"💳 <b>{escape(str(name))}</b> · {fmt_duration(pay_seconds)}",
        price_line,
        f"📅 Продлится до <b>{new_end.strftime('%d.%m.%Y')}</b>",
    ]

    kb = []
    if dev_price:
        dev_line = f"📱 Устройств: <b>{own_limit + devices}</b>"
        if devices:
            dev_line += f" (+{devices} · {dev_sum} ₽)"
        lines += ["", dev_line]
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

    lines += ["", f"💰 <b>К оплате: {total} ₽</b>"]

    kb.append(promo_btn)
    kb.append([InlineKeyboardButton(f"💳 Оплатить {total} ₽",
                                    callback_data=f"pay_invoice:{tariff_id}:{devices}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="renew_sub")])

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

    await query.edit_message_text("⏳ Создаю счёт...")
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
            "❌ <b>Не удалось создать счёт</b>\n\n"
            "Попробуйте ещё раз или напишите в поддержку.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз",
                                      callback_data=f"pay_invoice:{tariff_id or 0}:{devices}")],
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open")],
                [InlineKeyboardButton("◀️ Назад", callback_data="renew_sub")],
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
    if period_seconds:
        parts.append(fmt_duration(period_seconds))
    if devices:
        parts.append(f"+{devices} устр.")
    what = " · ".join(parts)

    await query.edit_message_text(
        f"💳 <b>Счёт на {price} ₽</b>\n"
        + (f"{what}\n" if what else "")
        + "\nОплатите — подписка продлится сама.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Перейти к оплате", url=url)],
            [InlineKeyboardButton("◀️ Назад", callback_data="renew_sub")],
        ]),
        disable_web_page_preview=True,
    )


async def handle_enter_promo(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_PROMO_CODE
    context.user_data["state"] = AWAITING_PROMO_CODE
    await query.edit_message_text(
        "🎟 <b>Введите промокод</b>",
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
                f"🔇 Запросы заблокированы до <b>{muted}</b>.\n"
                "Обратитесь к администратору.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
                ]),
            )
            return

    if await is_payment_pending(user.id):
        await query.edit_message_text(
            "⏳ <b>Заявка уже отправлена</b>\n\n"
            "Ваша заявка на оплату уже на рассмотрении.\n"
            "Ожидайте ответа администратора.",
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
        "✅ <b>Заявка отправлена!</b>\n\n"
        "Администратор проверит оплату и активирует вашу подписку.\n"
        "Вам придёт уведомление.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")]
        ]),
    )

    from config import ADMIN_ID
    row = await get_paid_sub_by_tg_id(user.id)
    sub_info = ""
    if row:
        sub_info = f"\n📧 Email: <code>{row[2]}</code>\n📅 До: <b>{row[6]}</b>"

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
                f"🎟 Промокод: <b>{promo[1]}</b> (−{percent}%)\n"
                f"💵 К оплате: <s>{price} ₽</s> → <b>{final_price} ₽</b>\n"
            )
    if not promo_admin_line:
        promo_admin_line = f"💵 Сумма: <b>{price} ₽</b>\n"

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
            f"({escape(str(uname))})\n"
            f"🆔 TG ID: <code>{user.id}</code>"
            f"{sub_info}\n"
            f"{promo_admin_line}\n"
            f"{link_line}"
        ),
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


async def handle_news(query):
    await query.edit_message_text(
        "📰 <b>Новости</b>\n\nНовостей пока нет. Следите за обновлениями!",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def handle_how_to(query):
    await query.edit_message_text(
        "❓ <b>Как подключиться</b>\n\n"
        "<b>1️⃣ Установите приложение INCY</b> — рекомендуем\n"
        "• <a href=\"https://apps.apple.com/ru/app/incy/id6756943388\">iOS</a>\n"
        "• <a href=\"https://play.google.com/store/apps/details?id=llc.itdev.incy\">Android</a>\n"
        "• <a href=\"https://github.com/INCY-DEV/incy-platforms/releases/latest/download/incy-windows-setup.exe\">Windows</a>\n"
        "• <a href=\"https://apps.apple.com/ru/app/incy/id6756943388\">macOS</a>\n\n"
        "<b>2️⃣ Скопируйте ссылку подписки</b>\n"
        "Откройте «👤 Моя подписка» и нажмите на ссылку — она скопируется.\n\n"
        "<b>3️⃣ Вставьте ссылку в приложение</b>\n"
        "Серверы подтянутся сами.\n\n"
        "<b>4️⃣ Выберите сервер и подключайтесь</b>\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🔄 <b>Запасной вариант — Happ</b>\n"
        "• <a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">iOS</a>\n"
        "• <a href=\"https://play.google.com/store/apps/details?id=com.happproxy\">Android</a>\n"
        "• <a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe\">Windows</a>\n"
        "• <a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">macOS</a>\n"
        "Дальше всё так же: скопируйте ссылку и вставьте её в Happ.",
        parse_mode="HTML",
        reply_markup=back_info(),
        disable_web_page_preview=True,
    )


async def handle_buy(query):
    await query.edit_message_text(
        "🛒 <b>Покупка VPN</b>\n\nРаздел в разработке.",
        parse_mode="HTML",
        reply_markup=back_main(),
    )


async def handle_about(query):
    cfg = load_config()
    privacy_url = cfg.get("privacy_url", "")
    terms_url = cfg.get("terms_url", "")

    lines = [
        "ℹ️ <b>О сервисе</b>", "",
        "🖥 <b>Любая платформа</b>",
        "iOS, Android, Windows и macOS", "",
        "🛡 <b>Без логов</b>",
        "Не храним данные о вашей активности", "",
        "💳 <b>Честные платежи</b>",
        "Без скрытых списаний и автопродления",
    ]
    docs = []
    if privacy_url:
        docs.append(f'• <a href="{privacy_url}">Политика конфиденциальности</a>')
    if terms_url:
        docs.append(f'• <a href="{terms_url}">Пользовательское соглашение</a>')
    if docs:
        lines += ["", "━━━━━━━━━━━━━━", "", "📕 <b>Документы</b>"] + docs

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
        lines += ["🆓 <b>Пробный период</b>",
                  f"{fmt_duration(trial_period)} — бесплатно", ""]

    # Тарифы — то же, что человек увидит при продлении.
    # Пока их нет, показываем одну цену из общих настроек.
    from database import list_tariffs
    tariffs = await list_tariffs(only_active=True)
    if tariffs:
        lines.append("💳 <b>Тарифы</b>")
        base = None
        for _id, name, t_period, t_price, _a, _s in tariffs:
            per_month = t_price / (t_period / 2592000) if t_period else None
            note = ""
            # выгода длинных тарифов относительно самого короткого
            if base and per_month and per_month < base * 0.97:
                note = f" · выгода {round((1 - per_month / base) * 100)}%"
            if base is None and per_month:
                base = per_month
            lines.append(f"• {escape(str(name))} — <b>{t_price} ₽</b>{note}")
    elif price:
        lines.append("💳 <b>Подписка</b>")
        period = f" · {fmt_duration(pay_period)}" if pay_period else ""
        lines.append(f"<b>{price} ₽</b>{period}")

    if devices > 0:
        word = "устройства" if devices % 10 == 1 and devices % 100 != 11 else "устройств"
        dev_line = f"📱 До {devices} {word} одновременно"
    else:
        dev_line = "📱 Без ограничения устройств"
    lines += ["", "━━━━━━━━━━━━━━", "",
              "✨ <b>Что входит</b>",
              dev_line,
              "📶 Безлимитный трафик" if traffic <= 0 else f"📶 {traffic} ГБ трафика",
              "🖥 iOS, Android, Windows, macOS"]
    if devices > 0 and device_price > 0:
        lines.append(f"➕ Доп. устройство — {device_price} ₽")

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
            caption="📱 <b>QR-код подписки</b>\n\nОтсканируйте в приложении INCY или Happ.",
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
        "Старая ссылка перестанет работать на всех устройствах.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, перевыпустить", callback_data="reissue_do")],
            [InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")],
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

    await query.edit_message_text("⏳ Перевыпускаю ключ...")

    from xui_api import reissue_subscription
    result = await reissue_subscription(email)
    if not result["success"]:
        # техническая причина нужна админу, человеку — что делать дальше
        await send_log(context.bot,
            f"⚠️ Перевыпуск не удался: <code>{user_id}</code>\n"
            f"<code>{escape(str(result['error']))}</code>")
        await query.edit_message_text(
            "❌ <b>Не получилось</b>\n\n"
            "Старая ссылка продолжает работать. Попробуйте позже.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open")],
                [InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")],
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
        f"<code>{escape(new_url)}</code>\n\n"
        "Замените подписку в приложении на новую.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [copy_btn, InlineKeyboardButton("📱 QR-код", callback_data="qr_code")],
            [InlineKeyboardButton("👤 Моя подписка", callback_data="my_paid_sub")],
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
    sep = "━" * 14

    head = ["👥 <b>Drebol VPN · Реферальная программа</b>", "",
            "🎁 <b>Приглашай друзей — получай дни к подписке!</b>", ""]
    if bonus:
        head.append(f"Тебе: <b>+{fmt_duration(bonus)}</b> за каждого друга")
    if invited_bonus:
        head.append(f"Другу: <b>+{fmt_duration(invited_bonus)}</b> за регистрацию")

    body = [f"📊 <b>Ваша статистика</b>", "",
            f"👤 Приглашено: <b>{stats['total']}</b>",
            f"🎁 Получили бонус: <b>{stats['rewarded']}</b>"]
    if stats["total_bonus"] > 0:
        body.append(f"⏱ Начислено: <b>+{fmt_duration(stats['total_bonus'])}</b>")

    link = ["🔗 <b>Ваша реферальная ссылка</b>",
            f"<code>{ref_link}</code>", "",
            "💡 <i>Поделитесь ссылкой с другом — после регистрации",
            "вы оба получите бонусные дни.</i>"]

    blocks = ["\n".join(head), "\n".join(body), "\n".join(link)]

    if ref_rows:
        invited = ["👥 <b>Приглашённые</b>", ""]
        for tg_id, rewarded, bonus_sec, created_at in ref_rows[:10]:
            u_info = await get_user_info(tg_id)
            name = escape(str(u_info[1] if u_info and u_info[1] else tg_id))
            when = _ref_date(created_at)
            mark = "✅" if rewarded else "⏳"
            gift = (f"🎁 +{fmt_duration(bonus_sec)}" if rewarded and bonus_sec
                    else "🎁 бонус после оплаты")
            invited.append(f"{mark} <b>{name}</b>")
            invited.append(f"📅 {when} · {gift}")
            invited.append("")
        blocks.append("\n".join(invited).rstrip("\n"))
        if len(ref_rows) > 10:
            blocks[-1] += f"\n\n<i>…и ещё {len(ref_rows) - 10}</i>"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    share_text = "Попробуй Drebol VPN — быстрый и безопасный VPN!"
    share_url = f"https://t.me/share/url?url={ref_link}&text={share_text}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Поделиться ссылкой", url=share_url)],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
    ])

    await query.edit_message_text(
        f"\n\n{sep}\n\n".join(blocks),
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
        "ℹ️ <b>Инфо</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❓ Как подключиться?", callback_data="how_to")],
            [InlineKeyboardButton("💰 Цены", callback_data="prices")],
            [InlineKeyboardButton("📕 О сервисе", callback_data="about")],
            [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")],
        ]),
    )


async def handle_my_devices(query, context=None):
    """Устройства клиента: показать, отключить лишнее, докупить слоты."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from paidsub.storage import get_paid_sub_by_tg_id
    from xui_api import get_client_hwids
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
        lines = ["📱 <b>Устройства</b>", "", "Без ограничений."]
    elif not r.get("ok"):
        lines = [f"📱 <b>Устройств: до {limit}</b>", "",
                 "<i>Список сейчас недоступен.</i>"]
    else:
        items = r["items"]
        lines = [f"📱 <b>Устройства: {len(items)} из {limit}</b>", ""]
        for i, d in enumerate(items[:10], 1):
            name = " · ".join(str(x) for x in (d.get("deviceOs"), d.get("deviceModel")) if x) or "устройство"
            lines.append(f"{i}. {escape(name)} · {_when_ms(d.get('lastSeen'))}")
            kb.append([InlineKeyboardButton(f"🗑 Отключить {i}",
                                            callback_data=f"dev_del:{d.get('id')}")])
        if not items:
            lines.append("Пока ни одного — подключитесь в приложении.")
        elif len(items) >= limit:
            lines += ["", "⚠️ Мест нет — отключите лишнее или добавьте."]
    if limit and price > 0 and bought < max_extra:
        kb.append([InlineKeyboardButton(f"➕ Добавить · {price} ₽",
                                        callback_data="dev_buy_menu")])
    kb.append([InlineKeyboardButton("◀️ К подписке", callback_data="my_paid_sub")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb))


def _when_ms(ms) -> str:
    from datetime import datetime
    try:
        ms = int(ms or 0)
    except (TypeError, ValueError):
        return "?"
    return datetime.fromtimestamp(ms / 1000).strftime("%d.%m %H:%M") if ms > 0 else "—"


async def handle_dev_del(query, context, hwid_id: int):
    """Клиент сам отключает своё устройство и освобождает слот."""
    from paidsub.storage import get_paid_sub_by_tg_id
    from xui_api import delete_client_hwid
    row = await get_paid_sub_by_tg_id(query.from_user.id)
    if not row:
        await query.answer("Подписка не найдена", show_alert=True)
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
        "➕ <b>Сколько добавить?</b>\n"
        "<i>До конца оплаченного срока.</i>",
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
            "Напишите в поддержку — добавим вручную.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open")],
                [InlineKeyboardButton("◀️ Назад", callback_data="my_devices")],
            ]),
        )
        return

    amount = count * price
    await query.edit_message_text("⏳ Создаю счёт...")
    result = await pg.create_payment(
        amount=amount, description=f"Устройства Drebol VPN · +{count} · {user.id}",
        tg_id=user.id, username=user.username,
    )
    if not result["ok"]:
        await query.edit_message_text(
            "❌ <b>Не удалось создать счёт</b>\n\nПопробуйте ещё раз или напишите в поддержку.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Ещё раз", callback_data="dev_buy_menu")],
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
        f"💳 <b>Счёт на {amount} ₽</b>\n"
        f"+{count} устр.\n\n"
        "Оплатите — устройства добавятся сами.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Оплатить", url=result["url"])],
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


async def _sub_summary(row, frozen: bool = False, extra: str = "") -> str:
    """Сводка подписки в три строки: что за план, до когда, ссылка."""
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
        return f"{plan} · 🔴 Закончилась\nПродлите — доступ вернётся сразу."

    if frozen:
        mark = "❄️ Заморожена"
    elif status == "renewal":
        mark = "🟡 Ждёт оплаты"
    else:
        mark = "🟢 Активна"
    until = end.strftime("%d.%m %H:%M") if end else row[6]
    return (f"{plan} · {mark}\n"
            f"⏳ {fmt_duration_precise(max(left, 0))} · до {until}\n"
            + (f"{extra}\n" if extra else "")
            + f"\n🔗 <code>{escape(row[5])}</code>")


async def _sub_facts(row) -> str:
    """Трафик и устройства — то, что человек хочет видеть сразу.

    Панель может не ответить: тогда просто не показываем строку,
    а не пугаем ошибкой на главном экране.
    """
    email, limit_hwid, total_gb = row[2], int(row[8] or 0), int(row[9] or 0)
    parts = []
    try:
        from xui_api import get_client_traffic
        t = await get_client_traffic(email)
        if t.get("success"):
            used = t.get("up", 0) + t.get("down", 0)
            parts.append(f"📊 {_fmt_bytes_user(used)}"
                         + (f" из {total_gb} ГБ" if total_gb > 0 else ""))
    except Exception:
        pass
    if limit_hwid:
        from paidsub.time_parser import _plural
        parts.append("📱 " + _plural(limit_hwid, ("устройство", "устройства", "устройств")))
    return " · ".join(parts)


async def start_screen(user, fresh: bool = False):
    """Главный экран: приветствие, состояние подписки и меню."""
    from staff import is_helper
    from adminsub.storage import get_sub_by_tg_id
    from paidsub.storage import get_paid_sub_by_tg_id
    is_admin = user.id == ADMIN_ID
    has_sub = bool(await get_sub_by_tg_id(user.id))
    row = await get_paid_sub_by_tg_id(user.id)
    paid_status = (row[11] if len(row) > 11 else "active") if row else ""

    head = f"👋 {escape(str(user.first_name or user.id))}, добро пожаловать в <b>Drebol VPN</b>"
    if row:
        enabled = True
        try:
            from xui_api import get_client_info
            info = await get_client_info(row[2])
            enabled = info.get("enabled", True) if info.get("success") else True
        except Exception:
            pass
        body = await _sub_summary(row, frozen=not enabled, extra=await _sub_facts(row))
        if fresh:
            body = ("🎉 <b>Пробный период активирован!</b>\n\n" + body
                    + "\n\n<i>Нажмите на ссылку и вставьте её в INCY.</i>")
    else:
        body = "Быстрый VPN без логов 🔒"
    text = f"{head}\n\n{body}"
    return text, main_keyboard(is_admin, has_sub, paid_status, is_helper(user.id))


async def handle_back_start(query, user):
    text, markup = await start_screen(user)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup,
                                  disable_web_page_preview=True)


