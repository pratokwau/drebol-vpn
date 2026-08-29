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
    await query.edit_message_text(
        "📋 <b>Админская подписка</b>\n\n"
        f"📅 Действует до: <b>{expire}</b>\n"
        f"📶 Трафик: <b>{traffic}</b>\n\n"
        f"🔗 <b>Ссылка подписки:</b>\n<code>{sub_url}</code>\n\n"
        "Скопируй ссылку и вставь в приложение (Happ, v2rayNG и др.)",
        parse_mode="HTML",
        reply_markup=back_main(),
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
    has_sub = bool(await get_sub_by_tg_id(user.id))
    await query.edit_message_text(
        f"👋 {user.first_name}, добро пожаловать в <b>Drebol VPN</b>\n\n"
        "🔒 Быстрый и безопасный VPN\n"
        "⚡️ Стабильное подключение\n"
        "🌍 Доступ к популярным сервисами\n\n"
        "Выберите нужный раздел ниже 👇",
        parse_mode="HTML",
        reply_markup=main_keyboard(is_admin, has_sub),
    )
