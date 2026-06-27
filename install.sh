#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="drebol-vpn"
ROOT="/root/drebol-vpn"
REPO_URL="${REPO_URL:-https://github.com/pratokwau/drebol-vpn.git}"

if [[ $EUID -ne 0 ]]; then
  echo "Запусти установщик от root."
  exit 1
fi

apt-get update
apt-get install -y git python3 python3-pip python3-venv

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}\.service"; then
  systemctl stop "$SERVICE_NAME" || true
  systemctl disable "$SERVICE_NAME" || true
fi

rm -rf "$ROOT"
git clone "$REPO_URL" "$ROOT"
cd "$ROOT"

python3 install.py
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt

cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Drebol Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/python $ROOT/main.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "Готово. Сервис запущен: $SERVICE_NAME"
