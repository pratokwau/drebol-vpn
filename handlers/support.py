"""Поддержка со стороны клиента.

Раньше это была одна лента сообщений: человек писал что угодно, и всё
падало админу. Теперь у обращения есть тема, а на частые вопросы бот сначала
отвечает сам — большая часть обращений решается без переписки. Если подсказка
не помогла, тема уезжает вместе с обращением, и админ сразу видит, о чём речь.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from database import (
    get_support_messages, count_support_files, get_support_files,
    get_ticket, ticket_closed,
)
from keyboards import support_keyboard, support_topics_keyboard

# Темы обращения: эмодзи, название и подсказка, которую бот даёт до переписки.
# Кнопки в подсказке ведут туда, где вопрос решается сам.
TOPICS = {
    "connect": {
        "emoji": "🔌",
        "name": "Не подключается",
        "hint": ("Обновите подписку в приложении — потяните список вниз.\n"
                 "Не помогло — перевыпустите ключ."),
        "buttons": [("🔁 Перевыпуск ключа", "reissue_key")],
    },
    "devices": {
        "emoji": "📱",
        "name": "Устройства",
        "hint": "Лимит занят? Отключите лишнее устройство — место освободится сразу.",
        "buttons": [("📱 Мои устройства", "my_devices")],
    },
    "pay": {
        "emoji": "💳",
        "name": "Оплата",
        "hint": ("Оплата засчитывается сама за минуту.\n"
                 "Прошло больше 10 минут — напишите нам."),
        "buttons": [("💳 Продлить подписку", "renew_sub")],
    },
    "speed": {
        "emoji": "🐢",
        "name": "Медленно",
        "hint": "Смените сервер в приложении или переключитесь между Wi-Fi и мобильной сетью.",
        "buttons": [],
    },
    "idea": {
        "emoji": "💡",
        "name": "Идея",
        "hint": "Напишите — мы читаем всё.",
        "buttons": [],
    },
    "other": {
        "emoji": "✍️",
        "name": "Другое",
        "hint": "Опишите вопрос — ответим.",
        "buttons": [],
    },
}


# ── Режим поддержки ──────────────────────────────────────────────────────────
#
# Поддержка работает одним из двух способов:
#   tickets — переписка живёт в боте (темы, тикеты, файлы, ответы админа);
#   contact — бот никого не расспрашивает, а уводит человека в личку
#             указанного аккаунта в телеграме.
# Режим и аккаунт задаются в админке: «💬 Поддержка».

MODE_TICKETS = "tickets"
MODE_CONTACT = "contact"


def support_mode() -> str:
    from config import load_config
    mode = (load_config().get("support_mode") or MODE_TICKETS).strip()
    return MODE_CONTACT if mode == MODE_CONTACT and support_contact() else MODE_TICKETS


def support_contact() -> str:
    """Аккаунт поддержки без «@». Пусто — не задан."""
    from config import load_config
    raw = str(load_config().get("support_contact") or "").strip()
    raw = raw.replace("https://t.me/", "").replace("t.me/", "").lstrip("@").strip("/")
    return raw.split("?")[0].strip()


def support_url() -> str:
    name = support_contact()
    return f"https://t.me/{name}" if name else ""


def contact_mode() -> bool:
    return support_mode() == MODE_CONTACT


def support_button(text: str = "💬 Поддержка", force: bool = False):
    """Кнопка поддержки: ссылка на аккаунт или вход в переписку в боте.

    force — показать даже если функция выключена в техработах (для админа).
    None означает, что кнопки быть не должно.
    """
    from telegram import InlineKeyboardButton
    import maintenance as mnt
    if not force and not mnt.feature_enabled("support"):
        return None
    if contact_mode():
        return InlineKeyboardButton(text, url=support_url())
    return InlineKeyboardButton(text, callback_data="support_open")


def support_row(text: str = "💬 Поддержка") -> list:
    """Готовый ряд кнопок — пустой, если поддержка выключена."""
    btn = support_button(text)
    return [btn] if btn else []


def contact_screen() -> tuple:
    """Экран «поддержка в телеграме»: текст и кнопка со ссылкой."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    name = support_contact()
    text = ("💬 <b>Поддержка</b>\n\n"
            f"<blockquote>Пишите нам в телеграм: @{name}</blockquote>\n\n"
            "<i>Нажмите кнопку — откроется чат с поддержкой. "
            "Опишите вопрос одним сообщением, так ответим быстрее.</i>")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Написать в поддержку", url=support_url())],
        [InlineKeyboardButton("◀️ Главное меню", callback_data="back_start")],
    ])
    return text, kb


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
        return "✅ вопрос закрыт"
    if status == "answered":
        return "🛡 поддержка ответила"
    return "🟢 ждём ответа"


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
    # каждое сообщение — своей цитатой: переписка читается как чат
    return f"{who} · <i>{_fmt_time(created_at)}</i>{mark}\n<blockquote>{body}</blockquote>"


async def open_support(query, user_id: int, page: int | None = None):
    """Главный экран поддержки: ссылка на аккаунт, выбор темы или переписка."""
    if contact_mode():
        text, kb = contact_screen()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb,
                                      disable_web_page_preview=True)
        return
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

    head = ("💬 <b>Поддержка</b>\n"
            f"📌 {topic_label(ticket['topic'])}  ·  {_status_line(ticket)}")
    body = "\n\n".join(_bubble(r) for r in msgs)
    text = f"{head}\n\n{body}\n\n<i>✍️ Напишите сообщение — оно придёт в этот чат.</i>"

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=support_keyboard(page, total_pages, has_files,
                                      can_close=ticket["status"] != "closed"),
    )


async def show_topics(query):
    """Первый экран: с чем помочь."""
    if contact_mode():
        text, kb = contact_screen()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb,
                                      disable_web_page_preview=True)
        return
    await query.edit_message_text(
        "💬 <b>Поддержка</b>\n\n"
        "С чем помочь? Выберите тему — по частым вопросам подскажем сразу.",
        parse_mode="HTML",
        reply_markup=support_topics_keyboard(TOPICS),
    )


async def show_topic_hint(query, context, topic: str):
    """Подсказка по теме. Не помогло — кнопка увести в переписку."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if contact_mode():
        text, kb = contact_screen()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb,
                                      disable_web_page_preview=True)
        return
    t = TOPICS.get(topic) or TOPICS["other"]
    rows = [[InlineKeyboardButton(label, callback_data=data)]
            for label, data in t["buttons"]]
    rows.append([InlineKeyboardButton("✍️ Написать нам",
                                      callback_data=f"support_write:{topic}")])
    rows.append([InlineKeyboardButton("◀️ К темам", callback_data="support_open")])
    await query.edit_message_text(
        f"{t['emoji']} <b>{t['name']}</b>\n\n"
        f"<blockquote>💡 {t['hint']}</blockquote>\n\n"
        "<i>Не помогло? Напишите нам — ответим здесь же, в боте.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def start_writing(query, context, topic: str):
    """Ставит тему и ждёт текст обращения."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_SUPPORT_MSG
    if contact_mode():
        text, kb = contact_screen()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb,
                                      disable_web_page_preview=True)
        return
    context.user_data["state"] = AWAITING_SUPPORT_MSG
    context.user_data["support_topic"] = topic
    await query.edit_message_text(
        "✍️ <b>Опишите вопрос</b>\n\n"
        f"<blockquote>Тема: {topic_label(topic)}</blockquote>\n\n"
        "<i>Одним сообщением. Можно приложить скриншот — так разберёмся быстрее.</i>",
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
        "<blockquote>Спасибо, что написали! Если что-то ещё — мы на связи.</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Новый вопрос", callback_data="support_open"),
             InlineKeyboardButton("◀️ Меню", callback_data="back_start")],
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


# ── Настройки поддержки (админка) ────────────────────────────────────────────

def _valid_contact(raw: str) -> str:
    """Username телеграма из чего угодно: @name, name, ссылка. Пусто — не годится."""
    name = (raw or "").strip()
    for prefix in ("https://", "http://", "t.me/", "telegram.me/", "@"):
        name = name.replace(prefix, "")
    name = name.strip("/ ").split("?")[0].split()[0] if name.strip() else ""
    if not (5 <= len(name) <= 32):
        return ""
    if not all(c.isascii() and (c.isalnum() or c == "_") for c in name):
        return ""
    return name


async def handle_support_settings(query, context=None, note: str = ""):
    """Две поддержки на выбор: переписка в боте или аккаунт в телеграме."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from database import get_unread_tickets_count, ticket_counts
    if context:
        context.user_data.pop("state", None)
    mode = support_mode()
    name = support_contact()
    counts = await ticket_counts()
    unread = await get_unread_tickets_count()

    lines = ["💬 <b>Поддержка</b>", ""]
    if note:
        lines += [note, ""]
    lines.append(
        "<blockquote>"
        f"⚙️ Режим: <b>{'🎫 Переписка в боте' if mode == MODE_TICKETS else '👤 Аккаунт в телеграме'}</b>\n"
        f"👤 Аккаунт: <b>{'@' + name if name else 'не задан'}</b>"
        "</blockquote>")
    if mode == MODE_TICKETS:
        lines.append(
            "<blockquote>"
            f"🎫 Открытых обращений: <b>{counts.get('open', 0)}</b>  ·  "
            f"без ответа: <b>{unread}</b>\n"
            f"✅ Закрытых: <b>{counts.get('closed', 0)}</b>"
            "</blockquote>")
    lines.append(
        "\n<i>🎫 Переписка в боте — человек выбирает тему, бот сначала подсказывает сам, "
        "а переписка и файлы лежат в «Тикетах».\n"
        "👤 Аккаунт в телеграме — бот ничего не спрашивает: кнопка «Поддержка» открывает "
        "личку указанного аккаунта, и человек пишет туда.</i>")

    kb = [[InlineKeyboardButton(("• " if mode == MODE_TICKETS else "") + "🎫 Переписка в боте",
                                callback_data="support_mode:tickets"),
           InlineKeyboardButton(("• " if mode == MODE_CONTACT else "") + "👤 Аккаунт",
                                callback_data="support_mode:contact")]]
    kb.append([InlineKeyboardButton("✍️ Сменить аккаунт" if name else "✍️ Указать аккаунт",
                                    callback_data="support_contact")])
    if name:
        kb.append([InlineKeyboardButton(f"🔗 Открыть @{name}", url=support_url())])
    if mode == MODE_TICKETS:
        kb.append([InlineKeyboardButton("🎫 К тикетам", callback_data="ticket_list:1")])
    kb.append([InlineKeyboardButton("◀️ Назад в админку", callback_data="admin_panel")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(kb),
                                  disable_web_page_preview=True)


async def handle_support_mode(query, context, mode: str):
    from config import load_config, save_config
    if mode == MODE_CONTACT and not support_contact():
        # включать некуда, пока не сказали, кому писать
        await handle_support_contact_ask(query, context,
                                         note="<i>Сначала укажи аккаунт поддержки.</i>")
        return
    cfg = load_config()
    cfg["support_mode"] = MODE_CONTACT if mode == MODE_CONTACT else MODE_TICKETS
    save_config(cfg)
    from log_channel import send_log
    await send_log(context.bot, "💬 Поддержка: " + (
        f"переключена на аккаунт @{support_contact()}" if mode == MODE_CONTACT
        else "переписка в боте"))
    note = ("<i>👤 Готово: кнопка «Поддержка» уводит в личку "
            f"@{support_contact()}.</i>" if mode == MODE_CONTACT
            else "<i>🎫 Готово: обращения снова приходят в бот.</i>")
    await handle_support_settings(query, context, note=note)


async def handle_support_contact_ask(query, context, note: str = ""):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from states import AWAITING_SUPPORT_CONTACT
    context.user_data["state"] = AWAITING_SUPPORT_CONTACT
    name = support_contact()
    await query.edit_message_text(
        "👤 <b>Аккаунт поддержки</b>\n\n"
        + (f"{note}\n\n" if note else "")
        + (f"<blockquote>Сейчас: <b>@{name}</b></blockquote>\n\n" if name else "")
        + "<blockquote>Пришли <code>@username</code> аккаунта — того, кто будет "
          "отвечать людям в телеграме.</blockquote>\n\n"
          "<i>У аккаунта должен быть username: без него ссылка не работает. "
          "Бот проверит только вид имени — открой чат кнопкой и убедись сам.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="support_settings")]]),
    )


async def handle_support_contact_input(update, context, text: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from config import load_config, save_config
    msg = update.message
    name = _valid_contact(text)
    if not name:
        await msg.reply_text(
            "❌ <b>Не похоже на username</b>\n\n"
            "<i>Латиница, цифры и «_», от 5 до 32 символов. Например: "
            "<code>@drebol_support</code>.</i>", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ К поддержке", callback_data="support_settings")]]))
        return
    cfg = load_config()
    cfg["support_contact"] = name
    save_config(cfg)
    context.user_data.pop("state", None)
    mode_line = ("<i>Режим уже включён — кнопка «Поддержка» ведёт сюда.</i>"
                 if support_mode() == MODE_CONTACT
                 else "<i>Чтобы бот начал уводить людей туда, включи режим «👤 Аккаунт».</i>")
    await msg.reply_text(
        f"✅ <b>Аккаунт поддержки: @{name}</b>\n\n{mode_line}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔗 Открыть @{name}", url=support_url())],
            [InlineKeyboardButton("💬 К настройкам поддержки", callback_data="support_settings")],
        ]))
