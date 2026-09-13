#!/usr/bin/env bash
# Сторож бота: сообщает админу в Telegram, что бот упал.
#
# systemd запускает скрипт как ExecStopPost — после КАЖДОЙ остановки сервиса.
# OnFailure тут не подходит: при Restart=always и паузе в 5 секунд systemd
# не переводит сервис в failed, и крэш-цикл идёт молча и бесконечно.
#
# Скрипт не зависит ни от Python, ни от кода бота — поэтому уведомление уйдёт,
# даже если бот не может даже стартовать (например, из-за ошибки импорта).

set -u

UNIT="${1:-drebol-vpn.service}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$DIR/.env"
STATE_DIR="${ALERT_STATE_DIR:-/var/lib/drebol-vpn}"
STAMP="$STATE_DIR/last_alert"
MARKER="$STATE_DIR/crashed"
COOLDOWN="${ALERT_COOLDOWN:-600}"

# Штатная остановка или перезапуск (systemctl stop/restart, обновление) — не авария.
if [ "${SERVICE_RESULT:-success}" = "success" ]; then
  exit 0
fi

getenv() {
  grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
          -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

BOT_TOKEN="$(getenv BOT_TOKEN)"
ADMIN_ID="$(getenv ADMIN_ID)"
if [ -z "$BOT_TOKEN" ] || [ -z "$ADMIN_ID" ]; then
  exit 0
fi

mkdir -p "$STATE_DIR"
# метка для бота: поднявшись, он сообщит, что снова работает
touch "$MARKER"

# в крэш-цикле сервис падает каждые несколько секунд — не заваливаем сообщениями
now=$(date +%s)
last=$(cat "$STAMP" 2>/dev/null || echo 0)
if [ $((now - last)) -lt "$COOLDOWN" ]; then
  exit 0
fi
echo "$now" > "$STAMP"

restarts=$(systemctl show -p NRestarts --value "$UNIT" 2>/dev/null)
logs=$(journalctl -u "$UNIT" -n 20 --no-pager -o cat 2>/dev/null | tail -c 2500)

text="🔴 Бот упал

Причина: ${SERVICE_RESULT:-?}, код ${EXIT_STATUS:-?}
Перезапусков: ${restarts:-?}
Сервер: $(hostname)

Последние строки лога:
${logs:-нет данных}"

curl -s --max-time 15 \
  "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${ADMIN_ID}" \
  --data-urlencode "text=${text}" \
  >/dev/null 2>&1 || true

exit 0
