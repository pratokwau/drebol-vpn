from html import escape

from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID
from database import upsert_user
from subscription import is_subscribed, subscribe_keyboard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("state", None)
    user = update.effective_user

    from database import get_user_info
    is_new = not await get_user_info(user.id)
    await upsert_user(user.id, user.first_name, user.username)
    if is_new:
        from database import log_activity
        await log_activity(user.id, "ev:registered",
                           context.args[0] if context.args else None)
        from log_channel import send_log
        # имя человек задаёт сам — без экранирования запись в лог-канал пропадёт
        uname = escape(f"@{user.username}" if user.username else f"id{user.id}")
        await send_log(context.bot,
            f"👤 Новый пользователь: {escape(str(user.first_name or user.id))} "
            f"({uname}) · <code>{user.id}</code>"
        )

    # Реферальная ссылка: /start ref_123456
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0][4:])
            if referrer_id != user.id:
                from paidsub.storage import save_referral
                await save_referral(user.id, referrer_id)
        except (ValueError, IndexError):
            pass

    # Техработы: пользователь видит сообщение, админ работает как обычно.
    # Регистрацию и реферала выше сохраняем, иначе пришедшие во время работ потеряются.
    # Помощник проходит, чтобы попасть в панель поддержки.
    from staff import is_helper
    helper = is_helper(user.id)
    if user.id != ADMIN_ID and not helper:
        import maintenance as mnt
        if mnt.is_maintenance():
            await mnt.show_maintenance(message=update.message)
            return

    from database import is_banned
    if user.id != ADMIN_ID and await is_banned(user.id):
        await update.message.reply_text("🚫 Ваш аккаунт заблокирован. Обратитесь к администратору.")
        return

    # Чёрный список: вместо меню — причина и кнопка поддержки
    if user.id != ADMIN_ID and not helper:
        from blacklist import entry as bl_entry, show_blocked
        ble = await bl_entry(user.id)
        if ble:
            await show_blocked(ble, message=update.message)
            return

    if not helper and not await is_subscribed(context.bot, user.id):
        await update.message.reply_text(
            f"👋 {escape(str(user.first_name or user.id))}, добро пожаловать в <b>Drebol VPN</b>\n\n"
            "🔒 Быстрый и безопасный VPN\n"
            "⚡️ Стабильное подключение\n"
            "🌍 Доступ к популярным сервисам\n\n"
            "🔒 Для дальнейшего пользования ботом подпишитесь на наш канал.\n\n"
            "Там новости сервиса, новые серверы и предупреждения о техработах.\n"
            "После подписки нажмите кнопку <b>✅ Я подписался</b>.",
            parse_mode="HTML",
            reply_markup=subscribe_keyboard(),
        )
        return

    # Канал пройден — пробный период выдаём сразу, без лишних нажатий.
    # Пока панель создаёт клиента, человек видит «⏳», а не тишину
    from handlers.user import ensure_trial, start_screen
    waiting = []

    async def _show_progress():
        waiting.append(await update.message.reply_text("⏳ Готовлю ваш доступ…"))

    fresh = await ensure_trial(user, context, on_start=_show_progress)
    text, markup = await start_screen(user, fresh=fresh)
    if waiting:
        await waiting[0].edit_text(text, parse_mode="HTML", reply_markup=markup,
                                   disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup,
                                        disable_web_page_preview=True)
