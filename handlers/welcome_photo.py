"""Картинки 16:9 для меню бота.

Админ загружает картинки сам в админке (меню «Канал» → «Картинка
приветствия»); хранится Telegram file_id в config.json, переживает
рестарты. У каждого меню — своя картинка:

    start     — главный экран (/start)
    my_sub    — Моя подписка
    prices    — Цены
    referral  — Пригласить друга
    info      — Инфо
    howto     — Как подключиться

Настройка: menu_photos: {key: {file_id, enabled}}. Для ключа start
дополнительно действует fallback на старые ключи welcome_photo_file_id
/ welcome_photo_enabled — картинка главного экрана, загруженная до
появления меню, продолжает работать.

Отправка — тем же паттерном, что рассылка (handlers/broadcast.py):
текст влезает в подпись (<=1024) — фото+подпись одним сообщением,
не влезает — фото отдельным сообщением, потом текст. Если картинки
нет или она выключена — обычный текст, поведение как раньше.

Показ экрана меню — show_menu_screen(query, key, ...): если у сообщения
уже та же картинка — правим подпись; если картинка другая или сообщение
текстовое, а у меню картинка есть — шлём экран заново с картинкой и
убираем старое сообщение; если у меню картинки нет, а сообщение — фото,
— шлём текст и убираем фото; иначе — обычная правка текста.
"""
import math

from config import load_config, save_config
from handlers.broadcast import CAPTION_LIMIT

KEY_FILE_ID = "welcome_photo_file_id"
KEY_ENABLED = "welcome_photo_enabled"
KEY_MENU_PHOTOS = "menu_photos"

MENU_TITLES = {
    "start": "Главный экран",
    "my_sub": "Моя подписка",
    "prices": "Цены",
    "referral": "Пригласить друга",
    "info": "Инфо",
    "howto": "Как подключиться",
}
MENU_KEYS = tuple(MENU_TITLES)

RATIO_W, RATIO_H = 16, 9
# допуск на соотношение: Telegram может чуть пережимать стороны,
# а 1366x768 (1.7786) — тоже честные 16:9
RATIO_TOL = 0.02


def get_menu_photo(key: str) -> tuple[str | None, bool]:
    """(file_id, enabled) картинки меню key из config.json."""
    cfg = load_config()
    photos = cfg.get(KEY_MENU_PHOTOS) or {}
    if key == "start" and key not in photos:
        # картинки главного экрана, загруженной до появления меню
        file_id = cfg.get(KEY_FILE_ID) or None
        enabled = bool(cfg.get(KEY_ENABLED, False))
        return file_id, enabled
    entry = photos.get(key) or {}
    return entry.get("file_id") or None, bool(entry.get("enabled", False))


def set_menu_photo(key: str, file_id=None, enabled=None) -> dict:
    """Сохранить картинку меню; file_id/enabled=None — не менять."""
    cfg = load_config()
    photos = cfg.get(KEY_MENU_PHOTOS) or {}
    entry = dict(photos.get(key) or {})
    if file_id is not None:
        entry["file_id"] = file_id
    if enabled is not None:
        entry["enabled"] = bool(enabled)
    photos[key] = entry
    cfg[KEY_MENU_PHOTOS] = photos
    if key == "start":
        # старые ключи — в ногу, чтобы ничего не читало их вразнобой
        if file_id is not None:
            cfg[KEY_FILE_ID] = file_id
        if enabled is not None:
            cfg[KEY_ENABLED] = bool(enabled)
    save_config(cfg)
    return entry


def clear_menu_photo(key: str) -> None:
    """Убрать картинку меню: file_id стёрт, выключено.

    Запись оставляем пустой, а не удаляем: иначе у start сработал бы
    fallback на старые ключи и удалённая картинка «воскресла» бы.
    """
    cfg = load_config()
    photos = cfg.get(KEY_MENU_PHOTOS) or {}
    photos[key] = {"file_id": None, "enabled": False}
    cfg[KEY_MENU_PHOTOS] = photos
    if key == "start":
        cfg[KEY_FILE_ID] = None
        cfg[KEY_ENABLED] = False
    save_config(cfg)


def get_welcome_photo() -> tuple[str | None, bool]:
    """(file_id, enabled) картинки приветствия — то же, что меню start."""
    return get_menu_photo("start")


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


async def _deliver(send_photo, send_text, text, reply_markup, parse_mode,
                   kwargs, file_id=None, enabled=False):
    """Общая логика: фото+подпись, фото отдельно + текст, или просто текст.

    send_photo/send_text — awaitable-вызовы с сигнатурой send_photo(photo=...,
    caption=...), send_text(text=...). Ошибка фото в режиме «подпись» —
    откат к обычному тексту, чтобы юзер не остался без экрана.
    """
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


async def reply_with_menu_photo(message, key, text, reply_markup=None,
                                parse_mode="HTML", **kwargs):
    """Ответ на сообщение юзера (сохраняет reply-нитку /start)."""
    file_id, enabled = get_menu_photo(key)
    return await _deliver(message.reply_photo, message.reply_text,
                          text, reply_markup, parse_mode, kwargs,
                          file_id, enabled)


async def send_with_menu_photo(bot, chat_id, key, text, reply_markup=None,
                               parse_mode="HTML", **kwargs):
    """Отправка в чат по chat_id (когда отвечать не на что — например,
    после удаления старого сообщения в check_sub)."""
    file_id, enabled = get_menu_photo(key)

    async def _send_text(**kw):
        return await bot.send_message(chat_id=chat_id, **kw)

    async def _send_photo(**kw):
        return await bot.send_photo(chat_id=chat_id, **kw)

    return await _deliver(_send_photo, _send_text,
                          text, reply_markup, parse_mode, kwargs,
                          file_id, enabled)


async def reply_with_welcome_photo(message, text, reply_markup=None,
                                   parse_mode="HTML", **kwargs):
    """Ответ с картинкой главного экрана (ключ start)."""
    return await reply_with_menu_photo(message, "start", text,
                                       reply_markup, parse_mode, **kwargs)


async def send_with_welcome_photo(bot, chat_id, text, reply_markup=None,
                                  parse_mode="HTML", **kwargs):
    """Отправка с картинкой главного экрана (ключ start)."""
    return await send_with_menu_photo(bot, chat_id, "start", text,
                                      reply_markup, parse_mode, **kwargs)


async def show_menu_screen(query, key, text, reply_markup=None,
                           parse_mode="HTML", **kwargs):
    """Показать экран меню key на месте текущего сообщения query.

    Картинка меню — та же, что у сообщения: правим подпись.
    Картинка другая (или сообщение текстовое, а у меню картинка есть):
    шлём экран заново с картинкой и убираем старое сообщение.
    У меню картинки нет, а сообщение — фото: шлём текст и убираем фото.
    Картинки нет и сообщение текстовое: обычная правка текста.
    Падения при удалении старого сообщения молча игнорируем.
    """
    file_id, enabled = get_menu_photo(key)
    msg = query.message
    if msg is None:
        return await query.edit_message_text(
            text, parse_mode=parse_mode, reply_markup=reply_markup, **kwargs)
    photo = getattr(msg, "photo", None)
    current = photo[-1].file_id if photo else None
    if enabled and file_id and current == file_id \
            and len(text) <= CAPTION_LIMIT:
        caption_kwargs = {k: v for k, v in kwargs.items()
                          if k not in ("disable_web_page_preview",
                                       "link_preview_options")}
        return await query.edit_message_caption(
            caption=text, parse_mode=parse_mode, reply_markup=reply_markup,
            **caption_kwargs)
    if enabled and file_id:
        await _deliver(msg.reply_photo, msg.reply_text,
                       text, reply_markup, parse_mode, kwargs,
                       file_id, enabled)
    elif current is not None:
        await msg.reply_text(text=text, parse_mode=parse_mode,
                             reply_markup=reply_markup, **kwargs)
    else:
        return await query.edit_message_text(
            text, parse_mode=parse_mode, reply_markup=reply_markup, **kwargs)
    try:
        await msg.delete()
    except Exception:
        pass
    return None
