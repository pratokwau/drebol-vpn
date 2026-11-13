"""Бот поддержки Drebol VPN (отдельный бот).

Пользователь пишет сюда: после /start любое его сообщение (текст,
фото, файл, голосовое) уходит в его тему в группе поддержки, а ответ
из темы возвращается ему сюда же. Команды после /start не нужны —
всё, что он пишет, это обращение в поддержку.

Запуск: ~/workspace/venv-bot/bin/python support_bot.py
Токен — в config.json (support_bot_token), ID группы — support_group_id
(задаётся в админке основного бота: «👥 Группа поддержки»).
Оба бота должны быть админами в группе, в группе включены темы.
"""
import asyncio
import logging
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
)

from config import load_config
import core.database as db

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO)
log = logging.getLogger("support_bot")


def _topic_name(first_name, username, tg_id: str) -> str:
    """Имя темы: клиент в едином формате, не длиннее 128 символов."""
    label = db.format_client(first_name, username, tg_id, html=False)
    return label[:120]


async def _ensure_topic(bot, user) -> int | None:
    """Тема юзера в группе: вернуть topic_id (создать, если нет)."""
    cfg = load_config()
    group_id = cfg.get("support_group_id")
    if not group_id:
        return None
    row = await db.get_support_topic(user.id)
    if row and row[2] == "open":
        return int(row[0])
    try:
        topic = await bot.create_forum_topic(
            chat_id=group_id, name=_topic_name(user.first_name, user.username, user.id))
    except Exception as e:
        log.error("create_forum_topic failed for %s: %s", user.id, e)
        return None
    topic_id = int(topic.message_thread_id)
    await db.set_support_topic(user.id, topic_id, int(group_id))
    # карточка в теме: кто это, чтобы было видно без открытия профиля
    try:
        await bot.send_message(
            chat_id=group_id, message_thread_id=topic_id,
            text=f"🎫 Новое обращение\n\n"
                 f"{db.format_client(user.first_name, user.username, user.id)}",
            parse_mode="HTML")
    except Exception:
        pass
    return topic_id


async def _register_user(user) -> None:
    """Юзер в общей базе (имя/ник для формата клиента и истории)."""
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO users (id, first_name, username) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET first_name = excluded.first_name, "
            "username = excluded.username",
            (user.id, user.first_name or "", user.username or ""))
        await conn.commit()


async def cmd_start(update: Update, context) -> None:
    user = update.effective_user
    await _register_user(user)
    await update.message.reply_text(
        "👋 <b>Поддержка Drebol VPN</b>\n\n"
        "Напишите ваш вопрос — он сразу уйдёт в поддержку, а ответ "
        "придёт сюда же.\n\n"
        "<i>Команды вводить не нужно: всё, что вы пишете, — это обращение. "
        "Можно прислать текст, фото или файл.\n\n"
        "✅ на вашем сообщении — значит, оно отправлено в поддержку.</i>",
        parse_mode="HTML")


async def _react_sent(msg) -> None:
    """✅ на сообщение юзера — подтверждение, что оно ушло в поддержку.

    Реакция — приятный бонус, а не обязательная часть: если Telegram
    её не принял, пересылка всё равно уже выполнена, молча идём дальше.
    """
    try:
        await msg.set_reaction("✅")
    except Exception as e:
        log.debug("set_reaction failed: %s", e)


async def on_user_message(update: Update, context) -> None:
    """Любое сообщение юзера в личку → в его тему в группе."""
    msg = update.message
    user = update.effective_user
    if not msg or not user:
        return
    cfg = load_config()
    group_id = cfg.get("support_group_id")
    if not group_id:
        await msg.reply_text(
            "⚠️ Поддержка временно недоступна — группа не настроена. "
            "Напишите, пожалуйста, позже.",
            parse_mode="HTML")
        return
    await _register_user(user)
    topic_id = await _ensure_topic(context.bot, user)
    if not topic_id:
        await msg.reply_text(
            "⚠️ Не удалось создать обращение — попробуйте ещё раз чуть позже.",
            parse_mode="HTML")
        return
    try:
        await msg.copy(chat_id=group_id, message_thread_id=topic_id)
        await db.touch_support_topic(user.id)
        await _react_sent(msg)
    except Exception as e:
        log.error("copy to topic failed for %s: %s", user.id, e)
        await msg.reply_text(
            "⚠️ Не удалось отправить — попробуйте ещё раз чуть позже.",
            parse_mode="HTML")


async def on_group_message(update: Update, context) -> None:
    """Сообщение в группе (в теме) → переслать юзеру в бота поддержки.

    Сюда попадают и ответы Марка/помощников, и служебные сообщения
    бота (карточка темы) — свои сообщения бота не пересылаем.
    """
    msg = update.message
    if not msg or not msg.message_thread_id:
        return
    if msg.from_user and msg.from_user.is_bot:
        return
    cfg = load_config()
    group_id = cfg.get("support_group_id")
    if not group_id or msg.chat_id != int(group_id):
        return
    user_id = await db.get_user_by_topic(msg.message_thread_id, int(group_id))
    if not user_id:
        return
    try:
        await msg.copy(chat_id=user_id)
        await db.touch_support_topic(user_id)
    except Exception as e:
        log.error("copy to user %s failed: %s", user_id, e)


async def cmd_close(update: Update, context) -> None:
    """ /close в теме — закрыть обращение (тема остаётся для истории)."""
    msg = update.message
    if not msg or not msg.message_thread_id:
        return
    cfg = load_config()
    group_id = cfg.get("support_group_id")
    if not group_id or msg.chat_id != int(group_id):
        return
    user_id = await db.get_user_by_topic(msg.message_thread_id, int(group_id))
    if not user_id:
        return
    await db.set_support_topic_status(user_id, "closed")
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ <b>Обращение закрыто.</b>\n\n"
                 "<i>Если появится новый вопрос — просто напишите сюда.</i>",
            parse_mode="HTML")
    except Exception:
        pass
    await msg.reply_text("✅ Обращение закрыто.", parse_mode="HTML")


def main() -> None:
    cfg = load_config()
    token = cfg.get("support_bot_token")
    if not token:
        print("support_bot_token не задан в config.json. "
              "Создай бота у @BotFather и впиши токен в config.json "
              "(ключ support_bot_token).")
        sys.exit(1)
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("close", cmd_close))
    # личка: любое сообщение — обращение
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND,
                                   on_user_message))
    # группа: сообщения в темах — ответы юзеру
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND,
                                   on_group_message))
    log.info("support bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
