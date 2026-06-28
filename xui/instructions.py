from __future__ import annotations

from html import escape


def happ_instruction(sub_id: str | None = None) -> str:
    device_line = ""
    if sub_id:
        device_line = (
            "Перейдите по ссылке на устройство пользователя из панели 3x-ui:\n"
            f"<code>https://vpn.drebol.ru:2096/sub/{escape(sub_id)}</code>\n"
        )
    return (
        "📖 <b>Инструкция</b>\n\n"
        "Установите приложение HAPP:\n"
        "• <a href=\"https://play.google.com/store/apps/details?id=com.happproxy\">Android</a>\n"
        "• <a href=\"https://apps.apple.com/au/app/happ-proxy-utility/id6504287215\">IOS</a>\n"
        "• <a href=\"https://apps.apple.com/au/app/happ-proxy-utility/id6504287215\">MacOS</a>\n"
        "• <a href=\"https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe\">Windows</a>\n\n"
        f"{device_line}"
        "На сайте выберите ваше устройство и перейдите в приложение HAPP."
    )
