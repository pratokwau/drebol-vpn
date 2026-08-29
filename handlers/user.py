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
    _, tg_id, email, uuid_val, sub_id, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at, status = row

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

    # --- Статус ---
    if status == "expired":
        status_emoji = "🔴"
        status_text = "отключена"
        status_detail = "Время на продление истекло"
    elif status == "renewal":
        status_emoji = "🟡"
        status_text = "ожидает оплаты"
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                expire_dt = datetime.strptime(expire, fmt)
                break
            except ValueError:
                continue
        else:
            expire_dt = datetime.now()
        remaining = expire_dt - datetime.now()
        remaining_sec = max(0, int(remaining.total_seconds()))
        from paidsub.time_parser import fmt_duration
        status_detail = f"Осталось {fmt_duration(remaining_sec)} на продление"
    elif not enabled:
        status_emoji = "❄️"
        status_text = "заморожена"
        status_detail = "Подписка приостановлена"
    else:
        status_emoji = "🟢"
        status_text = "активна"
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                expire_dt = datetime.strptime(expire, fmt)
                break
            except ValueError:
                continue
        else:
            expire_dt = datetime.now()
        days_left = (expire_dt - datetime.now()).days
        cfg_tmp = load_config()
        renew_sec = cfg_tmp.get("paid_renew_time", 86400)
        real_days = max(0, days_left - int(renew_sec / 86400))
        if real_days > 0:
            status_detail = f"Осталось {real_days} дн."
        else:
            from paidsub.time_parser import fmt_duration
            real_sec = max(0, int((expire_dt - datetime.now()).total_seconds()) - renew_sec)
            status_detail = f"Осталось {fmt_duration(real_sec)}" if real_sec > 0 else "Скоро закончится"

    # --- Трафик ---
    if total_gb > 0:
        traffic_limit = f"{total_gb} ГБ"
        used_gb = total_used / (1024 ** 3)
        bar = _progress_bar(used_gb, total_gb)
        traffic_block = (
            f"📊 <b>Трафик:</b> {used_str} / {traffic_limit}\n"
            f"<code>{bar}</code>\n"
            f"     ⬆ {up_str}  ⬇ {down_str}"
        )
    else:
        traffic_block = (
            f"📊 <b>Трафик:</b> безлимит\n"
            f"     ⬆ {up_str}  ⬇ {down_str}  ∑ {used_str}"
        )

    # --- Дата ---
    try:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                created_dt = datetime.strptime(created_at, fmt)
                break
            except ValueError:
                continue
        else:
            created_dt = None
        created_str = created_dt.strftime("%d.%m.%Y") if created_dt else created_at[:10]
    except Exception:
        created_str = str(created_at)[:10]

    text = (
        f"🔐 <b>Drebol VPN — Моя подписка</b>\n"
        f"{'━' * 28}\n\n"

        f"{status_emoji} Статус: <b>{status_text}</b>\n"
        f"     <i>{status_detail}</i>\n\n"

        f"📅 Активна до: <b>{expire}</b>\n"
        f"📆 Подключён с: {created_str}\n\n"

        f"{traffic_block}\n\n"

        f"{'━' * 28}\n"
        f"🔗 <b>Ссылка подписки:</b>\n"
        f"<code>{sub_url}</code>\n\n"
        f"<i>Нажми на ссылку чтобы скопировать → вставь в Happ или INCY</i>"
    )

    kb_rows = []
    if status in ("renewal", "expired"):
        kb_rows.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")])
    kb_rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )


async def handle_renew_sub(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user = query.from_user
    cfg = load_config()
    price = cfg.get("paid_price", 0)
    pay_url = cfg.get("paid_pay_url", "")

    uname = f"@{user.username}" if user.username else f"id{user.id}"
    hint_text = f"{user.id} - {uname}"

    kb = []
    if pay_url:
        kb.append([InlineKeyboardButton("💳 Оплатить", url=pay_url)])
    kb.append([InlineKeyboardButton("✅ Я оплатил", callback_data="i_paid")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_paid_sub")])

    await query.edit_message_text(
        "💳 <b>Продление подписки</b>\n\n"
        f"💵 Сумма: <b>{price} ₽</b>\n\n"
        "При оплате в поле <b>обратная связь</b> введите:\n"
        f"<code>{hint_text}</code>\n\n"
        "Затем нажмите кнопку <b>✅ Я оплатил</b> — "
        "администратор проверит и активирует вашу подписку.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_i_paid(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user = query.from_user

    from paidsub.storage import is_payment_pending, get_paid_sub_by_tg_id, update_paid_sub_field
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

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"confirm_payment:{user.id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment:{user.id}")],
    ])

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
        "1. Оформи пробный период или подписку\n"
        "2. Установи приложение — рекомендуем Happ\n"
        "• <a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">iOS</a>\n"
        "• <a href=\"https://play.google.com/store/apps/details?id=com.happproxy\">Android</a>\n"
        "• <a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe\">Windows</a>\n"
        "• <a href=\"https://apps.apple.com/us/app/happ-proxy-utility/id6504287215\">MacOS</a>\n"
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
