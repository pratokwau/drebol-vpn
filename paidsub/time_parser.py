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
