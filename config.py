from __future__ import annotations

import os

from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

XUI_URL = os.getenv("XUI_URL", "")
XUI_TOKEN = os.getenv("XUI_TOKEN", "")

DATA_DIR = os.getenv("DATA_DIR", "data")
AUTH_FILE = os.getenv("AUTH_FILE", "authorized.json")
SETTINGS_FILE = os.getenv("SETTINGS_FILE", f"{DATA_DIR}/settings.json")
XUI_SETTINGS_FILE = os.getenv("XUI_SETTINGS_FILE", f"{DATA_DIR}/xui_settings.json")
