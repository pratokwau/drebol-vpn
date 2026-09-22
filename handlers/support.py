"""Поддержка со стороны клиента.

Раньше это была одна лента сообщений: человек писал что угодно, и всё
падало админу. Теперь у обращения есть тема, а на частые вопросы бот сначала
отвечает сам — большая часть обращений решается без переписки. Если подсказка
не помогла, тема уезжает вместе с обращением, и админ сразу видит, о чём речь.
"""

from datetime import datetime
from html import escape

from database import (
    get_support_messages, count_support_files, get_support_files,
    get_ticket, ticket_closed,
)
from keyboards import support_keyboard, support_topics_keyboard

SEP = "━" * 14

# Темы обращения: эмодзи, название и подсказка, которую бот даёт до переписки.
# Кнопки в подсказке ведут туда, где вопрос решается сам.
TOPICS = {
    "connect": {
        "emoji": "🔌",
        "name": "Не подключается",
        "hint": (
            "Чаще всего помогает одно из трёх:\n\n"
            "1️⃣ <b>Обновите подписку в приложении.</b>\n"
            "В INCY или Happ откройте подписку и потяните список вниз — "
            "сервера обновятся.\n\n"
            "2️⃣ <b>Проверьте срок.</b>\n"
            "Если подписка закончилась, доступ выключен до оплаты.\n\n"
            "3️⃣ <b>Перевыпустите ключ.</b>\n"
            "Если ссылка попала к кому-то ещё или приложение путается — "
            "новая ссылка решает это за минуту."
        ),
        "buttons": [("👤 Моя подписка", "my_paid_sub"), ("🔁 Перевыпуск ключа", "reissue_key")],
    },
    "devices": {
        "emoji": "📱",
        "name": "Устройства и лимит",
        "hint": (
            "На подписку можно подключить ограниченное число устройств.\n\n"
            "Если лимит занят — отключите ненужное устройство в разделе "
            "<b>«Мои устройства»</b>, и слот освободится сразу.\n"
            "Нужно больше — там же можно добавить устройства."
        ),
        "buttons": [("📱 Мои устройства", "my_devices")],
    },
    "pay": {
        "emoji": "💳",
        "name": "Оплата и продление",
        "hint": (
            "Оплата засчитывается автоматически — обычно в течение минуты.\n\n"
            "Продлить можно <b>в любой момент</b>: остаток срока не сгорает, "
            "новые дни прибавятся к нему.\n\n"
            "Если деньги ушли, а подписка не продлилась дольше 10 минут — "
            "напишите нам, разберёмся вручную."
        ),
        "buttons": [("💳 Продлить подписку", "renew_sub")],
    },
    "speed": {
        "emoji": "🐢",
        "name": "Медленно работает",
        "hint": (
            "Попробуйте по порядку:\n\n"
            "1️⃣ Выберите <b>другой сервер</b> в приложении — скорость сильно "
            "зависит от точки подключения.\n"
            "2️⃣ Переключитесь между Wi-Fi и мобильным интернетом.\n"
            "3️⃣ Закройте и откройте приложение заново.\n\n"
            "Если не помогло — напишите, какой сервер и какая скорость без VPN."
        ),
        "buttons": [],
    },
    "idea": {
        "emoji": "💡",
        "name": "Идея или пожелание",
        "hint": "Расскажите, чего не хватает — мы правда читаем и добавляем.",
        "buttons": [],
    },
    "other": {
        "emoji": "✍️",
        "name": "Другое",
        "hint": "Опишите вопрос своими словами — ответим.",
        "buttons": [],
    },
}


def topic_label(key: str) -> str:
    t = TOPICS.get(key) or TOPICS["other"]
    return f"{t['emoji']} {t['name']}"


def _fmt_time(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        today = datetime.now().date()
        return dt.strftime("%H:%M") if dt.date() == today else dt.strftime("%d.%m · %H:%M")
    except Exception:
        return raw


def _status_line(ticket: dict) -> str:
    status = ticket["status"]
    if status == "closed":
        return "✅ <b>Вопрос закрыт</b>\n<i>Напишите снова, если понадобится.</i>"
    if status == "answered":
        return "🛡 <b>Поддержка ответила</b>\n<i>Если вопрос остался — пишите дальше.</i>"
    return "🟢 <b>Ждём ответа поддержки</b>\n<i>Обычно отвечаем в течение часа.</i>"


def _bubble(row) -> str:
    text, from_admin, created_at = row[0], row[1], row[2]
    file_id = row[3] if len(row) > 3 else None
    file_type = row[4] if len(row) > 4 else None
    who = "🛡 <b>Поддержка</b>" if from_admin else "👤 <b>Вы</b>"
    mark = ""
    if file_id:
        mark = " 🖼" if file_type == "photo" else " 📎"
    body = escape(text or "")
    if not body and file_id:
        body = "<i>файл</i>"
    return f"{who} · <i>{_fmt_time(created_at)}</i>{mark}\n{body}"


async def open_support(query, user_id: int, page: int | None = None):
    """Главный экран поддержки: либо выбор темы, либо сама переписка."""
    _, total_pages = await get_support_messages(user_id, 1)
    msgs_exist = (await get_support_messages(user_id, 1))[0]
    if not msgs_exist:
        await show_topics(query)
        return

    if page is None:
        page = total_pages
    msgs, total_pages = await get_support_messages(user_id, page)
    has_files = (await count_support_files(user_id)) > 0
    ticket = await get_ticket(user_id)

    parts = [
        "💬 <b>Drebol VPN · Поддержка</b>",
        _status_line(ticket),
    ]
    head = "\n\n".join(parts) + f"\n📌 Тема: <b>{topic_label(ticket['topic'])}</b>"
    body = "\n\n".join(_bubble(r) for r in msgs)
    tail = "✍️ <i>Напишите сообщение или отправьте файл — всё придёт сюда.</i>"
    text = f"{head}\n\n{SEP}\n\n{body}\n\n{SEP}\n\n{tail}"
    if total_pages > 1:
        text += f"\n<i>Страница {page} из {total_pages}</i>"

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=support_keyboard(page, total_pages, has_files,
                                      can_close=ticket["status"] != "closed"),
    )


async def show_topics(query):
    """Первый экран: с чем помочь."""
    await query.edit_message_text(
        "💬 <b>Drebol VPN · Поддержка</b>\n\n"
        "Выберите тему — по частым вопросам я подскажу сразу, "
        "без ожидания ответа.\n\n"
        f"{SEP}\n\n"
        "<i>Если нужного нет — выбирайте «Другое» и пишите своими словами.</i>",
        parse_mode="HTML",
        reply_markup=support_topics_keyboard(TOPICS),
    )


async def show_topic_hint(query, context, topic: str):
    """Подсказка по теме. Не помогло — кнопка увести в переписку."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    t = TOPICS.get(topic) or TOPICS["other"]
    rows = [[InlineKeyboardButton(label, callback_data=data)]
            for label, data in t["buttons"]]
    rows.append([InlineKeyboardButton("✍️ Написать в поддержку",
                                      callback_data=f"support_write:{topic}")])
    rows.append([InlineKeyboardButton("◀️ Другая тема", callback_data="support_open")])
    await query.edit_message_text(
        f"{t['emoji']} <b>{t['name']}</b>\n\n"
        f"{t['hint']}\n\n"
        f"{SEP}\n\n"
        "<i>Не помогло? Напишите нам — разберёмся вместе.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def start_writing(query, context, topic: str):
    """Ставит тему и ждёт текст обращения."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_SUPPORT_MSG
    context.user_data["state"] = AWAITING_SUPPORT_MSG
    context.user_data["support_topic"] = topic
    await query.edit_message_text(
        f"✍️ <b>Ваше обращение</b>\n"
        f"📌 Тема: <b>{topic_label(topic)}</b>\n\n"
        "Опишите вопрос одним сообщением. Можно приложить фото или файл — "
        "скриншот ошибки помогает решить всё быстрее.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data=f"support_topic:{topic}")],
        ]),
    )


async def handle_support_close(query, user_id: int):
    """Человек сам закрыл вопрос."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await ticket_closed(user_id)
    await query.edit_message_text(
        "✅ <b>Вопрос закрыт</b>\n\n"
        "Спасибо, что написали! Если понадобимся снова — "
        "просто откройте поддержку и напишите.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Открыть поддержку", callback_data="support_open")],
            [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")],
        ]),
    )


async def handle_support_files(query, user_id: int):
    files = await get_support_files(user_id)
    if not files:
        await query.answer("Файлов пока нет.", show_alert=True)
        return
    await query.answer(f"Отправляю файлы: {len(files)}")
    for file_id, file_type, from_admin, created_at in files:
        who = "🛡 Поддержка" if from_admin else "👤 Вы"
        caption = f"{who} · {_fmt_time(created_at)}"
        try:
            if file_type == "photo":
                await query.message.reply_photo(file_id, caption=caption)
            else:
                await query.message.reply_document(file_id, caption=caption)
        except Exception:
            pass
