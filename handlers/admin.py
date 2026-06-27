from __future__ import annotations

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from config import ADMIN_ID
from updater import apply_update, update_available
from xui.keyboards import admin_menu_kb
from xui.utils import is_admin


router = Router()


def _admin_kb() -> types.InlineKeyboardMarkup:
    configured = update_available()
    rows = [
        [types.InlineKeyboardButton(text="🔄 Проверить обновление", callback_data="app_update_check")],
        [types.InlineKeyboardButton(text="⚙️ XUI", callback_data="xui_settings")],
    ]
    if configured:
        rows[0] = [types.InlineKeyboardButton(text="⬆️ Обновить бота", callback_data="app_update_apply")]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    status = "есть обновление" if update_available() else "обновлений нет"
    await message.answer(
        f"⚙️ <b>Админ-панель</b>\n\n"
        f"Статус обновления: <b>{status}</b>\n"
        f"Пользователь: <code>{message.from_user.id}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=_admin_kb(),
    )


@router.callback_query(F.data == "app_update_check")
async def cb_update_check(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    if update_available():
        await call.message.edit_text(
            "📦 <b>Найдено обновление</b>\n\n"
            "Нажми кнопку ниже, чтобы скачать апдейт и перезапустить бота.",
            parse_mode=ParseMode.HTML,
            reply_markup=_admin_kb(),
        )
    else:
        await call.message.edit_text(
            "✅ <b>Обновлений нет</b>\n\n"
            "Локальная версия совпадает с GitHub.",
            parse_mode=ParseMode.HTML,
            reply_markup=_admin_kb(),
        )
    await call.answer()


@router.callback_query(F.data == "app_update_apply")
async def cb_update_apply(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)

    await call.message.edit_text(
        "⏳ <b>Обновляю бота...</b>\n\n"
        "Сейчас я скачиваю свежую версию и перезапускаю сервис.",
        parse_mode=ParseMode.HTML,
    )
    ok, msg = apply_update()
    if ok:
        await call.message.edit_text(
            "✅ <b>Обновление установлено</b>\n\n"
            "Бот перезапущен. Новая версия уже должна быть активна.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await call.message.edit_text(
            f"❌ <b>Не удалось обновиться</b>\n\n<code>{msg}</code>",
            parse_mode=ParseMode.HTML,
        )
    await call.answer()
