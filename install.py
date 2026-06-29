#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
DATA_DIR = ROOT / "data"


def ask(prompt: str, required: bool = False, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"Введите {prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("Поле обязательно.")


def write_env(token: str, admin_id: str) -> None:
    data = {
        "TOKEN": token,
        "ADMIN_ID": admin_id,
        "XUI_URL": "",
        "XUI_TOKEN": "",
        "DATA_DIR": "data",
        "AUTH_FILE": "data/authorized.json",
        "SETTINGS_FILE": "data/settings.json",
        "XUI_SETTINGS_FILE": "data/xui_settings.json",
    }
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in data.items()) + "\n", encoding="utf-8")


def main() -> None:
    print("Drebol bot: первичная настройка")
    token = ask("TOKEN бота", required=True)
    admin_id = ask("ADMIN ID", required=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_env(token, admin_id)

    auth_file = ROOT / "data" / "authorized.json"
    if not auth_file.exists():
        auth_file.write_text(json.dumps([int(admin_id)], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    settings_file = ROOT / "data" / "settings.json"
    if not settings_file.exists():
        settings_file.write_text("{}\n", encoding="utf-8")

    xui_settings_file = ROOT / "data" / "xui_settings.json"
    if not xui_settings_file.exists():
        xui_settings_file.write_text("{}\n", encoding="utf-8")

    print(f".env создан: {ENV_FILE}")
    print("Теперь можно запускать бота через main.py")


if __name__ == "__main__":
    main()
