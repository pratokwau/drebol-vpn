from __future__ import annotations

from html import escape
from urllib.parse import quote, urlsplit

from sub.config_runtime import get_xui_url
from sub.adminsub.inbound_settings_store import get_any_inbound_sub_port, get_inbound_sub_port


def build_subscription_link(sub_id: str | None, inbound_id: int | None = None) -> str:
    if not sub_id:
        return ""
    panel_url = get_xui_url().strip()
    sub_port = get_inbound_sub_port(inbound_id) if inbound_id is not None else ""
    if not sub_port:
        sub_port = get_any_inbound_sub_port()
    if not sub_port:
        parsed_for_port = urlsplit(panel_url) if panel_url else None
        sub_port = str(parsed_for_port.port or "") if parsed_for_port else ""
    if not panel_url or not sub_port:
        return ""
    parsed = urlsplit(panel_url)
    scheme = parsed.scheme or "https"
    host = parsed.hostname or parsed.path or panel_url
    return f"{scheme}://{host}:{sub_port}/sub/{quote(str(sub_id), safe='')}"


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
