from __future__ import annotations

import html
import re
import secrets
from datetime import datetime

from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from loader import bot
from sub.api import api_add_client, api_get_client, api_get_inbounds, api_del_client_by_email, api_update_client
from sub.helpers import parse_clients
from sub.instructions import happ_instruction
from sub.keyboards import client_actions_kb, flow_choice_kb
from sub.adminsub.inbound_settings_store import get_inbound_sub_port, set_inbound_sub_port
from sub.adminsub.storage import (
    DEFAULT_EXPIRY_TIME_MS,
    DEFAULT_FLOW,
    DEFAULT_LIMIT_GB,
    DEFAULT_LIMIT_IP,
    DEFAULT_MAX_DEVICES,
    add_device_to_user,
    add_device_to_user_key,
    create_user_with_inbound,
    delete_user_completely,
    get_effective_user_setting,
    get_user_key_by_client,
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
    set_user_flow,
    set_user_limit_gb,
    set_user_limit_ip,
    set_user_max_devices,
    set_user_note_key,
    user_settings_ready,
    get_client_note,
)
from sub.states import XuiAddUser, XuiBindTg, XuiNoteEdit, XuiUserSettings, XuiSettings as InboundSettingsState
from sub.utils import cache, format_bytes, is_admin
from sub.views import _refresh_client_view, _show_user_menu, _show_user_settings, render_inbound, render_inbounds, render_inbound_settings


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
    from sub.utils import _cache

    return dict(_cache.get(hash_value, {}) or {})


def _decode_client_payload(payload: dict) -> tuple[str, int, str]:
    email = str(payload.get("email", "") or "")
    ib_id = int(payload.get("ib_id", 0) or 0)
    uuid_value = str(payload.get("uuid", "") or "")
    return email, ib_id, uuid_value


async def _sync_user_settings_to_panel(user_key: str) -> None:
    info = load_vpn_users().get(user_key, {})
    devices = info.get("devices", [])
    if not devices:
        return
    limit_gb = float(info.get("limit_gb") or 0.0)
    expiry_time_ms = int(info.get("expiry_time_ms") or DEFAULT_EXPIRY_TIME_MS)
    limit_ip = int(info.get("limit_ip") or DEFAULT_LIMIT_IP)
    flow = str(info.get("flow") or DEFAULT_FLOW)
    for device in devices:
        email = str(device.get("email", "") or "")
        if not email:
            continue
        client = await api_get_client(email)
        if not client:
            continue
        client["totalGB"] = 0 if limit_gb <= 0 else int(limit_gb * 1024 ** 3)
        client["expiryTime"] = expiry_time_ms
        client["limitIp"] = limit_ip
        client["flow"] = flow
        await api_update_client(email, client)


async def _show_client_details(call_or_message, email: str, ib_id: int, owner_user_key: str = "", *, edit: bool = False) -> None:
    inbounds, _ = await api_get_inbounds()
    inbound = next((ib for ib in inbounds if ib.get("id") == ib_id), None)
    if not inbound:
        text = "❌ Клиент не найден"
        if edit:
            await call_or_message.edit_text(text)
        else:
            await call_or_message.answer(text)
        return
    client = await api_get_client(email)
    if not client:
        text = "❌ Клиент не найден"
        if edit:
            await call_or_message.edit_text(text)
        else:
            await call_or_message.answer(text)
        return
    stats_map = {}
    try:
        from sub.helpers import get_client_stats_map

        stats_map = get_client_stats_map(inbound)
    except Exception:
        stats_map = {}
    stats = stats_map.get(email, {})
    enabled = bool(client.get("enable", True))
    up = format_bytes(stats.get("up", 0))
    down = format_bytes(stats.get("down", 0))
    total = stats.get("total", 0)
    total_str = format_bytes(total) if total > 0 else "∞"
    expiry = client.get("expiryTime", 0)
    expiry_str = "∞" if not expiry or expiry == 0 else f"{expiry}"
    note = get_client_note(ib_id, email)
    if not owner_user_key:
        for uk, uinfo in load_vpn_users().items():
            for d in uinfo.get("devices", []):
                if d.get("ib_id") == ib_id and d.get("email") == email:
                    owner_user_key = uk
                    break
            if owner_user_key:
                break
    text = f"👤 <b>{email}</b>\n\n"
    if owner_user_key:
        if owner_user_key.startswith("anon_"):
            text += "👥 Владелец: <i>без TG</i>\n"
        else:
            text += f"👥 Владелец: TG <code>{owner_user_key}</code>\n"
    text += (
        f"📌 Статус: {'✅ Активен' if enabled else '❌ Отключён'}\n"
        f"📤 Отправлено: <b>{up}</b>\n"
        f"📥 Получено: <b>{down}</b>\n"
        f"💾 Лимит: <b>{total_str}</b>\n"
        f"⏳ Срок: <b>{expiry_str}</b>"
    )
    if note:
        text += f"\n📝 Заметка: <i>{html.escape(note)}</i>"
    client_hash = cache(f"cl_{ib_id}_{email}", {"email": email, "uuid": client.get("id", ""), "ib_id": ib_id, "owner_uk": owner_user_key})
    markup = client_actions_kb(client_hash, enabled, owner_user_key)
    if edit:
        await call_or_message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await call_or_message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


def _device_hash(ib_id: int, email: str) -> str:
    from sub.utils import cache

    return cache(f"admin_dev_{ib_id}_{email}", {"ib_id": ib_id, "email": email})


async def _render_user(call_or_msg, user_key: str, ib_id: int, edit: bool = True):
    await _show_user_menu(call_or_msg, user_key, ib_id, edit=edit)


async def _render_settings(call_or_msg, user_key: str, edit: bool = True):
    await _show_user_settings(call_or_msg, user_key, edit=edit)


async def _restore_admin_menu(message: types.Message, kind: str, data: dict) -> None:
    if kind == "user_settings":
        await _show_user_settings(message, str(data.get("target_user_key") or ""), edit=False)
        return
    if kind == "user_menu":
        await _show_user_menu(message, str(data.get("target_user_key") or ""), int(data.get("target_user_ib_id") or 0), edit=False)
        return
    if kind == "inbound_settings":
        inbound_id = int(data.get("target_inbound_id") or 0)
        if inbound_id:
            inbounds, _ = await api_get_inbounds()
            inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)
            if inbound:
                await render_inbound_settings(message, inbound)
                return
    if kind == "client_view":
        await _show_client_details(
            message,
            str(data.get("target_client_email") or ""),
            int(data.get("target_client_ib_id") or 0),
            str(data.get("target_client_owner_user_key") or ""),
            edit=False,
        )
        return
    if kind == "inbound":
        inbound_id = int(data.get("target_inbound_id") or data.get("xui_ib_id") or 0)
        if inbound_id:
            inbounds, _ = await api_get_inbounds()
            inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)
            if inbound:
                await render_inbound(message, inbound)


def _settings_back_button(user_key: str) -> str:
    from sub.utils import cache

    return cache(f"usetm_back_{user_key}", {"user_key": user_key, "ib_id": 0})


def _format_user_menu_text(user_key: str, info: dict, *, devices: list | None = None) -> tuple[str, int]:
    devices = info.get("devices", []) if devices is None else devices
    max_devices = int(info.get("max_devices", 1) or 1)
    if user_key.startswith("anon_"):
        header = "👤 <b>Пользователь без TG ID</b>"
    else:
        header = f"👤 <b>TG: {user_key}</b>"
    return (
        f"{header}\n\n"
        f"📱 Устройств: <b>{len(devices)} / {max_devices}</b>",
        max_devices,
    )


async def _ensure_user_owner_key(user_key: str) -> str:
    if user_key.startswith("anon_"):
        return user_key
    return user_key


@router.message(Command("adminsub"))
@router.message(Command("adminxui"))
async def cmd_adminsub(message: types.Message):
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


@router.callback_query(F.data.startswith("xui_ibsettings_"))
async def cb_inbound_settings(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    ib_hash = call.data[len("xui_ibsettings_"):]
    info = _cache_lookup(ib_hash)
    inbound_id = info.get("id")
    if inbound_id is None:
        return await call.answer("Инбаунд не найден", show_alert=True)
    inbounds, err = await api_get_inbounds()
    inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)
    if not inbound:
        return await call.answer(f"Инбаунд не найден: {err}", show_alert=True)
    await render_inbound_settings(call, inbound)
    await call.answer()


@router.callback_query(F.data.startswith("xui_ibsubport_"))
async def cb_inbound_subport(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    ib_hash = call.data[len("xui_ibsubport_"):]
    info = _cache_lookup(ib_hash)
    inbound_id = info.get("id")
    if inbound_id is None:
        return await call.answer("Инбаунд не найден", show_alert=True)
    inbounds, err = await api_get_inbounds()
    inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)
    if not inbound:
        return await call.answer(f"Инбаунд не найден: {err}", show_alert=True)
    current = get_inbound_sub_port(inbound_id) or "не задан"
    await state.update_data(target_inbound_id=int(inbound_id), target_return_kind="inbound_settings")
    await state.set_state(InboundSettingsState.waiting_inbound_subport)
    await call.message.edit_text(
        "📡 <b>Порт подписки</b>\n\n"
        f"Текущий порт: <code>{current}</code>\n\n"
        "Отправь новый порт числом.\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data.startswith("xui_cl_"))
async def cb_client(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    await _refresh_client_view(call, call.data[len("xui_cl_"):])
    await call.answer()


@router.callback_query(F.data.startswith("xui_inst_"))
async def cb_client_instruction(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_inst_"):])
    email, _, _ = _decode_client_payload(payload)
    if not email:
        return await call.answer("Клиент не найден", show_alert=True)
    client = await api_get_client(email)
    sub_id = str((client or {}).get("subId") or email)
    inbound_id = int(payload.get("ib_id", 0) or 0)
    await call.answer()
    await call.message.answer(happ_instruction(sub_id, inbound_id), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("xui_bind_"))
async def cb_client_bind_tg(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_bind_"):])
    email, ib_id, uuid_value = _decode_client_payload(payload)
    if not email:
        return await call.answer("Клиент не найден", show_alert=True)
    await state.update_data(
        target_client_email=email,
        target_client_ib_id=ib_id,
        target_client_uuid=uuid_value,
        target_client_owner_user_key=str(payload.get("owner_uk") or ""),
        target_return_kind="client_view",
    )
    await state.set_state(XuiBindTg.waiting_tg_id)
    await call.message.edit_text(
        "📱 Отправь <b>TG ID</b>, к которому нужно привязать это устройство.\n\n"
        "Если у пользователя уже достигнут лимит устройств, привязка не выполнится.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data.startswith("xui_clnote_"))
async def cb_client_note(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_clnote_"):])
    email, ib_id, _ = _decode_client_payload(payload)
    if not email:
        return await call.answer("Клиент не найден", show_alert=True)
    await state.update_data(
        target_note_kind="client",
        target_client_email=email,
        target_client_ib_id=ib_id,
        target_return_kind="client_view",
    )
    await state.set_state(XuiNoteEdit.waiting_note)
    await call.message.edit_text(
        "📝 Отправь новую заметку для устройства.\n\n"
        "Можно отправить <code>-</code>, чтобы очистить заметку.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data.startswith("xui_unote_"))
async def cb_user_note(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_unote_"):])
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    await state.update_data(
        target_note_kind="user",
        target_user_key=user_key,
        target_user_ib_id=ib_id,
        target_return_kind="user_menu",
    )
    await state.set_state(XuiNoteEdit.waiting_note)
    await call.message.edit_text(
        "📝 Отправь новую заметку для пользователя.\n\n"
        "Можно отправить <code>-</code>, чтобы очистить заметку.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
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
    await state.update_data(target_user_key=user_key, target_setting_field=field, target_return_kind="user_settings")
    await state.set_state(XuiUserSettings.waiting_value)
    await call.message.edit_text(prompt, parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data.startswith("xui_def_max_"))
@router.callback_query(F.data.startswith("xui_def_gb_"))
@router.callback_query(F.data.startswith("xui_def_exp_"))
@router.callback_query(F.data.startswith("xui_def_ip_"))
@router.callback_query(F.data.startswith("xui_def_flow_"))
async def cb_user_settings_default(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data.split("_", 3)[-1])
    user_key, _ = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    if call.data.startswith("xui_def_max_"):
        set_user_max_devices(user_key, DEFAULT_MAX_DEVICES)
        await _sync_user_settings_to_panel(user_key)
    elif call.data.startswith("xui_def_gb_"):
        set_user_limit_gb(user_key, DEFAULT_LIMIT_GB)
        await _sync_user_settings_to_panel(user_key)
    elif call.data.startswith("xui_def_exp_"):
        set_user_expiry_time_ms(user_key, DEFAULT_EXPIRY_TIME_MS)
        await _sync_user_settings_to_panel(user_key)
    elif call.data.startswith("xui_def_ip_"):
        set_user_limit_ip(user_key, DEFAULT_LIMIT_IP)
        await _sync_user_settings_to_panel(user_key)
    elif call.data.startswith("xui_def_flow_"):
        set_user_flow(user_key, DEFAULT_FLOW)
        await _sync_user_settings_to_panel(user_key)
    else:
        return await call.answer("Неизвестная настройка", show_alert=True)
    await _show_user_settings(call.message, user_key, edit=True)
    await call.answer("Значение по умолчанию применено")


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
        await _sync_user_settings_to_panel(user_key)
    except ValueError:
        await message.answer("Некорректное значение.\n\nДля выхода введите /cancel")
        return
    await state.clear()
    await _restore_admin_menu(message, str(data.get("target_return_kind") or "user_settings"), data)


@router.callback_query(F.data.startswith("xui_adduser_"))
async def cb_add_user(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_adduser_"):])
    ib_id = payload.get("id")
    if not ib_id:
        return await call.answer("Инбаунд не найден", show_alert=True)
    await state.update_data(xui_ib_id=int(ib_id), target_inbound_id=int(ib_id), target_return_kind="inbound")
    await state.set_state(XuiAddUser.waiting_tg_id)
    await call.message.edit_text(
        "Введите <b>TG ID</b> пользователя или <code>-</code>, если TG нет.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.message(XuiAddUser.waiting_tg_id)
async def add_user_tg_id(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    ib_id = int(data.get("xui_ib_id", 0))
    if raw == "-":
        tg_id = None
    elif raw.isdigit():
        tg_id = int(raw)
    else:
        await message.answer("Нужен числовой TG ID или <code>-</code>.\n\nДля выхода введите /cancel", parse_mode=ParseMode.HTML)
        return
    create_user_with_inbound(tg_id, ib_id)
    await state.clear()
    inbounds, _ = await api_get_inbounds()
    inbound = next((item for item in inbounds if item.get("id") == ib_id), None)
    if inbound:
        await render_inbound(message, inbound)
        return
    if tg_id is None:
        await message.answer("✅ Пользователь без TG ID создан. Открой его и настрой параметры через ⚙️ Настройки.")
    else:
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
    if len(info.get("devices", [])) >= int(info.get("max_devices", 1) or 1):
        return await call.answer("⛔ Достигнут лимит устройств", show_alert=True)
    await state.update_data(
        target_user_key=user_key,
        target_ib_id=ib_id_default or int(info.get("default_ib_id", 0) or 0),
        target_return_kind="user_menu",
    )
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
    flow = str(info.get("flow") or DEFAULT_FLOW)
    result, client_uuid = await api_add_client(
        base_ib,
        email,
        0,
        limit_gb,
        flow,
        expiry_time_ms=expiry_time_ms,
        limit_ip=limit_ip,
    )
    if not result.get("success"):
        await state.clear()
        await message.answer(f"❌ Не удалось создать устройство.\n<code>{result.get('msg', '')}</code>", parse_mode=ParseMode.HTML)
        return
    add_device_to_user_key(user_key, base_ib, client_uuid, email, limit_ip=limit_ip)
    await state.clear()
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


@router.callback_query(F.data.startswith("xui_udelall_"))
async def cb_user_delete_all(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_udelall_"):])
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    info = load_vpn_users().get(user_key, {})
    removed = 0
    for device in list(info.get("devices", [])):
        email = device.get("email", "")
        if not email:
            continue
        await api_del_client_by_email(email)
        removed += 1
        if user_key.isdigit():
            remove_device_from_user(int(user_key), int(device.get("ib_id", 0) or 0), email)
    if not user_key.isdigit():
        data = load_vpn_users()
        if user_key in data:
            data[user_key]["devices"] = []
            save_vpn_users(data)
    await _show_user_menu(call.message, user_key, ib_id, edit=True)
    await call.answer("Устройства удалены" if removed else "Устройств не было")


@router.callback_query(F.data.startswith("xui_udel_user_"))
async def cb_user_delete(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    payload = _cache_lookup(call.data[len("xui_udel_user_"):])
    user_key, ib_id = _decode_user_payload(payload)
    if not user_key:
        return await call.answer("Пользователь не найден", show_alert=True)
    info = load_vpn_users().get(user_key, {})
    for device in list(info.get("devices", [])):
        email = device.get("email", "")
        if email:
            await api_del_client_by_email(email)
    delete_user_completely(user_key)
    inbounds, _ = await api_get_inbounds()
    inbound = next((item for item in inbounds if item.get("id") == ib_id), None)
    if inbound:
        try:
            await render_inbound(call, inbound)
        except Exception:
            await call.message.answer("✅ Пользователь удалён.")
    else:
        try:
            await call.message.edit_text("✅ Пользователь удалён.")
        except Exception:
            await call.message.answer("✅ Пользователь удалён.")
    await call.answer("✅ Пользователь удалён")


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
    await state.update_data(target_user_key=user_key, target_ib_id=ib_id, target_return_kind="user_menu")
    await state.set_state(XuiBindTg.waiting_tg_id)
    await call.message.edit_text(
        "Введите TG ID для привязки.\n\n"
        "Если у пользователя уже достигнут лимит устройств, привязка не выполнится.\n\n"
        "Для выхода введите /cancel",
        parse_mode=ParseMode.HTML,
    )
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
    target_client_email = str(data.get("target_client_email") or "")
    target_client_ib_id = int(data.get("target_client_ib_id") or 0)
    target_client_uuid = str(data.get("target_client_uuid") or "")
    if not user_key:
        if not target_client_email or not target_client_ib_id:
            await message.answer("Пользователь не найден.")
            return
    new_key = raw
    if user_key:
        users = load_vpn_users()
        if user_key in users:
            if new_key in users:
                target_info = users[new_key]
                max_devices = int(target_info.get("max_devices", 1) or 1)
                device_count = len(target_info.get("devices", []))
                if device_count >= max_devices:
                    await state.clear()
                    await message.answer(
                        f"⛔ У пользователя уже {device_count}/{max_devices} устройств.\n"
                        "Сначала освободите слот или увеличьте лимит устройств."
                    )
                    return
            rekey_user(user_key, new_key)
            data = load_vpn_users()
            if new_key in data and user_settings_ready(data[new_key]):
                data[new_key]["has_vpn_access"] = True
                save_vpn_users(data)
    else:
        users = load_vpn_users()
        if new_key in users:
            target_info = users[new_key]
            max_devices = int(target_info.get("max_devices", 1) or 1)
            device_count = len(target_info.get("devices", []))
            if device_count >= max_devices:
                await state.clear()
                await message.answer(
                    f"⛔ У пользователя уже {device_count}/{max_devices} устройств.\n"
                    "Сначала освободите слот или увеличьте лимит устройств."
                )
                return
        add_device_to_user_key(
            new_key,
            target_client_ib_id,
            target_client_uuid or "",
            target_client_email,
        )
    await state.clear()
    if target_client_email:
        await _show_client_details(message, target_client_email, target_client_ib_id, edit=False)
    elif user_key:
        await _show_user_menu(message, new_key, int(data.get("target_ib_id") or 0), edit=False)
    else:
        await message.answer("✅ TG ID привязан.")


@router.message(XuiNoteEdit.waiting_note)
async def note_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    note_kind = str(data.get("target_note_kind") or "")
    raw = (message.text or "").strip()
    note = "" if raw == "-" else raw
    if not note_kind:
        await state.clear()
        await message.answer("Контекст заметки не найден.")
        return
    if note_kind == "user":
        user_key = str(data.get("target_user_key") or "")
        ib_id = int(data.get("target_user_ib_id") or 0)
        if not user_key:
            await state.clear()
            await message.answer("Пользователь не найден.")
            return
        set_user_note_key(user_key, note)
        await state.clear()
        await _show_user_menu(message, user_key, ib_id, edit=False)
        return
    email = str(data.get("target_client_email") or "")
    ib_id = int(data.get("target_client_ib_id") or 0)
    if not email or not ib_id:
        await state.clear()
        await message.answer("Клиент не найден.")
        return
    set_client_note(ib_id, email, note)
    await state.clear()
    await _show_client_details(message, email, ib_id, str(data.get("target_client_owner_user_key") or ""), edit=False)


@router.message(InboundSettingsState.waiting_inbound_subport)
async def inbound_subport_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой порт.\n\nДля выхода введите /cancel")
        return
    data = await state.get_data()
    inbound_id = int(data.get("target_inbound_id") or 0)
    if not inbound_id:
        await state.clear()
        await message.answer("Инбаунд не найден.")
        return
    set_inbound_sub_port(inbound_id, raw)
    await state.clear()
    inbounds, err = await api_get_inbounds()
    inbound = next((ib for ib in inbounds if ib.get("id") == inbound_id), None)
    if inbound:
        await render_inbound_settings(message, inbound)
        return
    await message.answer(f"✅ Порт подписки сохранён.\n\n<code>{err}</code>", parse_mode=ParseMode.HTML)


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
        owner_user_key = get_user_key_by_client(ib_id, email)
        if owner_user_key and owner_user_key.isdigit():
            remove_device_from_user(int(owner_user_key), ib_id, email)
        else:
            owner_user_key = owner_user_key or ""
        for uk, uinfo in load_vpn_users().items():
            if any(d.get("ib_id") == ib_id and d.get("email") == email for d in uinfo.get("devices", [])):
                data = load_vpn_users()
                data[uk]["devices"] = [d for d in data[uk].get("devices", []) if not (d.get("ib_id") == ib_id and d.get("email") == email)]
                save_vpn_users(data)
                break
    owner_user_key = info.get("owner_uk", "") or get_user_key_by_client(ib_id, email) or ""
    if owner_user_key:
        try:
            await _show_user_menu(call.message, owner_user_key, ib_id, edit=True)
        except Exception:
            await call.message.answer("✅ Клиент удалён.")
    else:
        inbounds, _ = await api_get_inbounds()
        inbound = next((item for item in inbounds if item.get("id") == ib_id), None)
        if inbound:
            try:
                await render_inbound(call, inbound)
            except Exception:
                await call.message.answer("✅ Клиент удалён.")
        else:
            await call.message.edit_text("✅ Клиент удалён.")
    await call.answer("✅ Клиент удалён")


@router.callback_query(F.data.startswith("xui_tog_"))
async def cb_client_toggle(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    client_hash = call.data[len("xui_tog_"):]
    info = _cache_lookup(client_hash)
    email = info.get("email", "")
    if not email:
        return await call.answer("Клиент не найден", show_alert=True)
    client = await api_get_client(email)
    if not client:
        return await call.answer("Не удалось загрузить клиента", show_alert=True)
    client["enable"] = not bool(client.get("enable", True))
    result = await api_update_client(email, client)
    if not result.get("success", True):
        return await call.answer(result.get("msg", "Не удалось обновить клиента"), show_alert=True)
    await _show_client_details(call.message, email, int(info.get("ib_id", 0) or 0), str(info.get("owner_uk") or ""), edit=True)
    await call.answer("Состояние обновлено")
