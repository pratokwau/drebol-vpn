from __future__ import annotations

import asyncio
from datetime import datetime

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from loader import bot
from xui.api import api_add_client, api_get_client, api_get_inbounds, api_del_client_by_email, api_update_client
from xui.helpers import parse_clients
from xui.keyboards import flow_choice_kb
from xui.storage import (
    DEFAULT_MAX_DEVICES,
    add_device_to_user,
    create_user,
    delete_user_completely,
    get_tg_id_by_client,
    get_vpn_user,
    load_vpn_users,
    remove_device_from_user,
    save_vpn_users,
    set_admin_disabled,
    set_admin_disabled_key,
    set_client_note,
    set_user_note,
    set_user_note_key,
    set_user_vpn_access,
    set_user_vpn_access_key,
    rekey_user,
)
from xui.states import XuiBindTg, XuiNoteEdit
from xui.utils import is_admin
from xui.views import _refresh_client_view, _show_user_menu, render_inbound, render_inbounds


router = Router()


class XuiAddClient(StatesGroup):
    tg_id = State()
    max_devices = State()
    limit_gb = State()
    expiry = State()
    flow = State()


def _default_or_value(raw: str | None, default, parser):
    text = (raw or "").strip()
    if not text or text == "-":
        return default
    return parser(text)


def _parse_expiry_date(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return 2523456000000
    dt = datetime.strptime(text, "%d.%m.%Y")
    return int(dt.timestamp() * 1000)


def _decode_user_payload(payload: dict) -> tuple[str | None, int]:
    user_key = payload.get("user_key")
    ib_id = int(payload.get("ib_id", 0) or 0)
    return (str(user_key) if user_key else None, ib_id)


def _find_device_by_hash(client_hash: str) -> dict:
    from xui.utils import _cache

    return dict(_cache.get(client_hash, {}) or {})


def _find_owner_key(ib_id: int, email: str) -> str:
    owner_id = get_tg_id_by_client(ib_id, email)
    if owner_id is not None:
        return str(owner_id)
    for user_key, info in load_vpn_users().items():
        for device in info.get("devices", []):
            if device.get("ib_id") == ib_id and device.get("email") == email:
                return str(user_key)
    return ""


async def _refresh_user_menu(message_or_call, user_key: str, ib_id: int):
    await _show_user_menu(message_or_call, user_key, ib_id, edit=True)


async def _refresh_client_card(call: types.CallbackQuery, client_hash: str):
    await _refresh_client_view(call, client_hash)
@router.message(Command("adminxui"))
async def cmd_adminxui(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await render_inbounds(message, show_settings=False)


@router.callback_query(F.data == "xui_inbounds")
async def cb_inbounds(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await call.answer()
    await render_inbounds(call.message, show_settings=False)


@router.callback_query(F.data.startswith("xui_ib_"))
async def cb_inbound(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    ib_hash = call.data[len("xui_ib_") :]
    # Пока используем кэш только для id, чтобы не усложнять стартовый каркас.
    if len(ib_hash) != 8:
        return await call.answer("Некорректный инбаунд", show_alert=True)
    from xui.utils import _cache

    info = _cache.get(ib_hash, {})
    inbound_id = info.get("id")
    if inbound_id is None:
        return await call.answer("Инбаунд не найден", show_alert=True)
    inbounds, err = await api_get_inbounds()
    inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)
    if not inbound:
        return await call.answer(f"Инбаунд не найден: {err}", show_alert=True)
    await render_inbound(call, inbound)
    await call.answer()


@router.callback_query(F.data.startswith("xui_cl_"))
async def cb_client(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await _refresh_client_view(call, call.data[len("xui_cl_"):])
    await call.answer()


@router.callback_query(F.data.startswith("xui_usr_"))
async def cb_user(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_usr_"):], {})
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    await _show_user_menu(call.message, str(user_key), int(ib_id or 0), edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("xui_adduser_"))
async def cb_add_user(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_adduser_"):], {})
    ib_id = payload.get("id")
    if not ib_id:
        return await call.answer("Инбаунд не найден", show_alert=True)
    await state.update_data(xui_ib_id=int(ib_id))
    await state.set_state(XuiAddClient.tg_id)
    await call.message.edit_text(
        "Введите <b>TG ID</b> пользователя.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(XuiAddClient.tg_id)
async def add_user_tg_id(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой TG ID.\n\nДля выхода введите /cancel")
        return
    await state.update_data(xui_tg_id=int(raw))
    await state.set_state(XuiAddClient.max_devices)
    await message.answer(
        "Введите лимит устройств или отправьте <code>-</code> для значения по умолчанию.\n"
        f"По умолчанию: <b>{DEFAULT_MAX_DEVICES}</b>.\n\n"
        "Для выхода введите /cancel"
    )


@router.message(XuiAddClient.max_devices)
async def add_user_max_devices(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw and raw != "-":
        try:
            max_devices = max(1, int(raw))
        except ValueError:
            await message.answer("Введите число или <code>-</code>.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
            return
    else:
        max_devices = DEFAULT_MAX_DEVICES
    await state.update_data(xui_max_devices=max_devices)
    await state.set_state(XuiAddClient.limit_gb)
    await message.answer(
        "Введите лимит ГБ или отправьте <code>-</code> для бесконечности.\n"
        "Пример: <code>100</code>\n\n"
        "Для выхода введите /cancel"
    , parse_mode=ParseMode.HTML)


@router.message(XuiAddClient.limit_gb)
async def add_user_limit_gb(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw and raw != "-":
        try:
            limit_gb = float(raw)
        except ValueError:
            await message.answer("Введите число или <code>-</code>.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
            return
    else:
        limit_gb = 0.0
    await state.update_data(xui_limit_gb=limit_gb)
    await state.set_state(XuiAddClient.expiry)
    await message.answer(
        "Введите дату окончания в формате <code>дд.мм.гггг</code> или отправьте <code>-</code> для дефолта.\n"
        "Дефолт: <b>12.12.2050</b>.\n\n"
        "Для выхода введите /cancel"
        , parse_mode=ParseMode.HTML
    )


@router.message(XuiAddClient.expiry)
async def add_user_expiry(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if raw and raw != "-":
        try:
            expiry_time = _parse_expiry_date(raw)
        except ValueError:
            await message.answer(
                "Нужен формат <code>дд.мм.гггг</code> или <code>-</code>.\n\nДля выхода введите /cancel",
                parse_mode=ParseMode.HTML,
            )
            return
    else:
        expiry_time = 2523456000000

    data = await state.get_data()
    tg_id = int(data["xui_tg_id"])
    max_devices = int(data.get("xui_max_devices", DEFAULT_MAX_DEVICES))
    limit_gb = float(data.get("xui_limit_gb", 0))
    ib_id = int(data.get("xui_ib_id", 0))

    result, client_uuid = await api_add_client(
        ib_id,
        f"{tg_id}_{ib_id}",
        0,
        limit_gb,
        "",
        expiry_time_ms=expiry_time,
    )
    if not result.get("success"):
        await message.answer(f"❌ Не удалось добавить пользователя.\n<code>{result.get('msg', '')}</code>", parse_mode=ParseMode.HTML)
        return

    create_user(tg_id, max_devices=max_devices)
    add_device_to_user(tg_id, ib_id, client_uuid, f"{tg_id}_{ib_id}")
    set_user_vpn_access(tg_id, True)

    try:
        await bot.send_message(
            tg_id,
            "✅ <b>Вам был добавлен VPN.</b>\n\n"
            "Теперь в /start доступна команда /vpn для управления устройством.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await state.clear()
    await message.answer("✅ Пользователь добавлен и уведомление отправлено.")


@router.callback_query(F.data.startswith("xui_unblk_"))
async def cb_user_unblock(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_unblk_"):], {})
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    if user_key.isdigit():
        set_admin_disabled(int(user_key), False)
    await _show_user_menu(call.message, user_key, ib_id, edit=True)
    await call.answer("Пользователь разблокирован")


@router.callback_query(F.data.startswith("xui_ublk_"))
async def cb_user_block(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_ublk_"):], {})
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    if user_key.isdigit():
        set_admin_disabled(int(user_key), True)
    await _show_user_menu(call.message, user_key, ib_id, edit=True)
    await call.answer("Пользователь заблокирован")


@router.callback_query(F.data.startswith("xui_unote_"))
async def cb_user_note(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_unote_"):], {})
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    await state.update_data(target_user_key=user_key, target_ib_id=ib_id)
    await state.set_state(XuiNoteEdit.waiting_note)
    await call.message.edit_text("Введите новую заметку.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
    await call.answer()


@router.message(XuiNoteEdit.waiting_note)
async def note_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    note = (message.text or "").strip()
    data = await state.get_data()
    user_key = str(data.get("target_user_key") or "")
    ib_id = int(data.get("target_ib_id") or 0)
    if not user_key:
        await message.answer("Пользователь не найден.")
        return
    if user_key.isdigit():
        set_user_note(int(user_key), note)
    else:
        from xui.storage import load_vpn_users
        users = load_vpn_users()
        if user_key in users:
            users[user_key]["note"] = note[:50]
            save_vpn_users(users)
    await state.clear()
    await message.answer("✅ Заметка сохранена.")


@router.callback_query(F.data.startswith("xui_uunbind_"))
async def cb_user_unbind(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_uunbind_"):], {})
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key or not user_key.isdigit():
        return await call.answer("Нельзя отвязать", show_alert=True)
    set_user_vpn_access(int(user_key), False)
    await _show_user_menu(call.message, user_key, ib_id, edit=True)
    await call.answer("TG отвязан")


@router.callback_query(F.data.startswith("xui_udelall_"))
async def cb_user_del_all(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_udelall_"):], {})
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    info = get_vpn_user(int(user_key)) if user_key.isdigit() else load_vpn_users().get(user_key, {})
    for device in list(info.get("devices", [])):
        await api_del_client_by_email(device.get("email", ""))
        if user_key.isdigit():
            remove_device_from_user(int(user_key), int(device.get("ib_id", 0)), device.get("email", ""))
    await _show_user_menu(call.message, user_key, ib_id, edit=True)
    await call.answer("Все устройства удалены")


@router.callback_query(F.data.startswith("xui_udel_"))
async def cb_user_delete(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_udel_"):], {})
    user_key, _ = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    delete_user_completely(user_key)
    await call.message.edit_text("✅ Пользователь удалён.")
    await call.answer()


@router.callback_query(F.data.startswith("xui_bindanon_"))
async def cb_bind_anon(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_bindanon_"):], {})
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    await state.update_data(target_user_key=user_key, target_ib_id=ib_id)
    await state.set_state(XuiBindTg.waiting_tg_id)
    await call.message.edit_text("Введите TG ID для привязки.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
    await call.answer()


@router.message(XuiBindTg.waiting_tg_id)
async def bind_tg_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой TG ID.\n\nДля выхода введите /cancel")
        return
    data = await state.get_data()
    user_key = str(data.get("target_user_key") or "")
    if not user_key:
        await message.answer("Пользователь не найден.")
        return
    if user_key in load_vpn_users():
        users = load_vpn_users()
        if user_key in users:
            users[raw] = users.pop(user_key)
            users[raw]["has_vpn_access"] = True
            save_vpn_users(users)
    await state.clear()
    await message.answer("✅ TG ID привязан.")


@router.callback_query(F.data.startswith("xui_bind_"))
async def cb_bind_client(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    from xui.utils import _cache

    payload = _cache.get(call.data[len("xui_bind_"):], {})
    client_hash = call.data[len("xui_bind_"):]
    info = _find_device_by_hash(client_hash)
    if not info:
        return await call.answer("Клиент не найден", show_alert=True)
    await state.update_data(
        target_client_hash=client_hash,
        target_client_email=info.get("email", ""),
        target_client_ib_id=int(info.get("ib_id", 0) or 0),
        target_client_uuid=info.get("uuid", ""),
    )
    await state.set_state(XuiBindTg.waiting_tg_id)
    await call.message.edit_text(
        "Введите TG ID для привязки этого клиента.\n\nДля выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data.startswith("xui_tog_"))
async def cb_toggle_client(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    client_hash = call.data[len("xui_tog_"):]
    info = _find_device_by_hash(client_hash)
    email = info.get("email", "")
    if not email:
        return await call.answer("Клиент не найден", show_alert=True)
    client = await api_get_client(email)
    if not client:
        return await call.answer("Не удалось загрузить клиента", show_alert=True)
    enabled = bool(client.get("enable", True))
    client["enable"] = not enabled
    result = await api_update_client(email, client)
    if not result.get("success", True):
        return await call.answer(result.get("msg", "Не удалось обновить клиента"), show_alert=True)
    await _refresh_client_view(call, client_hash)
    await call.answer("Клиент обновлён")


@router.callback_query(F.data.startswith("xui_inst_"))
async def cb_client_inst(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    client_hash = call.data[len("xui_inst_"):]
    info = _find_device_by_hash(client_hash)
    email = info.get("email", "?")
    await call.answer()
    await call.message.answer(
        "📖 <b>Инструкция</b>\n\n"
        f"Клиент: <code>{email}</code>\n"
        "Ссылку и формат подключения мы подключим в следующем шаге.",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("xui_clnote_"))
async def cb_client_note(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    client_hash = call.data[len("xui_clnote_"):]
    info = _find_device_by_hash(client_hash)
    if not info:
        return await call.answer("Клиент не найден", show_alert=True)
    await state.update_data(target_client_hash=client_hash)
    await state.set_state(XuiNoteEdit.waiting_note)
    await call.message.edit_text("Введите новую заметку для клиента.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data.startswith("xui_del_"))
async def cb_client_delete(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    client_hash = call.data[len("xui_del_"):]
    info = _find_device_by_hash(client_hash)
    email = info.get("email", "")
    ib_id = int(info.get("ib_id", 0) or 0)
    if not email:
        return await call.answer("Клиент не найден", show_alert=True)
    result = await api_del_client_by_email(email)
    if not result.get("success", True):
        return await call.answer(result.get("msg", "Не удалось удалить клиента"), show_alert=True)
    owner_key = _find_owner_key(ib_id, email)
    if owner_key and owner_key.isdigit():
        remove_device_from_user(int(owner_key), ib_id, email)
    elif owner_key:
        user_data = load_vpn_users()
        if owner_key in user_data:
            user_data[owner_key]["devices"] = [
                d for d in user_data[owner_key].get("devices", [])
                if not (d.get("ib_id") == ib_id and d.get("email") == email)
            ]
            save_vpn_users(user_data)
    await call.message.edit_text("✅ Клиент удалён.")
    await call.answer()
