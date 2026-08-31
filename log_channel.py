from config import load_config


async def send_log(bot, text: str):
    cfg = load_config()
    channel_id = cfg.get("log_channel_id")
    if not channel_id:
        return
    try:
        await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
    except Exception:
        pass
