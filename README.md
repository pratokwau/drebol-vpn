# Drebol VPN Bot

Telegram-бот для управления 3x-ui из админского меню.

## Возможности

- установка одной командой из GitHub
- первичная настройка через `install.py`
- ввод `TOKEN` бота и `ADMIN_ID`
- команда `/start`
- админская команда `/adminxui`
- настройка подключения к 3x-ui:
  - `XUI_URL`
  - `XUI_TOKEN`
- автозапуск через `systemd`

## Установка

```bash
bash <(curl -Ls https://raw.githubusercontent.com/pratokwau/drebol-vpn/main/install.sh)
```

Во время установки бот попросит:

1. токен Telegram-бота
2. `ADMIN_ID` администратора

После этого установщик:

- создаст `.env`
- установит зависимости
- создаст сервис `systemd`
- включит автозапуск после перезагрузки сервера

## Автозапуск

Да, бот ставится в автозагрузку.

В `install.sh` создаётся сервис `systemd`, после чего выполняются команды:

- `systemctl daemon-reload`
- `systemctl enable drebolbot`
- `systemctl restart drebolbot`

Это означает, что после рестарта сервера бот поднимется сам.

## Первичная настройка

Если хочешь запустить настройку вручную:

```bash
python3 install.py
```

`install.py` создаст:

- `.env`
- `data/authorized.json`
- `data/settings.json`
- `data/xui_settings.json`

## Команды

### Пользовательские

- `/start` - главное меню
- `/cancel` - отмена действия

### Админские

- `/adminxui` - панель настройки 3x-ui

## Настройка 3x-ui

Открой `/adminxui`, затем:

1. нажми `🔧 XUI`
2. выбери настройку URL или токена
3. сохрани значения
4. открой `📡 Инбаунды`

## Структура

- `main.py` - точка входа
- `install.sh` - установка и systemd-сервис
- `install.py` - первичная настройка
- `config.py` - переменные окружения
- `xui/` - логика админки и работы с 3x-ui
- `handlers/` - основные команды бота

## Примечания

- бот работает через long polling
- для работы нужен рабочий Telegram bot token
- `ADMIN_ID` должен быть числом
- для доступа к панели 3x-ui нужен корректный `URL` и API token

## Публикация в GitHub

Если меняешь имя репозитория, не забудь обновить ссылку в:

- `install.sh`
- README-команде установки выше

