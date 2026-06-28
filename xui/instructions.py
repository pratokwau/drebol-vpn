from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

from xui.config_runtime import get_xui_url
from xui.inbound_settings_store import get_inbound_sub_port


def build_subscription_link(sub_id: str | None, inbound_id: int | None = None) -> str:
    if not sub_id:
        return ""
    panel_url = get_xui_url().strip()
    sub_port = get_inbound_sub_port(inbound_id) if inbound_id is not None else ""
    if not panel_url or not sub_port:
        return ""
    parsed = urlsplit(panel_url)
    scheme = parsed.scheme or "https"
    host = parsed.hostname or parsed.path or panel_url
    return f"{scheme}://{host}:{sub_port}/sub/{escape(str(sub_id))}"


def happ_instruction(sub_id: str | None = None, inbound_id: int | None = None) -> str:
    device_line = ""
    subscription_link = build_subscription_link(sub_id, inbound_id)
    if subscription_link:
        device_line = (
            "Перейдите по ссылке на устройство пользователя из панели 3x-ui:\n"
            f"<a href=\"{subscription_link}\">Открыть ссылку подписки</a>\n"
        )
    return (
        "📖 <b>Инструкция</b>\n\n"
        "Установите приложение HAPP:\n"
        "• <a href=\"https://play.google.com/store/apps/details?id=com.happproxy\">Android</a>\n"
        "• <a href=\"https://apps.apple.com/au/app/happ-proxy-utility/id6504287215\">IOS</a>\n"
        "• <a href=\"https://apps.apple.com/au/app/happ-proxy-utility/id6504287215\">MacOS</a>\n"
        "• <a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe\">Windows</a>\n\n"
        f"{device_line}"
        "На сайте выберите ваше устройство и перейдите в приложение HAPP.\n\n"
        "🪟 <b>Для Windows</b>: сначала скопируйте ссылку подписки, затем в приложении HAPP нажмите <b>+</b> и выберите импорт из буфера обмена."
    )
