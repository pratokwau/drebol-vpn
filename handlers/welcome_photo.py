"""Картинка приветствия: фото 16:9 к /start и главным экранам подписки.

Админ загружает картинку сам в админке (меню «Канал» → «Картинка
приветствия»); хранится Telegram file_id в config.json, переживает
рестарты. Настройка: welcome_photo_file_id + welcome_photo_enabled.

Отправка — тем же паттерном, что рассылка (handlers/broadcast.py):
текст влезает в подпись (<=1024) — фото+подпись одним сообщением,
не влезает — фото отдельным сообщением, потом текст. Если картинки
нет или она выключена — обычный текст, поведение как раньше.
"""
import math

from config import load_config
from handlers.broadcast import CAPTION_LIMIT

KEY_FILE_ID = "welcome_photo_file_id"
KEY_ENABLED = "welcome_photo_enabled"

RATIO_W, RATIO_H = 16, 9
# допуск на соотношение: Telegram может чуть пережимать стороны,
# а 1366x768 (1.7786) — тоже честные 16:9
RATIO_TOL = 0.02


def get_welcome_photo() -> tuple[str | None, bool]:
    """(file_id, enabled) картинки приветствия из config.json."""
    cfg = load_config()
    file_id = cfg.get(KEY_FILE_ID) or None
    enabled = bool(cfg.get(KEY_ENABLED, False))
    return file_id, enabled


def is_16_9(width: int, height: int) -> bool:
    """Проверка соотношения по размерам из Telegram PhotoSize."""
    if not width or not height:
        return False
    return abs(width / height - RATIO_W / RATIO_H) <= RATIO_TOL


def ratio_label(width: int, height: int) -> str:
    """Человекочитаемое соотношение, например 16:9 или 3:2."""
    if not width or not height:
        return "?"
    g = math.gcd(width, height)
    return f"{width // g}:{height // g}"


async def _deliver(send_photo, send_text, text, reply_markup, parse_mode, kwargs):
    """Общая логика: фото+подпись, фото отдельно + текст, или просто текст.

    send_photo/send_text — awaitable-вызовы с сигнатурой send_photo(photo=...,
    caption=...), send_text(text=...). Ошибка фото в режиме «подпись» —
    откат к обычному тексту, чтобы юзер не остался без экрана.
    """
    file_id, enabled = get_welcome_photo()
    if not (enabled and file_id):
        return await send_text(text=text, parse_mode=parse_mode,
                               reply_markup=reply_markup, **kwargs)
    if len(text) <= CAPTION_LIMIT:
        try:
            photo_kwargs = {k: v for k, v in kwargs.items()
                            if k != "disable_web_page_preview"}
            return await send_photo(photo=file_id, caption=text,
                                    parse_mode=parse_mode,
                                    reply_markup=reply_markup, **photo_kwargs)
        except Exception:
            return await send_text(text=text, parse_mode=parse_mode,
                                   reply_markup=reply_markup, **kwargs)
    try:
        await send_photo(photo=file_id)
    except Exception:
        pass  # фото не ушло — текст всё равно покажем
    return await send_text(text=text, parse_mode=parse_mode,
                           reply_markup=reply_markup, **kwargs)


async def reply_with_welcome_photo(message, text, reply_markup=None,
                                   parse_mode="HTML", **kwargs):
    """Ответ на сообщение юзера (сохраняет reply-нитку /start)."""
    return await _deliver(message.reply_photo, message.reply_text,
                          text, reply_markup, parse_mode, kwargs)


async def send_with_welcome_photo(bot, chat_id, text, reply_markup=None,
                                  parse_mode="HTML", **kwargs):
    """Отправка в чат по chat_id (когда отвечать не на что — например,
    после удаления старого сообщения в check_sub)."""

    async def _send_text(**kw):
        return await bot.send_message(chat_id=chat_id, **kw)

    async def _send_photo(**kw):
        return await bot.send_photo(chat_id=chat_id, **kw)

    return await _deliver(_send_photo, _send_text,
                          text, reply_markup, parse_mode, kwargs)
