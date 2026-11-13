from config import load_config


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
        await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
    except Exception:
        pass
