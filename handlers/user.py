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


async def handle_my_paid_sub(query):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user_id = query.from_user.id
    from paidsub.storage import get_paid_sub_by_tg_id
    row = await get_paid_sub_by_tg_id(user_id)
    if not row:
        await query.edit_message_text(
            "👤 <b>Моя подписка</b>\n\nУ вас пока нет активной подписки.",
            parse_mode="HTML",
            reply_markup=back_main(),
        )
        return
    _, tg_id, email, uuid_val, sub_id, sub_url, expire, limit_ip, limit_hwid, total_gb, created_at, status = row
    traffic = f"{total_gb} ГБ" if total_gb > 0 else "безлимит"

    from xui_api import get_client_info
    info = await get_client_info(email)
    if info.get("success"):
        enabled = info.get("enabled", True)
    else:
        enabled = True

    if status == "expired":
        status_line = "🔴 Статус: <b>отключена</b>"
        status_note = "\n\n⚠️ Время на продление истекло. Продлите подписку!"
    elif status == "renewal":
        status_line = "🟡 Статус: <b>ожидает оплаты</b>"
        from datetime import datetime, timedelta
        cfg = load_config()
        renew_sec = cfg.get("paid_renew_time", 86400)
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
        status_note = f"\n\n⏳ Осталось <b>{fmt_duration(remaining_sec)}</b> на продление."
    elif not enabled:
        status_line = "🔴 Статус: <b>заморожена</b>"
        status_note = ""
    else:
        status_line = "🟢 Статус: <b>активна</b>"
        status_note = ""

    kb_rows = []
    if status in ("renewal", "expired"):
        kb_rows.append([InlineKeyboardButton("💳 Продлить подписку", callback_data="renew_sub")])
    kb_rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")])

    await query.edit_message_text(
        "👤 <b>Моя подписка</b>\n\n"
        f"{status_line}\n"
        f"📅 Действует до: <b>{expire}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>"
        f"{status_note}\n\n"
        f"🔗 <b>Ссылка подписки:</b>\n<code>{sub_url}</code>\n\n"
        "Скопируй ссылку и вставь в приложение (Happ, v2rayNG и др.)",
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
        "После оплаты в поле <b>обратная связь</b> введите:\n"
        f"<code>{hint_text}</code>\n\n"
        "Затем нажмите кнопку <b>✅ Я оплатил</b> — "
        "администратор проверит и активирует вашу подписку.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_i_paid(query, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user = query.from_user
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
    from paidsub.storage import get_paid_sub_by_tg_id
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
