from __future__ import annotations

import secrets
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
    add_device_to_user,
    create_user_with_inbound,
    delete_user_completely,
    get_effective_user_setting,
    get_tg_id_by_client,
    get_vpn_user,
    load_vpn_users,
    rekey_user,
    remove_device_from_user,
    save_vpn_users,
    set_admin_disabled,
    set_admin_disabled_key,
    set_client_note,
    set_user_expiry_time_ms,
    set_user_limit_gb,
    set_user_limit_ip,
    set_user_max_devices,
    set_user_note,
    set_user_note_key,
    user_settings_ready,
)
from xui.states import XuiAddUser, XuiBindTg, XuiNoteEdit, XuiUserSettings
from xui.utils import is_admin
from xui.views import _refresh_client_view, _show_user_menu, _show_user_settings, render_inbound, render_inbounds


router = Router()


class XuiAdminAddDevice(StatesGroup):
    waiting_name = State()


def _decode_user_payload(payload: dict) -> tuple[str | None, int]:
    user_key = payload.get("user_key")
    ib_id = int(payload.get("ib_id", 0) or 0)
    return (str(user_key) if user_key else None, ib_id)


def _parse_expiry_date(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return 2523456000000
    dt = datetime.strptime(text, "%d.%m.%Y")
    return int(dt.timestamp() * 1000)


def _parse_limit_gb(raw: str | None) -> float:
    text = (raw or "").strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def _parse_limit_ip(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return 2
    return max(1, int(text))


def _parse_max_devices(raw: str | None) -> int:
    text = (raw or "").strip()
    if not text or text == "-":
        return 1
    return max(1, int(text))


def _sanitize_slug(text: str) -> str:
    slug = re.sub(r"[^\w-]+", "_", text.strip().lower(), flags=re.UNICODE)
    return slug.strip("_") or "device"


def _cache_lookup(hash_value: str) -> dict:
    from xui.utils import _cache

    return dict(_cache.get(hash_value, {}) or {})


def _device_hash(ib_id: int, email: str) -> str:
    from xui.utils import cache

    return cache(f"admin_dev_{ib_id}_{email}", {"ib_id": ib_id, "email": email})


async def _render_user(call_or_msg, user_key: str, ib_id: int, edit: bool = True):
    await _show_user_menu(call_or_msg, user_key, ib_id, edit=edit)


async def _render_settings(call_or_msg, user_key: str, edit: bool = True):
    await _show_user_settings(call_or_msg, user_key, edit=edit)


def _settings_back_button(user_key: str) -> str:
    from xui.utils import cache

    return cache(f"usetm_back_{user_key}", {"user_key": user_key, "ib_id": 0})


async def _ensure_user_owner_key(user_key: str) -> str:
    if user_key.startswith("anon_"):
        return user_key
    return user_key


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
    info = _cache_lookup(ib_hash)
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
    payload = _cache_lookup(call.data[len("xui_usr_"):])
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    await _render_user(call.message, user_key, int(ib_id or 0), edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("xui_usetm_"))
async def cb_user_settings(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_usetm_"):])
    user_key, _ = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    await _render_settings(call.message, user_key, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("xui_set_max_"))
@router.callback_query(F.data.startswith("xui_set_gb_"))
@router.callback_query(F.data.startswith("xui_set_exp_"))
@router.callback_query(F.data.startswith("xui_set_ip_"))
async def cb_user_settings_edit(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data.split("_", 3)[-1])
    user_key, _ = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    field = None
    if call.data.startswith("xui_set_max_"):
        field = "max_devices"
        prompt = (
            "Введите лимит устройств или <code>-</code> для значения по умолчанию.\n"
            "По умолчанию: <b>1</b>.\n\n"
            "Для выхода введите /cancel"
        )
    elif call.data.startswith("xui_set_gb_"):
        field = "limit_gb"
        prompt = (
            "Введите лимит ГБ или <code>-</code> для бесконечности.\n"
            "Пример: <code>100</code>\n\n"
            "Для выхода введите /cancel"
        )
    elif call.data.startswith("xui_set_exp_"):
        field = "expiry_time_ms"
        prompt = (
            "Введите дату окончания в формате <code>дд.мм.гггг</code> или <code>-</code>.\n"
            "Дефолт: <b>12.12.2050</b>.\n\n"
            "Для выхода введите /cancel"
        )
    elif call.data.startswith("xui_set_ip_"):
        field = "limit_ip"
        prompt = (
            "Введите лимит IP или <code>-</code> для значения по умолчанию.\n"
            "По умолчанию: <b>2</b>.\n\n"
            "Для выхода введите /cancel"
        )
    if not field:
        return await call.answer("Неизвестная настройка", show_alert=True)
    await state.update_data(target_user_key=user_key, target_setting_field=field)
    await state.set_state(XuiUserSettings.waiting_value)
    await call.message.edit_text(prompt, parse_mode=ParseMode.HTML)
    await call.answer()


@router.message(XuiUserSettings.waiting_value)
async def user_settings_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    user_key = str(data.get("target_user_key") or "")
    field = str(data.get("target_setting_field") or "")
    if not user_key or not field:
        await message.answer("Пользователь не найден.")
        return
    raw = (message.text or "").strip()
    try:
        if field == "max_devices":
            value = _parse_max_devices(raw)
            set_user_max_devices(user_key, value)
        elif field == "limit_gb":
            value = _parse_limit_gb(raw)
            set_user_limit_gb(user_key, value)
        elif field == "expiry_time_ms":
            value = _parse_expiry_date(raw)
            set_user_expiry_time_ms(user_key, value)
        elif field == "limit_ip":
            value = _parse_limit_ip(raw)
            set_user_limit_ip(user_key, value)
        else:
            await message.answer("Неизвестная настройка.")
            return
    except ValueError:
        await message.answer("Некорректное значение.\n\nДля выхода введите /cancel")
        return
    current = load_vpn_users().get(user_key, {})
    await state.clear()
    await message.answer(
        "✅ Настройка сохранена.",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"xui_usetm_{_settings_back_button(user_key)}")],
            ]
        ),
    )
    await _show_user_settings(message, user_key, edit=False)


@router.callback_query(F.data.startswith("xui_adduser_"))
async def cb_add_user(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_adduser_"):])
    ib_id = payload.get("id")
    if not ib_id:
        return await call.answer("Инбаунд не найден", show_alert=True)
    await state.update_data(xui_ib_id=int(ib_id))
    await state.set_state(XuiAddUser.waiting_tg_id)
    await call.message.edit_text(
        "Введите <b>TG ID</b> пользователя.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(XuiAddUser.waiting_tg_id)
async def add_user_tg_id(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой TG ID.\n\nДля выхода введите /cancel")
        return
    data = await state.get_data()
    tg_id = int(raw)
    ib_id = int(data.get("xui_ib_id", 0))
    create_user_with_inbound(tg_id, ib_id)
    await state.clear()
    await message.answer("✅ Пользователь создан. Открой его и настрой параметры через ⚙️ Настройки.")


@router.callback_query(F.data.startswith("xui_uadd_"))
async def cb_user_add_device(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_uadd_"):])
    user_key, ib_id_default = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    info = load_vpn_users().get(user_key, {})
    if not user_settings_ready(info):
        return await call.answer("Сначала настройте лимиты пользователя", show_alert=True)
    await state.update_data(target_user_key=user_key, target_ib_id=ib_id_default or int(info.get("default_ib_id", 0) or 0))
    await state.set_state(XuiAdminAddDevice.waiting_name)
    await call.message.edit_text(
        "Введите название устройства.\n\nДля выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(XuiAdminAddDevice.waiting_name)
async def admin_add_device_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым.\n\nДля выхода введите /cancel")
        return
    data = await state.get_data()
    user_key = str(data.get("target_user_key") or "")
    if not user_key:
        await message.answer("Пользователь не найден.")
        return
    info = load_vpn_users().get(user_key, {})
    if not user_settings_ready(info):
        await state.clear()
        await message.answer("⛔ Сначала настройте лимиты пользователя.")
        return
    tg_id = int(user_key) if user_key.isdigit() else None
    base_ib = int(data.get("target_ib_id") or info.get("default_ib_id") or 0)
    if not base_ib:
        await state.clear()
        await message.answer("⛔ Не выбран инбаунд для добавления устройства.")
        return
    devices = info.get("devices", [])
    if len(devices) >= int(info.get("max_devices", 1) or 1):
        await state.clear()
        await message.answer("⛔ Достигнут лимит устройств.")
        return
    slug = _sanitize_slug(name)
    email = f"{user_key}_{slug}"
    expiry_time_ms = int(info.get("expiry_time_ms") or 2523456000000)
    limit_gb = float(info.get("limit_gb") or 0.0)
    limit_ip = int(info.get("limit_ip") or 2)
    result, client_uuid = await api_add_client(
        base_ib,
        email,
        0,
        limit_gb,
        "",
        expiry_time_ms=expiry_time_ms,
        limit_ip=limit_ip,
    )
    if not result.get("success"):
        await state.clear()
        await message.answer(f"❌ Не удалось создать устройство.\n<code>{result.get('msg', '')}</code>", parse_mode=ParseMode.HTML)
        return
    if user_key.isdigit():
        add_device_to_user(int(user_key), base_ib, client_uuid, email, limit_ip=limit_ip)
    await state.clear()
    await message.answer(
        f"✅ Устройство <code>{email}</code> создано.\n"
        f"Лимит IP: <b>{limit_ip}</b>",
        parse_mode=ParseMode.HTML,
    )
    await _show_user_menu(message, user_key, base_ib, edit=False)
    if tg_id:
        try:
            await bot.send_message(
                tg_id,
                "✅ <b>Вам добавлено новое устройство.</b>\n\n"
                "Теперь используйте /vpn для управления.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("xui_ublk_"))
async def cb_user_block(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_ublk_"):])
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    info = load_vpn_users().get(user_key, {})
    for device in info.get("devices", []):
        email = device.get("email", "")
        if not email:
            continue
        client = await api_get_client(email)
        if client:
            client["enable"] = False
            await api_update_client(email, client)
    set_admin_disabled(int(user_key), True) if user_key.isdigit() else set_admin_disabled_key(user_key, True)
    await _show_user_menu(call.message, user_key, ib_id, edit=True)
    await call.answer("Пользователь заблокирован")


@router.callback_query(F.data.startswith("xui_unblk_"))
async def cb_user_unblock(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_unblk_"):])
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    info = load_vpn_users().get(user_key, {})
    for device in info.get("devices", []):
        email = device.get("email", "")
        if not email:
            continue
        client = await api_get_client(email)
        if client:
            client["enable"] = True
            await api_update_client(email, client)
    set_admin_disabled(int(user_key), False) if user_key.isdigit() else set_admin_disabled_key(user_key, False)
    await _show_user_menu(call.message, user_key, ib_id, edit=True)
    await call.answer("Пользователь разблокирован")


@router.callback_query(F.data.startswith("xui_uunbind_"))
async def cb_user_unbind(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_uunbind_"):])
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key or not user_key.isdigit():
        return await call.answer("Нельзя отвязать", show_alert=True)
    anon_key = f"anon_{secrets.token_hex(4)}"
    rekey_user(user_key, anon_key)
    await _show_user_menu(call.message, anon_key, ib_id, edit=True)
    await call.answer("TG отвязан")


@router.callback_query(F.data.startswith("xui_bindanon_"))
async def cb_bind_anon(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_bindanon_"):])
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
    new_key = raw
    if user_key in load_vpn_users():
        rekey_user(user_key, new_key)
        data = load_vpn_users()
        if new_key in data and user_settings_ready(data[new_key]):
            data[new_key]["has_vpn_access"] = True
            save_vpn_users(data)
    await state.clear()
    await message.answer("✅ TG ID привязан.")


@router.callback_query(F.data.startswith("xui_del_"))
async def cb_client_delete(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    client_hash = call.data[len("xui_del_"):]
    info = _cache_lookup(client_hash)
    email = info.get("email", "")
    ib_id = int(info.get("ib_id", 0) or 0)
    if not email:
        return await call.answer("Клиент не найден", show_alert=True)
    result = await api_del_client_by_email(email)
    if not result.get("success", True):
        return await call.answer(result.get("msg", "Не удалось удалить клиента"), show_alert=True)
    owner_key = get_tg_id_by_client(ib_id, email)
    if owner_key is not None:
        remove_device_from_user(owner_key, ib_id, email)
    else:
        for uk, uinfo in load_vpn_users().items():
            if any(d.get("ib_id") == ib_id and d.get("email") == email for d in uinfo.get("devices", [])):
                data = load_vpn_users()
                data[uk]["devices"] = [d for d in data[uk].get("devices", []) if not (d.get("ib_id") == ib_id and d.get("email") == email)]
                save_vpn_users(data)
                break
    await call.message.edit_text("✅ Клиент удалён.")
    await call.answer()
