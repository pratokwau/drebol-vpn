from __future__ import annotations

import asyncio

from aiogram.types import BotCommand
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import ADMIN_ID
from handlers.admin import router as admin_router
from handlers.cancel import router as cancel_router
from handlers.start import router as start_router
from loader import bot, dp
from storage import clear_update_state, load_update_state
from updater import get_remote_head, get_local_head
from xui import router as xui_router


async def setup_commands() -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
        ]
    )


def _update_notice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬆️ Обновиться", callback_data="app_update_apply")],
            [InlineKeyboardButton(text="🔄 Проверить обновление", callback_data="app_update_check")],
        ]
    )


async def _notify_about_updates() -> None:
    while True:
        try:
            local_head = get_local_head()
            remote_head = get_remote_head()
            if local_head and remote_head and local_head != remote_head:
                state = load_update_state()
                if state.get("notified_remote_head") != remote_head:
                    await bot.send_message(
                        ADMIN_ID,
                        "📦 <b>Доступно новое обновление</b>\n\n"
                        f"Локальная версия: <code>{local_head[:8] or 'unknown'}</code>\n"
                        f"Новая версия: <code>{remote_head[:8]}</code>\n\n"
                        "Нажми кнопку ниже, чтобы обновить бота.",
                        parse_mode="HTML",
                        reply_markup=_update_notice_kb(),
                    )
                    state["notified_remote_head"] = remote_head
                    state["status"] = state.get("status", "idle")
                    from storage import save_update_state

                    save_update_state(state)
        except Exception:
            pass
        await asyncio.sleep(60)


async def main() -> None:
    dp.include_router(cancel_router)
    dp.include_router(start_router)
    dp.include_router(admin_router)
    dp.include_router(xui_router)
    await setup_commands()

    async def notify_update_success() -> None:
        state = load_update_state()
        if state.get("status") != "pending_success":
            return
        chat_id = int(state.get("chat_id") or ADMIN_ID or 0)
        if not chat_id:
            return
        await asyncio.sleep(2)
        try:
            await bot.send_message(
                chat_id,
                "✅ <b>Обновление применено успешно.</b>\n\n"
                "Новая версия бота запущена и готова к работе.",
            )
        finally:
            clear_update_state()

    asyncio.create_task(notify_update_success())
    asyncio.create_task(_notify_about_updates())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
