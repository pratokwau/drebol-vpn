import re


_UNITS = {
    "минут": 60, "мин": 60, "minute": 60, "min": 60,
    "час": 3600, "hour": 3600, "hr": 3600,
    "день": 86400, "дн": 86400, "day": 86400,
    "недел": 604800, "week": 604800,
    "месяц": 2592000, "month": 2592000,
}

_PATTERN = re.compile(r"(\d+)\s*([a-zа-яё]+)", re.IGNORECASE)


def parse_duration(text: str) -> int:
    """Парсит строку вроде '5 часов', '7 дней', '2 недели', '44 минуты', '3 месяца'.
    Возвращает количество секунд или None если не удалось распознать."""
    m = _PATTERN.match(text.strip())
    if not m:
        return None
    num = int(m.group(1))
    if num <= 0:
        return None
    unit_text = m.group(2).lower()
    for prefix, seconds in _UNITS.items():
        if unit_text.startswith(prefix):
            return num * seconds
    return None


def _plural(n: int, forms: tuple) -> str:
    """forms = (одна, две, пять): '1 день', '2 дня', '5 дней'."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        word = forms[0]
    elif 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        word = forms[1]
    else:
        word = forms[2]
    return f"{n} {word}"


def fmt_duration_precise(seconds: int) -> str:
    """Каскадный формат из двух старших ненулевых единиц:
    '5 дней 7 часов', '7 часов 8 минут', '8 минут 5 секунд', '5 секунд'."""
    seconds = max(0, int(seconds))
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    d = _plural(days, ("день", "дня", "дней"))
    h = _plural(hours, ("час", "часа", "часов"))
    m = _plural(minutes, ("минута", "минуты", "минут"))
    s = _plural(secs, ("секунда", "секунды", "секунд"))

    if days > 0:
        return f"{d} {h}" if hours > 0 else d
    if hours > 0:
        return f"{h} {m}" if minutes > 0 else h
    if minutes > 0:
        return f"{m} {s}" if secs > 0 else m
    return s


def fmt_duration(seconds: int) -> str:
    """Форматирует секунды в читаемую строку."""
    if seconds >= 2592000 and seconds % 2592000 == 0:
        n = seconds // 2592000
        return f"{n} мес."
    if seconds >= 604800 and seconds % 604800 == 0:
        n = seconds // 604800
        return f"{n} нед."
    if seconds >= 86400 and seconds % 86400 == 0:
        n = seconds // 86400
        return f"{n} дн."
    if seconds >= 3600 and seconds % 3600 == 0:
        n = seconds // 3600
        return f"{n} ч."
    if seconds >= 60:
        n = seconds // 60
        return f"{n} мин."
    return f"{seconds} сек."
