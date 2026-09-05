from datetime import datetime
from database import get_support_messages, count_support_files, get_support_files
from keyboards import support_keyboard


def _fmt_time(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return raw


def _status_line(msgs: list) -> str:
    if not msgs:
        return ""
    last_from_admin = msgs[-1][1]
    if last_from_admin:
        return "✅ <i>Поддержка ответила.</i>"
    return "🟢 <i>Сообщение отправлено, ожидайте ответа.</i>"


def _build_text(msgs: list, page: int, total_pages: int) -> str:
    header = f"💬 <b>Поддержка</b> — стр. {page}/{total_pages}"
    if not msgs:
        return (
            "💬 <b>Поддержка</b>\n\n"
            "Здесь вы можете задать любой вопрос — мы ответим как можно скорее.\n\n"
            "✍️ Просто напишите сообщение или отправьте файл/фото ниже."
        )
    lines = [header]
    status_line = _status_line(msgs)
    if status_line:
        lines.append(status_line)
    lines.append("─" * 20)
    for row in msgs:
        text, from_admin, created_at = row[0], row[1], row[2]
        file_id = row[3] if len(row) > 3 else None
        file_type = row[4] if len(row) > 4 else None
        who = "🛡 <b>Поддержка</b>" if from_admin else "👤 <b>Вы</b>"
        file_mark = ""
        if file_id:
            file_mark = " 🖼" if file_type == "photo" else " 📎"
        lines.append(f"{who} · 🕐 {_fmt_time(created_at)}{file_mark}\n{text}")
    lines.append("\n✍️ Напишите сообщение или отправьте файл/фото:")
    return "\n\n".join(lines)


async def open_support(query, user_id: int, page: int | None = None):
    _, total_pages = await get_support_messages(user_id, 1)
    if page is None:
        page = total_pages
    msgs, total_pages = await get_support_messages(user_id, page)
    has_files = (await count_support_files(user_id)) > 0
    text = _build_text(msgs, page, total_pages)
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=support_keyboard(page, total_pages, has_files),
    )


async def handle_support_files(query, user_id: int):
    files = await get_support_files(user_id)
    if not files:
        await query.answer("Файлов нет.", show_alert=True)
        return
    await query.answer(f"Отправляю {len(files)} файл(ов)...")
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
