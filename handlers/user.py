from config import ADMIN_ID, load_config
from keyboards import main_keyboard, back_main


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
        "Скопируй ссылку и вставь в приложение (Happ, v2rayNG и др.)",
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
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import datetime, timedelta
    user_id = query.from_user.id
    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub_by_tg_id(user_id)
    if not row:
        await query.edit_message_text(
            "🔐 <b>Drebol VPN</b>\n\n"
            "У вас пока нет подписки.\n"
            "Нажмите <b>👤 Моя подписка</b> чтобы оформить пробный период.",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return
    _, tg_id, email, uuid_val, sub_id, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at, status, times_renewed = row[:13]

    from paidsub.time_parser import fmt_duration
    from xui_api import get_client_info, get_client_traffic
    info = await get_client_info(email)
    enabled = info.get("enabled", True) if info.get("success") else True

    t = await get_client_traffic(email)
    if t.get("success"):
        up = t.get("up", 0)
        down = t.get("down", 0)
        total_used = up + down
        used_str = _fmt_bytes_user(total_used)
        up_str = _fmt_bytes_user(up)
        down_str = _fmt_bytes_user(down)
    else:
        total_used = 0
        used_str = "0 КБ"
        up_str = "0 КБ"
        down_str = "0 КБ"

    def _parse_dt(s):
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return datetime.now()

    expire_dt = _parse_dt(expire)
    cfg_tmp = load_config()
    renew_sec = cfg_tmp.get("paid_renew_time", 86400)

    # --- Статус ---
    if status == "expired":
        status_emoji = "🔴"
        status_text = "отключена"
        status_detail = "Время на продление истекло"
    elif status == "renewal":
        status_emoji = "🟡"
        status_text = "ожидает оплаты"
        remaining_sec = max(0, int((expire_dt - datetime.now()).total_seconds()))
        status_detail = f"Осталось {fmt_duration(remaining_sec)} на продление"
    elif not enabled:
        status_emoji = "❄️"
        status_text = "заморожена"
        status_detail = "Подписка приостановлена"
    else:
        status_emoji = "🟢"
        status_text = "активна"
        real_sec = max(0, int((expire_dt - datetime.now()).total_seconds()) - renew_sec)
        status_detail = f"Осталось {fmt_duration(real_sec)}" if real_sec > 0 else "Скоро закончится"

    # --- Трафик ---
    if total_gb > 0:
        traffic_limit = f"{total_gb} ГБ"
        used_gb = total_used / (1024 ** 3)
        bar = _progress_bar(used_gb, total_gb)
        traffic_block = (
            f"📊 <b>Трафик</b>\n"
            f"     {used_str} из {traffic_limit}\n"
            f"     <code>{bar}</code>\n"
            f"     ⬆️ {up_str}   ⬇️ {down_str}"
        )
    else:
        traffic_block = (
            f"📊 <b>Трафик</b>\n"
            f"     ♾ Безлимит  —  использовано {used_str}\n"
            f"     ⬆️ {up_str}   ⬇️ {down_str}"
        )

    # --- Дата подключения ---
    try:
        created_dt = _parse_dt(created_at)
        created_str = created_dt.strftime("%d.%m.%Y")
    except Exception:
        created_str = str(created_at)[:10]

    # --- Тип подписки ---
    if status == "expired":
        sub_type = "🚫 Требуется продление"
    elif status == "renewal":
        sub_type = "⏳ Ожидает оплаты"
    elif not enabled:
        sub_type = "❄️ Заморожена"
    elif times_renewed > 0:
        sub_type = "⭐️ Премиум"
    else:
        sub_type = "🆓 Пробный период"

    # --- Дата окончания без времени, если полночь ---
    expire_display = expire_dt.strftime("%d.%m.%Y в %H:%M")

    # --- Реферальный блок ---
    referral_block = ""
    from paidsub.storage import get_referral_stats
    ref_stats = await get_referral_stats(user_id)
    bonus_cfg = cfg_tmp.get("referral_bonus")
    if ref_stats["total"] > 0:
        earned = f" · +{fmt_duration(ref_stats['total_bonus'])}" if ref_stats["total_bonus"] > 0 else ""
        referral_block = (
            f"\n👥 <b>Приглашено друзей:</b> {ref_stats['total']}{earned}\n"
        )
    elif bonus_cfg:
        referral_block = (
            f"\n🎁 <b>Приглашай друзей</b> — получай +{fmt_duration(bonus_cfg)} за каждого!\n"
        )

    text = (
        f"🔐 <b>Drebol VPN — Моя подписка</b>\n"
        f"{'━' * 24}\n\n"

        f"📋 Тип: <b>{sub_type}</b>\n"
        f"{status_emoji} Статус: <b>{status_text}</b>\n"
        f"     <i>{status_detail}</i>\n\n"

        f"📅 Активна до: <b>{expire_display}</b>\n"
        f"📆 Подключён с: {created_str}\n\n"

        f"{traffic_block}\n"
        f"{referral_block}\n"

        f"{'━' * 24}\n"
        f"🔗 <b>Ваша ссылка подписки:</b>\n"
        f"<code>{sub_url}</code>\n\n"
        f"<i>Нажмите на ссылку, чтобы скопировать, и вставьте её в приложение Happ или INCY.</i>"
    )

    kb_rows = []
    if status in ("renewal", "expired"):
        kb_rows.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")])
    kb_rows.append([
        InlineKeyboardButton("👥 Пригласить друга", callback_data="referral"),
        InlineKeyboardButton("❓ Как подключиться", callback_data="how_to"),
    ])
    kb_rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows),
        disable_web_page_preview=True,
    )


async def handle_renew_sub(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user = query.from_user
    cfg = load_config()

    from paidsub.storage import get_paid_sub_by_tg_id, get_paid_sub
    row = await get_paid_sub_by_tg_id(user.id)
    if row:
        full = await get_paid_sub(row[0])
        ind_price = full[16] if full and full[16] else None
        ind_pay_url = full[17] if full and full[17] else None
    else:
        ind_price = None
        ind_pay_url = None
    price = ind_price if ind_price else cfg.get("paid_price", 0)
    pay_url = ind_pay_url if ind_pay_url else cfg.get("paid_pay_url", "")
    ind_pay_period = full[14] if full and full[14] else None
    pay_seconds = ind_pay_period if ind_pay_period else cfg.get("paid_pay_period", 2592000)
    from paidsub.time_parser import fmt_duration
    period_str = fmt_duration(pay_seconds)

    uname = f"@{user.username}" if user.username else f"id{user.id}"
    hint_text = f"{user.id} - {uname}"

    kb = []
    if pay_url:
        kb.append([InlineKeyboardButton("💳 Оплатить", url=pay_url)])
    kb.append([InlineKeyboardButton("✅ Я оплатил", callback_data="i_paid")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")])

    await query.edit_message_text(
        "💳 <b>Продление подписки</b>\n\n"
        f"💵 Сумма: <b>{price} ₽</b>\n"
        f"⏱ Срок: <b>{period_str}</b>\n\n"
        "При оплате в поле <b>обратная связь</b> введите:\n"
        f"<code>{hint_text}</code>\n\n"
        "Затем нажмите кнопку <b>✅ Я оплатил</b> — "
        "администратор проверит и активирует вашу подписку.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_i_paid(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import datetime
    user = query.from_user

    from paidsub.storage import is_payment_pending, get_paid_sub_by_tg_id, update_paid_sub_field, get_muted_until
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
    price = cfg.get("paid_price", 0)

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
            f'👤 <a href="tg://user?id={user.id}">{user.first_name}</a> ({uname})\n'
            f"🆔 TG ID: <code>{user.id}</code>"
            f"{sub_info}\n"
            f"💵 Сумма: <b>{price} ₽</b>\n\n"
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
        "<b>❓ Как подключиться?</b>\n\n"
        "<b>Основной способ ⬇️</b>\n"
        "1. Оформи пробный период или подписку\n"
        "2. Установи приложение — рекомендуем Happ\n"
        "• <a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">iOS</a>\n"
        "• <a href=\"https://play.google.com/store/apps/details?id=com.happproxy\">Android</a>\n"
        "• <a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe\">Windows</a>\n"
        "• <a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">MacOS</a>\n"
        "3. Скопируй ссылку подписки и вставь её в приложение\n"
        "4. Выбери сервер и подключайся\n\n"
        "<b>Альтернативный способ ⬇️</b>\n"
        "1. Оформи пробный период или подписку\n"
        "2. Установи приложение — INCY\n"
        "• <a href=\"https://apps.apple.com/ru/app/incy/id6756943388\">iOS</a>\n"
        "• <a href=\"https://play.google.com/store/apps/details?id=llc.itdev.incy\">Android</a>\n"
        "• <a href=\"https://github.com/INCY-DEV/incy-platforms/releases/latest/download/incy-windows-setup.exe\">Windows</a>\n"
        "• <a href=\"https://apps.apple.com/ru/app/incy/id6756943388\">MacOS</a>\n"
        "3. Скопируй ссылку подписки и вставь её в приложение\n"
        "4. Выбери сервер и подключайся",
        parse_mode="HTML",
        reply_markup=back_main(),
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

    if privacy_url and terms_url:
        docs = (
            f'<a href="{privacy_url}">политика конфиденциальности</a>'
            f' и <a href="{terms_url}">пользовательское соглашение</a>'
        )
    elif privacy_url:
        docs = f'<a href="{privacy_url}">политика конфиденциальности</a> и пользовательское соглашение'
    elif terms_url:
        docs = f'политика конфиденциальности и <a href="{terms_url}">пользовательское соглашение</a>'
    else:
        docs = "политика конфиденциальности и пользовательское соглашение"

    await query.edit_message_text(
        "<b>ℹ️ О сервисе</b>\n\n"
        "<b>🖥️ Любая платформа</b> — iOS, MacOS, Android, Windows\n\n"
        "<b>🛡️ Без логов</b> — не храним данные об активности пользователей\n\n"
        "<b>💳 Прозрачные платежи</b> — без скрытых списаний и автопродления\n\n"
        f"<b>📕 Документы</b> — {docs}",
        parse_mode="HTML",
        reply_markup=back_main(),
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

    lines = [
        "👥 <b>Реферальная программа</b>\n",
        "Приглашай друзей и получай бонусные дни к подписке!\n",
    ]

    cfg = load_config()
    bonus = cfg.get("referral_bonus")
    if bonus:
        lines.append(f"🎁 Бонус за каждого друга: <b>{fmt_duration(bonus)}</b>\n")

    lines.append(f"👤 Приглашено: <b>{stats['total']}</b>")
    lines.append(f"✅ С бонусом: <b>{stats['rewarded']}</b>")
    if stats['total_bonus'] > 0:
        lines.append(f"⏱ Всего начислено: <b>{fmt_duration(stats['total_bonus'])}</b>")

    if ref_rows:
        lines.append("\n<b>Приглашённые:</b>")
        for tg_id, rewarded, bonus_sec, created_at in ref_rows[:10]:
            u_info = await get_user_info(tg_id)
            name = u_info[1] if u_info else str(tg_id)
            status = "✅" if rewarded else "⏳"
            bonus_txt = f" (+{fmt_duration(bonus_sec)})" if rewarded and bonus_sec else ""
            ts = created_at[:10] if created_at else ""
            lines.append(f"{status} {name} · {ts}{bonus_txt}")

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    share_text = "Попробуй Drebol VPN — быстрый и безопасный VPN!"
    share_url = f"https://t.me/share/url?url={ref_link}&text={share_text}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Поделиться ссылкой", url=share_url)],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
    ])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


async def handle_back_start(query, user):
    is_admin = user.id == ADMIN_ID
    from adminsub.storage import get_sub_by_tg_id
    from paidsub.storage import get_paid_sub_status
    has_sub = bool(await get_sub_by_tg_id(user.id))
    paid_status = await get_paid_sub_status(user.id)
    await query.edit_message_text(
        f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
        "🔒 Быстрый и безопасный VPN\n"
        "⚡️ Стабильное подключение\n"
        "🌍 Доступ к популярным сервисам\n\n"
        "Выберите нужный раздел ниже 👇",
        parse_mode="HTML",
        reply_markup=main_keyboard(is_admin, has_sub, paid_status),
    )
