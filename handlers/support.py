from datetime import datetime
from database import get_support_messages
from keyboards import support_keyboard


def _fmt_time(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return raw


def _build_text(msgs: list, page: int, total_pages: int) -> str:
    header = f"💬 <b>Поддержка</b> — стр. {page}/{total_pages}\n"
    if not msgs:
        return header + "\nПока обращений нет.\n\n✍️ Напишите сообщение — мы ответим как можно скорее."
    lines = [header]
    for text, from_admin, created_at in msgs:
        who = "🛡 <b>Поддержка</b>" if from_admin else "👤 <b>Вы</b>"
        lines.append(f"{who}: {text}\n🕐 {_fmt_time(created_at)}")
    lines.append("\n✍️ Напишите сообщение ниже:")
    return "\n\n".join(lines)


async def open_support(query, user_id: int, page: int = 1):
    msgs, total_pages = await get_support_messages(user_id, page)
    text = _build_text(msgs, page, total_pages)
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=support_keyboard(page, total_pages),
    )
