from __future__ import annotations

import asyncio

from aiogram.types import BotCommand
from config import ADMIN_ID
from handlers.admin import router as admin_router
from handlers.cancel import router as cancel_router
from handlers.start import router as start_router
from loader import bot, dp
from storage import clear_update_state, load_update_state
from xui import router as xui_router


async def setup_commands() -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
        ]
    )


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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
