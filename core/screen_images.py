"""Картинки к экранам меню.

Админ задаёт картинку для экрана (главное меню, «Моя подписка», цены…),
а бот показывает этот экран как фото с подписью — в одном сообщении.
Где картинки нет — экран как раньше, обычным текстом.

Подпись у фото в Telegram — максимум 1024 символа. Если текст экрана
длиннее, картинку пропускаем и показываем текст: иначе сообщение
просто не отправится.
"""
from telegram import InputMediaPhoto

# Подпись в Telegram — не больше 1024 символов
CAPTION_LIMIT = 1024

# Экраны, к которым можно прикрепить картинку: ключ → подпись в админке.
SCREENS = {
    "main": "🏠 Главное меню",
    "my_paid_sub": "⚙️ Моя подписка",
    "my_lte": "📡 LTE-интернет",
    "renew_sub": "💳 Продление подписки",
    "tariff_pick": "💳 Карточка тарифа",
    "prices": "💰 Цены",
    "referral": "🎁 Пригласить друга",
    "info": "ℹ️ Информация",
    "my_devices": "🖥 Мои устройства",
    "my_sub": "📋 Админская подписка",
    "how_to": "❓ Как подключиться",
    "about": "📕 О сервисе",
    "gift_pick": "🎁 Подарок подписки",
    "enter_promo": "🎟 Промокод",
    "support": "🛟 Поддержка",
}


async def get_image(key: str) -> str | None:
    """file_id картинки экрана или None."""
    from core.database import get_screen_image
    return await get_screen_image(key)


def _editable_message(target):
    """Сообщение бота, которое можно редактировать, или None.

    CallbackQuery — сообщение, на котором кнопка (всегда ботово).
    Message от бота (например, «⏳ Готовлю ваш доступ…») — оно же.
    Message юзера (например, /start) — редактировать нельзя, на него
    только отвечаем: возвращаем None.
    """
    from telegram import Message
    if isinstance(target, Message):
        if target.from_user and target.from_user.is_bot:
            return target
        return None
    return target.message


async def _send_new(target, file_id, text, reply_markup, parse_mode,
                    disable_web_page_preview):
    """Новое сообщение в чат. На сообщение юзера — ответом на него;
    иначе — просто в чат (отвечать на удалённое сообщение нельзя)."""
    from telegram import Message
    if isinstance(target, Message) and not (
            target.from_user and target.from_user.is_bot):
        if file_id:
            return await target.reply_photo(
                photo=file_id, caption=text, parse_mode=parse_mode,
                reply_markup=reply_markup)
        return await target.reply_text(
            text, parse_mode=parse_mode, reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview)
    chat = target.chat if isinstance(target, Message) else target.message.chat
    if file_id:
        return await chat.send_photo(
            photo=file_id, caption=text, parse_mode=parse_mode,
            reply_markup=reply_markup)
    return await chat.send_message(
        text, parse_mode=parse_mode, reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview)


async def show_screen(target, key: str, text: str, reply_markup=None,
                      parse_mode: str = "HTML",
                      disable_web_page_preview: bool = False):
    """Показать экран меню.

    target — CallbackQuery (редактируем сообщение, на котором кнопка)
    или Message: сообщение самого бота — редактируем его, сообщение
    юзера (например, /start) — отвечаем на него.

    Если для экрана задана картинка и текст влезает в подпись —
    отправляем фото с подписью и кнопками в одном сообщении.
    Иначе — обычный текст, как раньше.
    """
    file_id = await get_image(key)
    msg = _editable_message(target)

    # Сообщение юзера — только отвечаем, ничего не трогаем
    if msg is None:
        return await _send_new(target, file_id if len(text) <= CAPTION_LIMIT else None,
                               text, reply_markup, parse_mode,
                               disable_web_page_preview)

    # ── Фото ────────────────────────────────────────────────────────────────
    if file_id and len(text) <= CAPTION_LIMIT:
        try:
            await msg.edit_media(
                InputMediaPhoto(media=file_id, caption=text,
                                parse_mode=parse_mode),
                reply_markup=reply_markup)
            return None
        except Exception:
            # Сообщение не превращается в фото (например, удалено) —
            # удаляем его и шлём фото заново
            try:
                await msg.delete()
            except Exception:
                pass
            return await _send_new(target, file_id, text, reply_markup,
                                   parse_mode, disable_web_page_preview)

    # ── Текст ───────────────────────────────────────────────────────────────
    # На фото-сообщении edit_text меняет только подпись, поэтому его
    # удаляем и шлём текст заново. На текстовом — просто редактируем.
    if getattr(msg, "photo", None):
        try:
            await msg.delete()
        except Exception:
            pass
        return await _send_new(target, None, text, reply_markup, parse_mode,
                               disable_web_page_preview)
    try:
        return await msg.edit_text(
            text, parse_mode=parse_mode, reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview)
    except Exception:
        # Сообщение уже не редактируется — шлём заново
        return await _send_new(target, None, text, reply_markup, parse_mode,
                               disable_web_page_preview)
