from __future__ import annotations

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from xui.paid_storage import has_paid_subscription
from xui.storage import get_vpn_user, user_settings_ready
from xui.utils import is_admin
from xui.vpn import _render_vpn
from handlers.admin import cmd_admin
from xui.admin import cmd_adminsub
from xui.paid_subscriptions import cmd_adminpaysub, cmd_sub


router = Router()


def _start_kb(*, has_admin_sub: bool, has_paid_sub: bool, is_admin_user: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_admin_sub:
        rows.append([InlineKeyboardButton(text="🔐 Мой VPN", callback_data="start_vpn")])
    if has_paid_sub:
        rows.append([InlineKeyboardButton(text="💳 Моя подписка", callback_data="start_sub")])
    if not has_admin_sub and not has_paid_sub:
        rows.append([InlineKeyboardButton(text="💳 Запросить триал", callback_data="start_sub")])
    if is_admin_user:
        rows.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="start_admin")])
        rows.append([
            InlineKeyboardButton(text="📡 Админская подписка", callback_data="start_adminsub"),
            InlineKeyboardButton(text="💳 Платные подписки", callback_data="start_adminpaysub"),
        ])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="start_refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_start(message: types.Message) -> None:
    user_id = message.from_user.id
    vpn_user = get_vpn_user(user_id)
    has_admin_sub = bool(vpn_user and user_settings_ready(vpn_user) and not vpn_user.get("admin_disabled"))
    has_paid_sub = has_paid_subscription(user_id)
    is_admin_user = is_admin(user_id)
    text = (
        "👋 <b>Добро пожаловать в Drebol VPN</b>\n\n"
        "Здесь можно открыть свой VPN, посмотреть подписку или зайти в админ-раздел.\n\n"
        "Выберите действие кнопкой ниже:"
    )
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_start_kb(
            has_admin_sub=has_admin_sub,
            has_paid_sub=has_paid_sub,
            is_admin_user=is_admin_user,
        ),
    )


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await _render_start(message)


@router.callback_query(F.data == "start_refresh")
async def cb_start_refresh(call: types.CallbackQuery):
    await call.answer()
    await _render_start(call.message)


@router.callback_query(F.data == "start_vpn")
async def cb_start_vpn(call: types.CallbackQuery):
    user_data = get_vpn_user(call.from_user.id)
    if not user_data or not user_settings_ready(user_data):
        return await call.answer("⛔ У вас пока нет доступа к VPN", show_alert=True)
    if user_data.get("admin_disabled"):
        return await call.answer("⛔ Доступ временно отключён", show_alert=True)
    await call.answer()
    await _render_vpn(call.message, user_data)


@router.callback_query(F.data == "start_sub")
async def cb_start_sub(call: types.CallbackQuery):
    await call.answer()
    await cmd_sub(call.message)


@router.callback_query(F.data == "start_admin")
async def cb_start_admin(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("⛔ Доступ запрещён", show_alert=True)
    await call.answer()
    await cmd_admin(call.message)


@router.callback_query(F.data == "start_adminsub")
async def cb_start_adminsub(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("⛔ Доступ запрещён", show_alert=True)
    await call.answer()
    await cmd_adminsub(call.message)


@router.callback_query(F.data == "start_adminpaysub")
async def cb_start_adminpaysub(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("⛔ Доступ запрещён", show_alert=True)
    await call.answer()
    await cmd_adminpaysub(call.message)
