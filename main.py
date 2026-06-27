from __future__ import annotations

import asyncio

from aiogram import BotCommand, BotCommandScopeChat

from config import ADMIN_ID
from handlers.cancel import router as cancel_router
from handlers.start import router as start_router
from loader import bot, dp
from xui import router as xui_router


async def setup_commands() -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="cancel", description="Отмена"),
        ]
    )
    if ADMIN_ID:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="cancel", description="Отмена"),
                BotCommand(command="adminxui", description="Панель 3X-UI"),
            ],
            scope=BotCommandScopeChat(chat_id=ADMIN_ID),
        )


async def main() -> None:
    dp.include_router(cancel_router)
    dp.include_router(start_router)
    dp.include_router(xui_router)
    await setup_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
