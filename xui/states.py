from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class XuiAddUser(StatesGroup):
    waiting_tg_id = State()
    waiting_max_devices = State()
    waiting_limit_gb = State()
    waiting_expiry = State()


class XuiNoteEdit(StatesGroup):
    waiting_note = State()


class XuiBindTg(StatesGroup):
    waiting_tg_id = State()


class XuiAdminAddDevice(StatesGroup):
    waiting_name = State()
    waiting_limit_ip = State()


class XuiVpnAddDevice(StatesGroup):
    waiting_name = State()
    waiting_limit_ip = State()


class XuiSettings(StatesGroup):
    waiting_url = State()
    waiting_token = State()
    waiting_subport = State()
    waiting_inbound_subport = State()
