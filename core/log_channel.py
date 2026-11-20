import re

from config import load_config

_SUB_URL_RE = re.compile(r"((?:https?://)?(?:sub|key)\.drbl\.tech/)([^\s<>\"']+)")


def mask_sub_urls(text: str) -> str:
    """Маскирует хвост ссылок подписки в тексте лога.

    Лог уходит в группу поддержки, а полный токен в ссылке — это доступ
    к чужой подписке. Оставляем домен и первые символы токена (чтобы
    ссылку можно было опознать), остальное заменяем звёздочками:
    sub.drbl.tech/behwjjej******.
    """
    def _mask(m: "re.Match") -> str:
        head, token = m.group(1), m.group(2)
        keep = token[:8] if len(token) > 10 else token[:2]
        return head + keep + "******"

    return _SUB_URL_RE.sub(_mask, text)


async def send_log(bot, text: str):
    """Логи бота: в группу поддержки (если задана), иначе в лог-канал.

    В группе с темами логи идут в общую тему (без message_thread_id) —
    темы там только для обращений. Если группа не задана — как раньше,
    в log_channel_id.
    """
    cfg = load_config()
    group_id = cfg.get("support_group_id")
    channel_id = group_id or cfg.get("log_channel_id")
    if not channel_id:
        return
    try:
        await bot.send_message(chat_id=channel_id, text=mask_sub_urls(text), parse_mode="HTML")
    except Exception:
        pass
