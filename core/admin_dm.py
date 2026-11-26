"""Первое сообщение админа человеку из основного бота («📌 Написать»).

Куда уходит сообщение — решает, был ли у человека диалог в боте
поддержки (темы в группе поддержки общие, одна на человека навсегда):

- Диалог есть (тему создал сам человек, origin != 'admin'): сообщение
  кладём в его тему в группе — бот поддержки перешлёт его человеку
  сам, как пересылает ответы из веб-админки. Переписка продолжается
  в теме.
- Диалога нет: заводим тему в группе от имени админа (origin='admin'),
  а сообщение шлём человеку прямо в основной бот с припиской, что
  продолжить общение можно в боте поддержки. Копию в теме бот
  поддержки не пересылает (пропускает сообщения ботов в admin-темах),
  дубля не выходит. Когда человек напишет в бота поддержки, его
  сообщения попадут в эту же тему, и origin станет 'user'.

Группы поддержки нет в настройках — fallback: просто сообщение в
основной бот, как работало раньше.
"""
from html import escape

from config import load_config
import core.database as db


def _footer() -> str:
    """Приписка к первому сообщению: куда идти продолжать общение."""
    from handlers.support import support_bot_username
    name = support_bot_username()
    if name:
        return (f"\n\n<i>✉️ Продолжить общение можно в боте поддержки: "
                f"@{escape(name)}</i>")
    return ("\n\n<i>✉️ Продолжить общение можно через кнопку "
            "«🛟 Поддержка» в меню этого бота.</i>")


async def ensure_user_topic(bot, tg_id: int):
    """Тема человека в группе поддержки: (topic_id, group_id) или None.

    Существующую тему (любого origin) переиспользуем. Нет темы —
    создаём основным ботом и помечаем origin='admin': человек сам
    в поддержку ещё не обращался.
    """
    cfg = load_config()
    group_id = cfg.get("support_group_id")
    if not group_id:
        return None
    group_id = int(group_id)
    row = await db.get_support_topic_full(tg_id)
    if row and int(row[1]) == group_id:
        return int(row[0]), group_id
    from core.database import get_user_info
    u = await get_user_info(tg_id)
    first_name = u[1] if u else ""
    username = u[2] if u else ""
    name = db.format_client(first_name, username, tg_id, html=False)[:120]
    try:
        topic = await bot.create_forum_topic(chat_id=group_id, name=name)
    except Exception:
        return None
    topic_id = int(topic.message_thread_id)
    await db.set_support_topic(tg_id, topic_id, group_id, name,
                               origin="admin")
    try:
        await bot.send_message(
            chat_id=group_id, message_thread_id=topic_id,
            text="💬 <b>Тема заведена админом</b> из основного бота.\n\n"
                 "<i>Переписка ведётся прямо здесь: сообщения из темы "
                 "человеку пересылает бот поддержки. Если человек ещё "
                 "ни разу не писал в бота поддержки, пересылка не "
                 "сработает, пока он не обратится туда сам, — тема у "
                 "него одна, и переписка продолжится в ней же.</i>",
            parse_mode="HTML")
    except Exception:
        pass
    return topic_id, group_id


def _preview(msg) -> str:
    if msg.text:
        return escape(msg.text[:100])
    if msg.caption:
        return escape(msg.caption[:100])
    if msg.photo:
        return "🖼 фото"
    if msg.document:
        return f"📎 {escape(msg.document.file_name or 'файл')}"
    if msg.video:
        return "🎬 видео"
    if msg.voice:
        return "🎤 голосовое"
    if msg.video_note:
        return "⭕ видеосообщение"
    if msg.audio:
        return "🎵 аудио"
    return "сообщение"


async def deliver_admin_message(bot, msg, target_id: int) -> dict:
    """Доставить сообщение админа (msg из чата с основным ботом) человеку.

    Возвращает {"ok": True, "via": "support" | "main" | "main_plain",
    "report": готовый текст подтверждения админу} или
    {"ok": False, "error": str}.
    """
    try:
        row = await db.get_support_topic_full(target_id)
        cfg = load_config()
        group_id = cfg.get("support_group_id")
        has_dialog = bool(
            row and group_id and int(row[1]) == int(group_id)
            and row[3] != "admin")

        topic = await ensure_user_topic(bot, target_id)

        if has_dialog and topic:
            topic_id, gid = topic
            await bot.copy_message(
                chat_id=gid, message_thread_id=topic_id,
                from_chat_id=msg.chat_id, message_id=msg.message_id)
            await db.touch_support_topic(target_id)
            via = "support"
            report = ("✅ Отправлено: сообщение легло в тему человека "
                      "в группе и уйдёт ему в бота поддержки. Если бота "
                      "поддержки он заблокировал — уйдёт основным ботом "
                      "(на сообщении в теме встанет 📨), а если не дойдёт "
                      "никак, в теме появится предупреждение.")
        elif topic:
            # Диалога в поддержке нет: человеку — в основной бот
            # с припиской, копия — в свежесозданную тему.
            topic_id, gid = topic
            footer = _footer()
            if msg.text:
                await bot.send_message(
                    chat_id=target_id,
                    text=("📌 <b>Сообщение от Drebol VPN</b>\n\n"
                          f"<blockquote>{escape(msg.text)}</blockquote>"
                          f"{footer}"),
                    parse_mode="HTML")
            else:
                caption = msg.caption or ""
                new_caption = (caption + footer) if caption else footer.strip()
                if len(new_caption) <= 1024:
                    await bot.copy_message(
                        chat_id=target_id, from_chat_id=msg.chat_id,
                        message_id=msg.message_id, caption=new_caption,
                        parse_mode="HTML")
                else:
                    await bot.copy_message(
                        chat_id=target_id, from_chat_id=msg.chat_id,
                        message_id=msg.message_id)
                    await bot.send_message(chat_id=target_id, text=footer,
                                           parse_mode="HTML")
            await bot.copy_message(
                chat_id=gid, message_thread_id=topic_id,
                from_chat_id=msg.chat_id, message_id=msg.message_id)
            await db.touch_support_topic(target_id)
            via = "main"
            report = ("✅ Отправлено пользователю в основной бот "
                      "(в бота поддержки он ещё не писал). Тема в группе "
                      "создана — отвечать можно и из неё.")
        else:
            # Группа поддержки не настроена: как раньше, просто в личку.
            if msg.text:
                await bot.send_message(
                    chat_id=target_id,
                    text=("📌 <b>Сообщение от Drebol VPN</b>\n\n"
                          f"<blockquote>{escape(msg.text)}</blockquote>"),
                    parse_mode="HTML")
            else:
                await bot.copy_message(
                    chat_id=target_id, from_chat_id=msg.chat_id,
                    message_id=msg.message_id)
            via = "main_plain"
            report = "✅ Сообщение отправлено пользователю."

        try:
            from core.log_channel import send_log
            await send_log(
                bot, f"📌 Админ → <code>{target_id}</code> "
                     f"({via}): {_preview(msg)}")
        except Exception:
            pass
        return {"ok": True, "via": via, "report": report}
    except Exception as e:
        return {"ok": False, "error": str(e)}
