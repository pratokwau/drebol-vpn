from __future__ import annotations

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from updater import apply_update, request_restart, update_available
from storage import load_xui_settings, save_xui_settings, save_update_state
from xui.keyboards import settings_kb
from xui.utils import is_admin


router = Router()


class XuiSettings(StatesGroup):
    url = State()
    token = State()


def _admin_kb() -> types.InlineKeyboardMarkup:
    configured = update_available()
    rows = [
        [types.InlineKeyboardButton(text="🔄 Проверить обновление", callback_data="app_update_check")],
        [types.InlineKeyboardButton(text="⚙️ Настроить XUI", callback_data="admin_xui_settings")],
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


@router.callback_query(F.data == "admin_xui_settings")
async def cb_admin_xui_settings(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    data = load_xui_settings()
    url = data.get("XUI_URL") or "не задан"
    token = data.get("XUI_TOKEN") or "не задан"
    await call.message.edit_text(
        "⚙️ <b>Настройки XUI</b>\n\n"
        f"URL: <code>{url}</code>\n"
        f"Токен: <code>{token}</code>\n\n"
        "Нажми кнопку ниже, чтобы изменить значение.",
        parse_mode=ParseMode.HTML,
        reply_markup=settings_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "xui_settings")
async def cb_xui_settings(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    data = load_xui_settings()
    url = data.get("XUI_URL") or "не задан"
    token = data.get("XUI_TOKEN") or "не задан"
    await call.message.edit_text(
        "⚙️ <b>Настройки XUI</b>\n\n"
        f"URL: <code>{url}</code>\n"
        f"Токен: <code>{token}</code>\n\n"
        "Нажми кнопку ниже, чтобы изменить значение.",
        parse_mode=ParseMode.HTML,
        reply_markup=settings_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "xui_set_url")
async def cb_xui_set_url(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(XuiSettings.url)
    await call.message.edit_text(
        "Отправь <b>URL панели 3x-ui</b> следующим сообщением.\n\n"
        "Пример: <code>https://example.com</code>\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data == "xui_set_token")
async def cb_xui_set_token(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.set_state(XuiSettings.token)
    await call.message.edit_text(
        "Отправь <b>API токен</b> панели следующим сообщением.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data == "xui_back")
async def cb_xui_back(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await state.clear()
    data = load_xui_settings()
    url = data.get("XUI_URL") or "не задан"
    token = data.get("XUI_TOKEN") or "не задан"
    await call.message.edit_text(
        "⚙️ <b>Настройки XUI</b>\n\n"
        f"URL: <code>{url}</code>\n"
        f"Токен: <code>{token}</code>\n\n"
        "Нажми кнопку ниже, чтобы изменить значение.",
        parse_mode=ParseMode.HTML,
        reply_markup=settings_kb(),
    )
    await call.answer()


@router.message(XuiSettings.url)
async def xui_url_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    url = (message.text or "").strip()
    if not url:
        await message.answer("URL не может быть пустым.")
        return
    data = load_xui_settings()
    data["XUI_URL"] = url
    save_xui_settings(data)
    await state.clear()
    await message.answer("✅ URL панели сохранён.")


@router.message(XuiSettings.token)
async def xui_token_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    token = (message.text or "").strip()
    if not token:
        await message.answer("Токен не может быть пустым.")
        return
    data = load_xui_settings()
    data["XUI_TOKEN"] = token
    save_xui_settings(data)
    await state.clear()
    await message.answer("✅ API токен сохранён.")


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
        "Сейчас я скачиваю свежую версию и начинаю перезагрузку.",
        parse_mode=ParseMode.HTML,
    )
    ok, msg = apply_update()
    if ok:
        save_update_state(
            {
                "chat_id": call.message.chat.id,
                "admin_id": call.from_user.id,
                "status": "pending_success",
            }
        )
        await call.message.edit_text(
            "🔄 <b>Обновление установлено</b>\n\n"
            "Сейчас бот завершает работу и перезапускается. После старта я пришлю подтверждение.",
            parse_mode=ParseMode.HTML,
        )
        request_restart()
    else:
        await call.message.edit_text(
            f"❌ <b>Не удалось обновиться</b>\n\n<code>{msg}</code>",
            parse_mode=ParseMode.HTML,
        )
    await call.answer()
