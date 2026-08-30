from datetime import datetime
from database import get_support_messages
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
            "✍️ Просто напишите сообщение ниже."
        )
    lines = [header]
    status_line = _status_line(msgs)
    if status_line:
        lines.append(status_line)
    lines.append("─" * 20)
    for text, from_admin, created_at in msgs:
        who = "🛡 <b>Поддержка</b>" if from_admin else "👤 <b>Вы</b>"
        lines.append(f"{who} · 🕐 {_fmt_time(created_at)}\n{text}")
    lines.append("\n✍️ Напишите сообщение ниже:")
    return "\n\n".join(lines)


async def open_support(query, user_id: int, page: int | None = None):
    # определяем число страниц, чтобы по умолчанию открыть последнюю (свежие сообщения)
    _, total_pages = await get_support_messages(user_id, 1)
    if page is None:
        page = total_pages
    msgs, total_pages = await get_support_messages(user_id, page)
    text = _build_text(msgs, page, total_pages)
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=support_keyboard(page, total_pages),
    )
