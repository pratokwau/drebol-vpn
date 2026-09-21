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


def subscribe_keyboard() -> InlineKeyboardMarkup:
    cfg = load_config()
    channel_url = cfg.get("channel_url", "https://t.me/")
    return InlineKeyboardMarkup([
        # Цвет кнопки — поле style из Bot API 9.4: danger, success или primary.
        # Библиотека 21.9 про это поле не знает, поэтому передаём через api_kwargs:
        # to_dict() отправляет их как есть, а старые клиенты просто игнорируют.
        [InlineKeyboardButton("📢 Подписаться на канал", url=channel_url,
                              api_kwargs={"style": "primary"})],
        [InlineKeyboardButton("✅ Я подписался", callback_data="check_sub",
                              api_kwargs={"style": "success"})],
    ])
