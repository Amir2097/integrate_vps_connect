#!/bin/bash
# Добавление нового WireGuard-клиента и вывод QR-кода конфига.
# Запуск на сервере: sudo ./add-wg-client.sh [имя_клиента] [IP_или_домен_VPS]
# Пример: sudo ./add-wg-client.sh friend1 82.117.84.212

set -e

# Пути можно задать через переменные окружения (при вызове из приложения передаются из .env)
WG_CONF="${WG_CONF:-/etc/wireguard/wg0.conf}"
WG_SUBNET="10.66.0"
CLIENT_NAME="${1:-client}"
SERVER_ENDPOINT="${2:-$SERVER_ENDPOINT}"
# Третий аргумент "1" — сделать конфиг читаемым для приложения (chmod 644), когда скрипт вызывается через sudo от amir
READABLE_BY_APP_ARG="${3:-}"
WORKDIR="${WG_CLIENTS_DIR:-/etc/wireguard/clients}"

if [ -z "$SERVER_ENDPOINT" ]; then
  echo "Укажи IP или домен сервера: $0 <имя_клиента> <IP_или_домен>"
  echo "Пример: $0 friend1 82.117.84.212"
  exit 1
fi

# Порт WireGuard (должен совпадать с ListenPort в wg0.conf)
WG_PORT="${WG_PORT:-51820}"

# Проверка root (при вызове из systemd/Python PATH может быть пустым — используем полный путь к id)
# Если задано WG_SKIP_ROOT_CHECK=1 — не требовать root (скрипт запускается от пользователя с правами на WG)
if [ "${WG_SKIP_ROOT_CHECK}" != "1" ]; then
  if [ "$(/usr/bin/id -u 2>/dev/null)" != "0" ]; then
    echo "Запусти скрипт с sudo или задай WG_SKIP_ROOT_CHECK=1 при запуске от пользователя с правами на WireGuard."
    exit 1
  fi
fi

if [ ! -f "$WG_CONF" ]; then
  echo "Не найден $WG_CONF. Сначала настрой WireGuard по инструкции."
  exit 1
fi

# Следующий свободный IP: ищем максимальный 10.66.0.X в AllowedIPs
NEXT_IP=2
if grep -q "AllowedIPs = $WG_SUBNET\." "$WG_CONF"; then
  MAX=$(grep "AllowedIPs = $WG_SUBNET\." "$WG_CONF" | sed -n "s/.*$WG_SUBNET\.\([0-9]*\).*/\1/p" | sort -n | tail -1)
  [ -n "$MAX" ] && NEXT_IP=$((MAX + 1))
fi

CLIENT_IP="$WG_SUBNET.$NEXT_IP"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

# Генерация ключей клиента
CLIENT_PRIVATE=$(wg genkey)
CLIENT_PUBLIC=$(echo "$CLIENT_PRIVATE" | wg pubkey)

# Публичный ключ сервера (интерфейс должен быть поднят или ключ в файле)
if wg show wg0 public-key &>/dev/null; then
  SERVER_PUBLIC=$(wg show wg0 public-key)
else
  [ -f /etc/wireguard/server_public.key ] && SERVER_PUBLIC=$(cat /etc/wireguard/server_public.key) || {
    echo "Не удалось получить публичный ключ сервера (wg0 не запущен или нет server_public.key)."
    exit 1
  }
fi

# Добавление peer в конфиг
PEER_BLOCK="
[Peer]
# $CLIENT_NAME
PublicKey = $CLIENT_PUBLIC
AllowedIPs = $CLIENT_IP/32
"
echo "$PEER_BLOCK" >> "$WG_CONF"

# Применение конфига без перезапуска всего интерфейса
if wg show wg0 &>/dev/null; then
  wg syncconf wg0 <(wg-quick strip wg0)
else
  echo "Интерфейс wg0 не поднят. Выполни: wg-quick up wg0"
fi

# Сборка конфига клиента
CLIENT_CONF="[Interface]
PrivateKey = $CLIENT_PRIVATE
Address = $CLIENT_IP/32
DNS = 1.1.1.1, 1.0.0.1

[Peer]
PublicKey = $SERVER_PUBLIC
Endpoint = $SERVER_ENDPOINT:$WG_PORT
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"

CONF_FILE="$WORKDIR/${CLIENT_NAME}.conf"
echo "$CLIENT_CONF" > "$CONF_FILE"
# По умолчанию только root. Если скрипт вызывается из приложения (sudo), приложение потом читает файл от пользователя (amir) — тогда делаем читаемым. Поддержка: env WG_READABLE_BY_APP=1 или третий аргумент "1".
if [ "${WG_READABLE_BY_APP}" = "1" ] || [ "$READABLE_BY_APP_ARG" = "1" ]; then
  chmod 644 "$CONF_FILE"
else
  chmod 600 "$CONF_FILE"
fi
echo "----------------------------------------"
echo "Клиент: $CLIENT_NAME"
echo "VPN IP:  $CLIENT_IP/32"
echo "Конфиг:  $CONF_FILE"
echo "----------------------------------------"

# QR-код в терминал (удобно по SSH)
if command -v qrencode &>/dev/null; then
  echo ""
  echo "QR-код (скань приложением WireGuard на телефоне):"
  echo ""
  qrencode -t ansiutf8 < "$CONF_FILE"
  echo ""
  echo "Или сохрани в PNG: qrencode -t png -o $CLIENT_NAME.png < $CONF_FILE"
else
  echo "Для QR установи qrencode: apt install qrencode"
  echo "Затем: qrencode -t ansiutf8 < $CONF_FILE"
  echo "Или скачай конфиг и сгенерируй QR на ПК."
fi

# Для приложения: вывести ключ и IP клиента (в .conf в [Peer] — ключ сервера, не клиента)
echo "WG_CLIENT_PUBLIC_KEY=$CLIENT_PUBLIC"
echo "WG_CLIENT_IP=$CLIENT_IP"

echo ""
echo "Готово. Конфиг для ручной выдачи: $CONF_FILE"
