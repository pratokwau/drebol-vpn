"""Поддержка со стороны админа.

Главное, чего не хватало: контекста и скорости. Теперь в карточке сразу видно,
кто пишет — что у него с подпиской, сколько он заплатил, сколько уже ждёт
ответа и о чём вопрос. Отвечать можно готовым шаблоном в одно касание,
а решённые переписки закрываются и не мозолят глаза.
"""

from datetime import datetime
from html import escape

from telegram.ext import ContextTypes
from config import load_config, save_config
from database import (
    get_ticket_users, get_support_messages, get_user_info, add_support_message,
    mark_ticket_read, count_support_files, get_support_files,
    get_ticket, ticket_counts, ticket_closed, ticket_answered, user_payment_total,
)
from keyboards import ticket_list_keyboard, ticket_view_keyboard, cancel_admin
from states import AWAITING_ADMIN_REPLY

SEP = "━" * 14

# Заготовки ответов. Админ правит их в «⚡ Шаблоны» — там же и добавляет свои.
DEFAULT_QUICK = [
    "Обновите подписку в приложении: откройте её и потяните список вниз — "
    "сервера обновятся, и всё заработает.",
    "Проверил — у вас занят лимит устройств. Отключите лишнее в разделе "
    "«📱 Мои устройства», слот освободится сразу.",
    "Оплата дошла, подписка продлена. Проверьте, пожалуйста, и напишите, если что-то не так.",
    "Попробуйте выбрать другой сервер в приложении — скорость сильно зависит от точки подключения.",
]


def quick_replies() -> list:
    saved = load_config().get("support_quick")
    return list(saved) if isinstance(saved, list) and saved else list(DEFAULT_QUICK)


def save_quick(items: list):
    cfg = load_config()
    cfg["support_quick"] = items
    save_config(cfg)


def _fmt_time(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        today = datetime.now().date()
        return dt.strftime("%H:%M") if dt.date() == today else dt.strftime("%d.%m · %H:%M")
    except Exception:
        return raw


def fmt_wait(seconds) -> str:
    """Сколько человек ждёт ответа — коротко, для списка."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ""
    if seconds < 3600:
        return f"{seconds // 60} мин"
    if seconds < 86400:
        return f"{seconds // 3600} ч"
    return f"{seconds // 86400} дн"


STATUS_MARK = {"open": "🔴", "answered": "✅", "closed": "🗂"}
STATUS_WORD = {"open": "ждёт ответа", "answered": "мы ответили", "closed": "закрыт"}


async def handle_ticket_list(query, page: int = 1, status: str = "open"):
    from handlers.support import topic_label
    rows, total_pages = await get_ticket_users(page, status)
    counts = await ticket_counts()

    title = ("🎫 <b>Тикеты</b>\n"
             f"🔴 Открытых: <b>{counts['open']}</b> · "
             f"✅ Отвеченных: <b>{counts['answered']}</b> · "
             f"🗂 Закрытых: <b>{counts['closed']}</b>")

    if not rows:
        empty = {"open": "Открытых обращений нет — всё разобрано.",
                 "answered": "Отвеченных переписок пока нет.",
                 "closed": "Закрытых переписок пока нет."}.get(status, "Обращений пока нет.")
        await query.edit_message_text(
            f"{title}\n\n{empty}",
            parse_mode="HTML",
            reply_markup=ticket_list_keyboard([], 1, 1, status),
        )
        return

    lines = [title, "", SEP, ""]
    for i, row in enumerate(rows, 1):
        (user_id, first_name, username, _total, unread, last_time,
         last_text, last_from_admin, t_status, topic, waiting) = row
        name = escape(str(first_name or user_id))
        uname = f" @{escape(username)}" if username else ""
        preview = escape((last_text or "").replace("\n", " ")[:60])
        who = "🛡" if last_from_admin else "👤"
        wait = fmt_wait(waiting)
        head = f"{i}. {STATUS_MARK.get(t_status, '💬')} <b>{name}</b>{uname}"
        if unread:
            head += f" · <b>+{unread}</b>"
        lines.append(head)
        meta = f"   📌 {topic_label(topic)}"
        if wait and t_status == "open":
            meta += f" · ⏳ ждёт <b>{wait}</b>"
        else:
            meta += f" · 🕐 {_fmt_time(last_time)}"
        lines.append(meta)
        lines.append(f"   {who} <i>{preview}</i>")
        lines.append("")

    lines.append(SEP)
    lines.append("<i>Дольше всех ждущие — сверху.</i>")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=ticket_list_keyboard(rows, page, total_pages, status),
    )


async def _user_context(user_id: int) -> str:
    """Кто пишет: подписка, деньги, устройства. Чтобы не бегать в профиль."""
    from paidsub.storage import get_paid_sub_by_tg_id, parse_sub_date
    from paidsub.time_parser import fmt_duration_precise
    row = await get_paid_sub_by_tg_id(user_id)
    lines = []
    if not row:
        lines.append("🚫 Подписки нет")
    else:
        status = row[11] if len(row) > 11 else "active"
        renewed = row[12] if len(row) > 12 else 0
        limit_hwid = int(row[8] or 0)
        extra = int(row[18] or 0) if len(row) > 18 else 0
        plan = "⭐️ Премиум" if renewed else "🆓 Триал"
        mark = {"active": "🟢", "renewal": "🟡", "expired": "🔴"}.get(status, "⚪")
        end = parse_sub_date(row[6])
        left = ""
        if end:
            secs = int((end - datetime.now()).total_seconds())
            left = (f" · осталось {fmt_duration_precise(secs)}" if secs > 0
                    else " · срок вышел")
        lines.append(f"{plan} · {mark} {status}{left}")
        lines.append(f"📅 До: {row[6]}")
        dev = f"🖥 Устройств: {limit_hwid or 'без лимита'}"
        if extra:
            dev += f" (докуплено {extra})"
        lines.append(f"{dev} · 🌐 IP: {row[7] or 'без лимита'}")

    total, count = await user_payment_total(user_id)
    if count:
        lines.append(f"💰 Оплат: {count} на {total} ₽")
    else:
        lines.append("💰 Оплат не было")
    return "\n".join(lines)


async def handle_ticket_view(query, user_id: int, page: int = 1):
    from handlers.support import topic_label
    await mark_ticket_read(user_id)

    user_info = await get_user_info(user_id)
    first_name = escape(str(user_info[1] if user_info else user_id))
    username = f" @{escape(user_info[2])}" if user_info and user_info[2] else ""

    msgs, total_pages = await get_support_messages(user_id, page)
    has_files = (await count_support_files(user_id)) > 0
    ticket = await get_ticket(user_id)
    context_block = await _user_context(user_id)

    status_line = f"{STATUS_MARK.get(ticket['status'], '💬')} {STATUS_WORD.get(ticket['status'], '')}"
    wait = fmt_wait(ticket["waiting"])
    if wait and ticket["status"] == "open":
        status_line += f" · ⏳ <b>{wait}</b>"

    head = (
        f"🎫 <b>{first_name}</b>{username}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"📌 {topic_label(ticket['topic'])} · {status_line}"
    )

    bubbles = []
    for row in msgs:
        text, from_admin, created_at = row[0], row[1], row[2]
        file_id = row[3] if len(row) > 3 else None
        file_type = row[4] if len(row) > 4 else None
        who = "🛡 <b>Поддержка</b>" if from_admin else f"👤 <b>{first_name}</b>"
        mark = ""
        if file_id:
            mark = " 🖼" if file_type == "photo" else " 📎"
        body = escape(text or "") or "<i>файл</i>"
        bubbles.append(f"{who} · <i>{_fmt_time(created_at)}</i>{mark}\n{body}")

    text = (f"{head}\n\n{SEP}\n\n{context_block}\n\n{SEP}\n\n"
            + "\n\n".join(bubbles))
    if total_pages > 1:
        text += f"\n\n<i>Страница {page} из {total_pages}</i>"

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=ticket_view_keyboard(user_id, page, total_pages, has_files,
                                          closed=ticket["status"] == "closed"),
    )


async def handle_ticket_reply_start(query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    context.user_data["state"] = AWAITING_ADMIN_REPLY
    context.user_data["reply_to"] = user_id
    user_info = await get_user_info(user_id)
    name = escape(str(user_info[1] if user_info else user_id))
    await query.edit_message_text(
        f"✏️ <b>Ответ · {name}</b>\n\n"
        "Напишите ответ или отправьте файл — уйдёт человеку сразу.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Шаблоны", callback_data=f"ticket_quick:{user_id}")],
            [InlineKeyboardButton("◀️ К переписке", callback_data=f"ticket_view:{user_id}:1")],
        ]),
    )


async def handle_ticket_quick(query, user_id: int):
    """Список заготовок: ответ в одно касание."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    items = quick_replies()
    rows = []
    for i, item in enumerate(items):
        label = item if len(item) <= 40 else item[:40] + "…"
        rows.append([InlineKeyboardButton(f"⚡ {label}", callback_data=f"ticket_send:{user_id}:{i}")])
    rows.append([InlineKeyboardButton("⚙️ Изменить шаблоны", callback_data="quick_menu")])
    rows.append([InlineKeyboardButton("◀️ К переписке", callback_data=f"ticket_view:{user_id}:1")])
    await query.edit_message_text(
        "⚡ <b>Быстрый ответ</b>\n\n"
        "Нажмите — текст уйдёт человеку сразу и попадёт в переписку.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_ticket_send_quick(query, user_id: int, index: int, context):
    items = quick_replies()
    if index >= len(items):
        await query.answer("Шаблон не найден", show_alert=True)
        return
    text = items[index]
    await add_support_message(user_id, text, from_admin=True)
    await ticket_answered(user_id)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🛡 <b>Ответ поддержки</b>\n\n{escape(text)}",
            parse_mode="HTML",
        )
        await query.answer("Отправлено")
    except Exception:
        await query.answer("Сохранено, но не доставлено: юзер заблокировал бота",
                           show_alert=True)
    await handle_ticket_view(query, user_id, 1)


async def handle_ticket_close(query, user_id: int, context):
    """Закрывает переписку и говорит об этом человеку."""
    await ticket_closed(user_id)
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ <b>Вопрос закрыт</b>\nЕсли что — пишите снова.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Поддержка", callback_data="support_open")],
            ]),
        )
    except Exception:
        pass
    await handle_ticket_view(query, user_id, 1)


async def handle_quick_menu(query):
    """Управление шаблонами."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    items = quick_replies()
    lines = ["⚡ <b>Шаблоны ответов</b>", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {escape(item)}")
        lines.append("")
    lines.append(SEP)
    lines.append("<i>Шаблон уходит человеку одним нажатием из переписки.</i>")
    rows = [[InlineKeyboardButton(f"🗑 Удалить {i + 1}", callback_data=f"quick_del:{i}")]
            for i in range(len(items))]
    rows.append([InlineKeyboardButton("➕ Добавить шаблон", callback_data="quick_add")])
    rows.append([InlineKeyboardButton("◀️ К тикетам", callback_data="ticket_list:1")])
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(rows))


async def handle_quick_add(query, context):
    from states import AWAITING_QUICK_REPLY
    context.user_data["state"] = AWAITING_QUICK_REPLY
    await query.edit_message_text(
        "➕ <b>Новый шаблон</b>\n\n"
        "Пришлите текст ответа одним сообщением.",
        parse_mode="HTML",
        reply_markup=cancel_admin(),
    )


async def handle_quick_del(query, index: int):
    items = quick_replies()
    if 0 <= index < len(items):
        items.pop(index)
        save_quick(items)
    await handle_quick_menu(query)


async def handle_ticket_files(query, user_id: int):
    files = await get_support_files(user_id)
    if not files:
        await query.answer("Файлов нет.", show_alert=True)
        return
    user_info = await get_user_info(user_id)
    first_name = user_info[1] if user_info else str(user_id)
    await query.answer(f"Отправляю файлы: {len(files)}")
    for file_id, file_type, from_admin, created_at in files:
        who = "🛡 Поддержка" if from_admin else f"👤 {first_name}"
        caption = f"{who} · {_fmt_time(created_at)}"
        try:
            if file_type == "photo":
                await query.message.reply_photo(file_id, caption=caption)
            else:
                await query.message.reply_document(file_id, caption=caption)
        except Exception:
            pass
