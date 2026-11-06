from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from config import load_config


def extract_channel_username(url: str) -> str | None:
    """Из https://t.me/mychannel → @mychannel. Для приватных ссылок (+) — None."""
    if "t.me/" in url and "+" not in url:
        username = url.split("t.me/")[-1].strip("/").split("?")[0]
        if username:
            return f"@{username}"
    return None


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """True если юзер подписан или проверка невозможна (бот не в канале)."""
    cfg = load_config()
    if not cfg.get("force_subscribe"):
        return True
    channel_url = cfg.get("channel_url", "")
    username = extract_channel_username(channel_url)
    if not username:
        return True  # приватная ссылка — не можем проверить
    try:
        member = await bot.get_chat_member(chat_id=username, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return True  # бот не админ канала или другая ошибка — пропускаем


def subscribe_text(first_name, retry: bool = False) -> str:
    """Экран «подпишитесь на канал» — один на /start и на все кнопки.

    retry=True — человек нажал «Я подписался», а подписки ещё не видно.
    """
    from html import escape
    name = escape(str(first_name or ""))
    head = (f"👋 Привет, {name}!\n" if name else "👋 Привет!\n") + \
        "Это <b>Drebol VPN</b> — быстрый VPN без логов 🔒\n\n"
    if retry:
        return (head + "<blockquote>🤔 Пока не видим вашу подписку на канал.</blockquote>\n\n"
                "<i>Подпишитесь по кнопке ниже и нажмите «✅ Я подписался» ещё раз.</i>")
    return (head + "<blockquote>🎁 Пробный период выдадим сразу — остался один шаг: "
            "подпишитесь на наш канал.</blockquote>\n\n"
            "<i>После подписки нажмите «✅ Я подписался».</i>")


def subscribe_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_url = cfg.get("channel_url", "https://t.me/")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Перейти в канал", url=channel_url)],
        [InlineKeyboardButton("✅ Я подписался", callback_data="check_sub")],
    ])
