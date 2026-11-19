import os
import json
import tempfile
import threading
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
# Капча Cloudflare Turnstile для входа в кабинет по почте и паролю.
# Нет ключей — вход по паролю выключен, вход через Telegram работает.
TURNSTILE_SITE_KEY: str = os.getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY: str = os.getenv("TURNSTILE_SECRET_KEY", "")
INSTALL_DIR: str = "/root/drebol-vpn"
CONFIG_FILE: str = os.path.join(INSTALL_DIR, "config.json")

# Блокировка писателей config.json: бот (основной поток), веб-API и
# фоновые потоки деплоя (asyncio.to_thread) пишут один и тот же файл.
# threading.RLock — а не asyncio.Lock, — потому что save_config()
# вызывается и из потоков, и из event loop.
_CONFIG_LOCK = threading.RLock()


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


SUB_STORED_DOMAIN = "key.drbl.tech"
SUB_DISPLAY_DOMAIN = "sub.drbl.tech"


def sub_url_for_display(sub_url: str) -> str:
    """Ссылка подписки в том виде, в каком её показывают пользователю.

    В базе и в панели ссылка хранится с key.drbl.tech. Какой домен
    показывать, выбирает настройка sub_link_domain (Настройки в
    веб-админке): "sub" (по умолчанию) — sub.drbl.tech, тот же origin,
    но через Yandex CDN; "key" — как хранится. Применяется везде:
    бот, личный кабинет, веб-админка.
    """
    if not sub_url:
        return ""
    mode = str(load_config().get("sub_link_domain") or "sub").strip().lower()
    want = SUB_STORED_DOMAIN if mode == "key" else SUB_DISPLAY_DOMAIN
    other = SUB_DISPLAY_DOMAIN if want == SUB_STORED_DOMAIN else SUB_STORED_DOMAIN
    if want in sub_url:
        return sub_url
    if other in sub_url:
        return sub_url.replace(other, want, 1)
    from urllib.parse import urlparse
    path = urlparse(sub_url).path.strip("/")
    return f"https://{want}/{path}" if path else ""


def turnstile_keys() -> tuple[str, str]:
    """Ключи капчи Cloudflare Turnstile: сначала config.json (задаются
    в админке), потом .env. Пустые — вход по паролю выключен."""
    cfg = load_config()
    site = str(cfg.get("turnstile_site_key") or "") or TURNSTILE_SITE_KEY
    secret = str(cfg.get("turnstile_secret_key") or "") or TURNSTILE_SECRET_KEY
    return site, secret


def save_config(data: dict) -> None:
    """Атомарно записывает config.json: временный файл в том же каталоге
    + os.replace, под блокировкой. Читатель никогда не увидит рваный
    файл, а два писателя подряд не потеряют друг друга на записи."""
    with _CONFIG_LOCK:
        parent = os.path.dirname(os.path.abspath(CONFIG_FILE)) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".config-", dir=parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, CONFIG_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def atomic_update(fn) -> dict:
    """load-modify-save одной неделимой операцией.

    fn(data) правит словарь на месте и может вернуть его же (или None).
    Использовать везде, где чтение и запись конфига должны быть единым
    целым — иначе два потока, прочитавших одну версию, затирают друг
    друга, даже если каждая запись сама по себе атомарна.
    """
    with _CONFIG_LOCK:
        data = load_config()
        out = fn(data)
        if out is not None:
            data = out
        save_config(data)
        return data
