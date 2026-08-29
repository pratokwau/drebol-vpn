#!/bin/bash
set -e

REPO_URL="https://github.com/pratokwau/drebol-vpn.git"
INSTALL_DIR="/root/drebol-vpn"
SERVICE_NAME="drebol-vpn"
PYTHON="python3"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    error "Запустите скрипт с правами root: sudo bash install.sh"
fi

info "Обновление пакетов..."
apt-get update -qq

info "Установка зависимостей (git, python3, pip)..."
apt-get install -y -qq git python3 python3-pip python3-venv

if [ -d "$INSTALL_DIR" ]; then
    warn "Директория $INSTALL_DIR уже существует. Обновляем репозиторий..."
    git -C "$INSTALL_DIR" pull
else
    info "Клонирование репозитория..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

info "Создание виртуального окружения..."
$PYTHON -m venv venv
source venv/bin/activate

info "Установка Python-зависимостей..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# --- Запрос конфигурации ---
echo ""
echo "========================================"
echo "         Настройка Drebol VPN Bot"
echo "========================================"
echo ""

if [ -f .env ]; then
    warn "Файл .env уже существует. Пропускаем настройку."
    warn "Чтобы изменить конфиг, отредактируйте $INSTALL_DIR/.env"
else
    read -rp "Введите токен Telegram-бота (от @BotFather): " BOT_TOKEN </dev/tty
    if [ -z "$BOT_TOKEN" ]; then
        error "Токен бота не может быть пустым."
    fi

    read -rp "Введите ваш Telegram ID (администратора): " ADMIN_ID </dev/tty
    if ! [[ "$ADMIN_ID" =~ ^[0-9]+$ ]]; then
        error "Telegram ID должен состоять только из цифр."
    fi

    cat > .env <<EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
EOF
    info "Конфиг сохранён в $INSTALL_DIR/.env"
fi

# --- Создание systemd-сервиса ---
info "Создание systemd-сервиса..."

cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Drebol VPN Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
info "========================================"
info "  Drebol VPN Bot успешно установлен!"
info "========================================"
info "Статус:   systemctl status $SERVICE_NAME"
info "Логи:     journalctl -u $SERVICE_NAME -f"
info "Стоп:     systemctl stop $SERVICE_NAME"
info "Конфиг:   $INSTALL_DIR/.env"
echo ""
