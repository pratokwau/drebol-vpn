from __future__ import annotations

import json
from typing import List

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_ID, TOKEN
from storage import load_authorized_users


bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())


def load_users() -> List[int]:
    return load_authorized_users()


authorized_users = load_users()
if ADMIN_ID and ADMIN_ID not in authorized_users:
    authorized_users.append(ADMIN_ID)


def save_users(users):
    from storage import save_authorized_users

    save_authorized_users([int(x) for x in users])


def is_authorized(user_id: int) -> bool:
    return int(user_id) in authorized_users
