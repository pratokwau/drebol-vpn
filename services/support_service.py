"""Управление сервисом бота поддержки (systemd).

После ввода токена в админке основной бот сам ставит и запускает
бота поддержки отдельным сервисом — Mark ничего вручную не запускает.
Сервис: drebol-support-bot, Restart=always (перезапуск при падении
и при смене токена), автозапуск при загрузке.
"""
import asyncio
import os
import subprocess
import sys

SERVICE_NAME = "drebol-support-bot"
UNIT_PATH = f"/etc/systemd/system/{SERVICE_NAME}.service"


def _unit_text(python_exe: str, install_dir: str) -> str:
    return (
        "[Unit]\n"
        "Description=Drebol VPN support bot\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={install_dir}\n"
        f"ExecStart={python_exe} {install_dir}/support_bot.py\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _run(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Синхронный запуск systemctl. Возвращает (ok, вывод/ошибка)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out.strip()
    except Exception as e:
        return False, str(e)


def _ensure_sync(python_exe: str, install_dir: str) -> tuple[bool, str]:
    """Поставить unit, перезагрузить systemd, включить и (пере)запустить."""
    try:
        with open(UNIT_PATH, "w") as f:
            f.write(_unit_text(python_exe, install_dir))
    except Exception as e:
        return False, f"не удалось записать {UNIT_PATH}: {e}"
    ok, out = _run(["systemctl", "daemon-reload"])
    if not ok:
        return False, f"daemon-reload: {out or 'ошибка'}"
    ok, out = _run(["systemctl", "enable", SERVICE_NAME])
    if not ok:
        return False, f"enable: {out or 'ошибка'}"
    ok, out = _run(["systemctl", "restart", SERVICE_NAME])
    if not ok:
        return False, f"restart: {out or 'ошибка'}"
    ok, out = _run(["systemctl", "is-active", SERVICE_NAME], timeout=15)
    if not ok:
        return False, "сервис не запустился (is-active != active)"
    return True, "active"


async def ensure_support_bot_running() -> tuple[bool, str]:
    """Поставить и запустить бота поддержки. Не блокирует event loop."""
    from config import INSTALL_DIR
    python_exe = sys.executable or os.path.join(INSTALL_DIR, "venv", "bin", "python")
    return await asyncio.to_thread(_ensure_sync, python_exe, INSTALL_DIR)
