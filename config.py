import os
import json
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
INSTALL_DIR: str = "/root/drebol-vpn"
CONFIG_FILE: str = os.path.join(INSTALL_DIR, "config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(data: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
