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


_MARK_OPEN = "❗️ "
_MARK_CLOSED = "✅ "
_MARKS = ("❗️", "✅")


def _marked_name(base: str, status: str) -> str:
    """Имя темы с отметкой статуса: ❗️ — тикет открыт, ✅ — закрыт.

    Отметка — префикс названия: иконку темы боту Telegram ставить не даёт
    (только кастомные эмодзи из фиксированного набора), а префикс в списке
    тем выглядит так же и меняется через editForumTopic.
    """
    name = (base or "").strip()
    changed = True
    while changed:
        changed = False
        for m in _MARKS:
            if name.startswith(m):
                name = name[len(m):].lstrip()
                changed = True
    mark = _MARK_CLOSED if status == "closed" else _MARK_OPEN
    return (mark + name)[:128]


async def _get_topic_row(user_id: int):
    """(topic_id, group_id, status, topic_name) из support_topics."""
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT topic_id, group_id, status, topic_name "
            "FROM support_topics WHERE user_id = ?", (user_id,))
        return await cur.fetchone()


async def _set_topic_name(user_id: int, name: str) -> None:
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "UPDATE support_topics SET topic_name = ? WHERE user_id = ?",
            (name, user_id))
        await conn.commit()


async def _sync_topic_mark(bot, user_id: int) -> None:
    """Привести отметку в названии темы к текущему статусу тикета."""
    row = await _get_topic_row(user_id)
    if not row:
        return
    topic_id, group_id, status, topic_name = row
    base = topic_name
    if not base:
        # У старых тем имя в базе не сохранилось — собрать заново.
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            cur = await conn.execute(
                "SELECT first_name, username FROM users WHERE id = ?",
                (user_id,))
            urow = await cur.fetchone()
        base = (_topic_name(urow[0], urow[1], user_id) if urow
                else str(user_id))
    new_name = _marked_name(base, status)
    if topic_name == new_name:
        return
    try:
        await bot.edit_forum_topic(
            chat_id=int(group_id), message_thread_id=int(topic_id),
            name=new_name)
    except Exception as e:
        log.warning("edit_forum_topic %s failed: %s", user_id, e)
        return
    await _set_topic_name(user_id, new_name)


async def _backfill_topic_marks(app) -> None:
    """Стартовая сверка: отметки статуса на всех существующих темах."""
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute("SELECT user_id FROM support_topics")
        rows = await cur.fetchall()
    renamed = 0
    for (user_id,) in rows:
        before = await _get_topic_row(user_id)
        await _sync_topic_mark(app.bot, user_id)
        after = await _get_topic_row(user_id)
        if before and after and before[3] != after[3]:
            renamed += 1
        await asyncio.sleep(0.05)
    log.info("topic marks backfill: renamed %s of %s", renamed, len(rows))


async def _create_topic(bot, user, group_id) -> int | None:
    """Создать юзеру новую тему в группе и записать её в базу."""
    topic_name = _marked_name(
        _topic_name(user.first_name, user.username, user.id), "open")
    try:
        topic = await bot.create_forum_topic(
            chat_id=group_id, name=topic_name)
    except Exception as e:
        log.error("create_forum_topic failed for %s: %s", user.id, e)
        return None
    topic_id = int(topic.message_thread_id)
    await db.set_support_topic(user.id, topic_id, int(group_id), topic_name)
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


async def _ensure_topic(bot, user) -> int | None:
    """Тема юзера в группе: одна на человека, навсегда.

    Закрытие (/close) — только пометка в базе: если человек пишет снова,
    обращение продолжается в той же теме (статус возвращается в open),
    новая тема не создаётся — вся история переписки в одном месте.
    Новая тема нужна лишь если старой нет или группа сменилась.
    """
    cfg = load_config()
    group_id = cfg.get("support_group_id")
    if not group_id:
        return None
    row = await db.get_support_topic(user.id)
    if row and int(row[1]) == int(group_id):
        if row[2] != "open":
            await db.set_support_topic_status(user.id, "open")
            await _sync_topic_mark(bot, user.id)
            try:
                await bot.send_message(
                    chat_id=group_id, message_thread_id=int(row[0]),
                    text="♻️ <b>Обращение продолжено</b> — человек написал "
                         "снова после закрытия.",
                    parse_mode="HTML")
            except Exception:
                pass
        return int(row[0])
    return await _create_topic(bot, user, group_id)


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
        "👍 на вашем сообщении — значит, оно отправлено в поддержку.</i>",
        parse_mode="HTML")


async def _react_sent(msg) -> None:
    """👍 на сообщение юзера — подтверждение, что оно ушло в поддержку.

    Важно: ✅ в реакциях Telegram НЕТ, поэтому используем 👍 —
    он есть в списке доступных реакций и означает «принято».
    Реакция — приятный бонус, а не обязательная часть: если Telegram
    её не принял, пересылка всё равно уже выполнена, молча идём дальше.
    """
    try:
        await msg.set_reaction("👍")
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
        # Возможно, тему удалили из группы вручную: создать свежую
        # и повторить отправку один раз, а не терять обращение.
        log.error("copy to topic failed for %s: %s", user.id, e)
        new_topic = await _create_topic(context.bot, user, group_id)
        if new_topic and new_topic != topic_id:
            try:
                await msg.copy(chat_id=group_id, message_thread_id=new_topic)
                await db.touch_support_topic(user.id)
                await _react_sent(msg)
                return
            except Exception as e2:
                log.error("copy to new topic failed for %s: %s", user.id, e2)
        await msg.reply_text(
            "⚠️ Не удалось отправить — попробуйте ещё раз чуть позже.",
            parse_mode="HTML")


async def on_group_message(update: Update, context) -> None:
    """Сообщение в группе (в теме) → переслать юзеру в бота поддержки.

    Сюда попадают и ответы Марка/помощников, и служебные сообщения
    бота (карточка темы), и ответы основного бота из веб-админки.
    Не пересылаем только свои сообщения (карточка темы и т.п.):
    сообщения других ботов — в первую очередь основного бота —
    пересылаем, иначе ответ из веб-админки остался бы в теме
    и не дошёл бы до юзера.
    """
    msg = update.message
    if not msg or not msg.message_thread_id:
        return
    if msg.from_user and msg.from_user.is_bot:
        if msg.from_user.id == context.bot.id:
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
    row = await db.get_support_topic(user_id)
    if row and row[2] == "closed":
        # Повторный /close: пользователю «закрыто» второй раз не шлём,
        # отвечаем только сюда, в тему.
        await _sync_topic_mark(context.bot, user_id)
        await msg.reply_text(
            "ℹ️ Обращение уже закрыто — повторно пользователю ничего "
            "не отправлено.")
        return
    await db.set_support_topic_status(user_id, "closed")
    await _sync_topic_mark(context.bot, user_id)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ <b>Обращение закрыто.</b>\n\n"
                 "<i>Если появится новый вопрос — просто напишите сюда.</i>",
            parse_mode="HTML")
    except Exception:
        pass
    await msg.reply_text(
        "✅ Обращение закрыто. Если человек напишет снова — переписка "
        "продолжится прямо здесь, в этой же теме.", parse_mode="HTML")


def main() -> None:
    cfg = load_config()
    token = cfg.get("support_bot_token")
    if not token:
        print("support_bot_token не задан в config.json. "
              "Создай бота у @BotFather и впиши токен в config.json "
              "(ключ support_bot_token).")
        sys.exit(1)
    app = (Application.builder().token(token)
           .post_init(_backfill_topic_marks).build())
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
