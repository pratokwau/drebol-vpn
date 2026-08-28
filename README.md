# Drebol VPN Bot

Telegram-бот для продажи VPN-подписок.

## Быстрая установка на Ubuntu-сервер

Одна команда — скачает, установит и запустит бота с автостартом:

```bash
curl -fsSL https://raw.githubusercontent.com/pratokwau/drebol-vpn/main/install.sh | sudo bash
```

> Скрипт спросит токен бота и ваш Telegram ID при первой установке.

---

## Что делает скрипт установки

- Устанавливает `git`, `python3`, `pip`, `venv`
- Клонирует репозиторий в `/opt/drebol-vpn`
- Создаёт виртуальное окружение и ставит зависимости
- Спрашивает токен бота и Telegram ID администратора
- Создаёт `systemd`-сервис с автозапуском при перезагрузке/падении

---

## Управление ботом

```bash
# Статус
systemctl status drebol-vpn

# Логи в реальном времени
journalctl -u drebol-vpn -f

# Перезапуск
systemctl restart drebol-vpn

# Остановка
systemctl stop drebol-vpn
```

---

## Ручная установка (без curl)

```bash
git clone https://github.com/pratokwau/drebol-vpn.git
cd drebol-vpn
sudo bash install.sh
```

---

## Конфигурация

После установки настройки хранятся в `/opt/drebol-vpn/.env`:

```env
BOT_TOKEN=ваш_токен_от_BotFather
ADMIN_ID=ваш_telegram_id
```

После изменения `.env` перезапустите бота:

```bash
systemctl restart drebol-vpn
```

---

## Команды бота

| Команда  | Описание                  |
|----------|---------------------------|
| `/start` | Главное меню              |
| `/help`  | Список команд             |
| `/admin` | Панель администратора     |

---

## Структура проекта

```
drebol-vpn/
├── bot.py            # Основной код бота
├── requirements.txt  # Python-зависимости
├── install.sh        # Скрипт установки на Ubuntu
├── .env.example      # Пример конфигурации
└── README.md
```
