"""Поддержка со стороны клиента.

Тикет-системы в основном боте больше нет (решение Mark, 2026-11-13):
обращения живут в отдельном боте поддержки и группе с темами
(support_bot.py). Здесь — только кнопка «🛟 Поддержка» и экран
со ссылкой на бота поддержки.

Юзернейм бота поддержки — в config.json (support_bot_username).
Если не задан — экран честно говорит, что поддержка пока не настроена.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def support_bot_username() -> str:
    """Юзернейм бота поддержки без «@». Пусто — не задан."""
    from config import load_config
    raw = str(load_config().get("support_bot_username") or "").strip()
    for prefix in ("https://", "http://", "t.me/", "telegram.me/", "@"):
        raw = raw.replace(prefix, "")
    return raw.strip("/ ").split("?")[0].split()[0] if raw.strip() else ""


def support_bot_url() -> str:
    name = support_bot_username()
    return f"https://t.me/{name}" if name else ""


def support_button(text: str = "🛟 Поддержка", force: bool = False):
    """Кнопка поддержки: открывает экран со ссылкой на бота поддержки.

    force — показать даже если функция выключена в техработах (для админа).
    None означает, что кнопки быть не должно.
    """
    import core.maintenance as mnt
    if not force and not mnt.feature_enabled("support"):
        return None
    return InlineKeyboardButton(text, callback_data="support_open")


def support_row(text: str = "🛟 Поддержка") -> list:
    """Готовый ряд кнопок — пустой, если поддержка выключена."""
    btn = support_button(text)
    return [btn] if btn else []


async def open_support(query, user_id: int | None = None, page: int | None = None):
    """Экран поддержки: ссылка на отдельного бота поддержки.

    user_id/page — для совместимости сигнатуры, не используются.
    """
    name = support_bot_username()
    if name:
        text = ("💬 <b>Поддержка</b>\n\n"
                "<blockquote>Напишите в бота поддержки — "
                "ответим там же.</blockquote>\n\n"
                "<i>Нажмите кнопку — откроется чат с поддержкой. "
                "Опишите вопрос одним сообщением, так ответим быстрее.</i>")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛟 Написать в поддержку", url=support_bot_url())],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
        ])
    else:
        text = ("💬 <b>Поддержка</b>\n\n"
                "<blockquote>Бот поддержки пока не настроен, "
                "обратитесь к администратору.</blockquote>")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="back_start")],
        ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb,
                                  disable_web_page_preview=True)
