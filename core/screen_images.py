"""Картинки к экранам меню.

Админ задаёт картинку для экрана (главное меню, «Моя подписка», цены…),
а бот показывает этот экран как фото с подписью — в одном сообщении.
Где картинки нет — экран как раньше, обычным текстом.

Два ограничения Telegram, которые тут учитываются:

- Подпись у фото — максимум 1024 символа. Если текст экрана длиннее,
  картинку пропускаем и показываем текст: иначе сообщение просто
  не отправится.
- В подписи нельзя цитату: <blockquote> Telegram в подписях к фото
  не принимает (\"can't parse entities\") — а почти каждый экран
  у нас с цитатой. Поэтому для подписи теги цитаты убираем,
  содержимое оставляем: текст тот же, без рамки цитаты.
- Картинка, присланная файлом, — это документ: её file_id нельзя
  отправить как фото, у неё свой метод (send_document). Вид картинки
  храним в базе рядом с file_id и отправляем правильным методом.

Главное правило: если фото показать не вышло по любой причине —
показываем обычный текст, а не молчим. Пользователь всегда должен
получить экран, пусть и без картинки.
"""
import logging
import re

from telegram import InputMediaDocument, InputMediaPhoto

log = logging.getLogger(__name__)

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


async def get_image(key: str) -> tuple | None:
    """(file_id, kind) картинки экрана или None."""
    from core.database import get_screen_image_full
    return await get_screen_image_full(key)


def _caption_text(text: str) -> str:
    """Текст для подписи к фото: без тегов цитаты.

    <blockquote> и <blockquote expandable> в подписях не поддерживаются,
    остальное (жирный, курсив, ссылки, код) — поддерживается.
    """
    return re.sub(r"</?blockquote[^>]*>", "", text)


def _media(file_id: str, kind: str, caption: str, parse_mode: str):
    """Медиа для edit_message_media: фото или документ-картинка."""
    if kind == "document":
        return InputMediaDocument(media=file_id, caption=caption,
                                  parse_mode=parse_mode)
    return InputMediaPhoto(media=file_id, caption=caption,
                           parse_mode=parse_mode)


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


async def _send_new(target, file_id, kind, text, reply_markup, parse_mode,
                    disable_web_page_preview):
    """Новое сообщение в чат. На сообщение юзера — ответом на него;
    иначе — просто в чат (отвечать на удалённое сообщение нельзя)."""
    from telegram import Message
    if isinstance(target, Message) and not (
            target.from_user and target.from_user.is_bot):
        if file_id:
            if kind == "document":
                return await target.reply_document(
                    document=file_id, caption=text, parse_mode=parse_mode,
                    reply_markup=reply_markup)
            return await target.reply_photo(
                photo=file_id, caption=text, parse_mode=parse_mode,
                reply_markup=reply_markup)
        return await target.reply_text(
            text, parse_mode=parse_mode, reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview)
    chat = target.chat if isinstance(target, Message) else target.message.chat
    if file_id:
        if kind == "document":
            return await chat.send_document(
                document=file_id, caption=text, parse_mode=parse_mode,
                reply_markup=reply_markup)
        return await chat.send_photo(
            photo=file_id, caption=text, parse_mode=parse_mode,
            reply_markup=reply_markup)
    return await chat.send_message(
        text, parse_mode=parse_mode, reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview)


async def _edit_to_text(target, msg, text, reply_markup, parse_mode,
                        disable_web_page_preview):
    """Поменять сообщение на текст. На фото-сообщении edit_text меняет
    только подпись, поэтому его удаляем и шлём текст заново."""
    if getattr(msg, "photo", None) or getattr(msg, "document", None):
        try:
            await msg.delete()
        except Exception:
            pass
        return await _send_new(target, None, None, text, reply_markup,
                               parse_mode, disable_web_page_preview)
    try:
        return await msg.edit_text(
            text, parse_mode=parse_mode, reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview)
    except Exception:
        # Сообщение уже не редактируется — шлём заново
        return await _send_new(target, None, None, text, reply_markup,
                               parse_mode, disable_web_page_preview)


async def show_screen(target, key: str, text: str, reply_markup=None,
                      parse_mode: str = "HTML",
                      disable_web_page_preview: bool = False):
    """Показать экран меню.

    target — CallbackQuery (редактируем сообщение, на котором кнопка)
    или Message: сообщение самого бота — редактируем его, сообщение
    юзера (например, /start) — отвечаем на него.

    Если для экрана задана картинка и текст влезает в подпись —
    отправляем фото с подписью и кнопками в одном сообщении.
    Иначе — обычный текст, как раньше. Если фото показать не вышло
    (битый file_id, не та подпись) — тоже показываем текст, а ошибку
    пишем в лог: экран пользователь получает всегда.
    """
    img = await get_image(key)
    file_id, kind = img if img else (None, None)
    caption = _caption_text(text) if file_id else text
    msg = _editable_message(target)

    # Сообщение юзера — только отвечаем, ничего не трогаем
    if msg is None:
        if file_id and len(caption) <= CAPTION_LIMIT:
            try:
                return await _send_new(target, file_id, kind, caption,
                                       reply_markup, parse_mode,
                                       disable_web_page_preview)
            except Exception as e:
                log.warning("screen %s: photo failed (%s), showing text",
                            key, e)
        return await _send_new(target, None, None, text, reply_markup,
                               parse_mode, disable_web_page_preview)

    # ── Фото ────────────────────────────────────────────────────────────────
    if file_id and len(caption) <= CAPTION_LIMIT:
        try:
            await msg.edit_media(
                _media(file_id, kind, caption, parse_mode),
                reply_markup=reply_markup)
            return None
        except Exception as e:
            log.warning("screen %s: edit to photo failed (%s), retrying "
                        "as new message", key, e)
            # Не удалось превратить сообщение в фото (например, оно удалено
            # или подпись не парсится) — удаляем его и шлём фото заново,
            # а если и это не выйдет — обычный текст
            try:
                await msg.delete()
            except Exception:
                pass
            try:
                return await _send_new(target, file_id, kind, caption,
                                       reply_markup, parse_mode,
                                       disable_web_page_preview)
            except Exception as e2:
                log.warning("screen %s: photo resend failed (%s), "
                            "showing text", key, e2)
                return await _send_new(target, None, None, text, reply_markup,
                                       parse_mode, disable_web_page_preview)

    # ── Текст ───────────────────────────────────────────────────────────────
    return await _edit_to_text(target, msg, text, reply_markup, parse_mode,
                               disable_web_page_preview)
