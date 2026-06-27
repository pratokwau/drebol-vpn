from __future__ import annotations

from aiogram.enums import ParseMode

from xui.api import api_get_inbounds
from xui.keyboards import clients_kb, inbounds_kb
from xui.utils import format_bytes


def inbound_text(inbound: dict) -> str:
    protocol = str(inbound.get("protocol", "?")).upper()
    port = inbound.get("port", "?")
    remark = inbound.get("remark") or f"{protocol}:{port}"
    clients = inbound.get("settings", {}).get("clients", [])
    total_up = sum(int((c.get("clientStats") or {}).get("up", 0)) for c in clients)
    total_down = sum(int((c.get("clientStats") or {}).get("down", 0)) for c in clients)
    return (
        f"📡 <b>{remark}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔌 Протокол: <b>{protocol}</b>\n"
        f"🌐 Порт: <b>{port}</b>\n"
        f"👥 Клиентов: <b>{len(clients)}</b>\n"
        f"📤 Отправлено: <b>{format_bytes(total_up)}</b>\n"
        f"📥 Получено: <b>{format_bytes(total_down)}</b>\n\n"
        f"Выберите клиента:"
    )


async def render_inbounds(message_or_call):
    inbounds, err = await api_get_inbounds()
    if not inbounds:
        if hasattr(message_or_call, "edit_text"):
            return await message_or_call.edit_text(f"❌ Не удалось загрузить инбаунды.\n<code>{err}</code>", parse_mode=ParseMode.HTML)
        return await message_or_call.answer(f"❌ Не удалось загрузить инбаунды.\n<code>{err}</code>", parse_mode=ParseMode.HTML)
    text = (
        f"🖥 <b>3X-UI Панель</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📡 Инбаундов: <b>{len(inbounds)}</b>\n\n"
        f"Выберите инбаунд:"
    )
    if hasattr(message_or_call, "edit_text") and getattr(getattr(message_or_call, "from_user", None), "is_bot", False):
        await message_or_call.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=inbounds_kb(inbounds))
    else:
        await message_or_call.answer(text, parse_mode=ParseMode.HTML, reply_markup=inbounds_kb(inbounds))


async def render_inbound(call, inbound: dict):
    await call.message.edit_text(
        inbound_text(inbound),
        parse_mode=ParseMode.HTML,
        reply_markup=clients_kb(inbound),
    )
