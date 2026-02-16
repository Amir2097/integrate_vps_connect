# Деплой VPN Manager на прод (VPS с WireGuard)

Пошаговая инструкция: развернуть бэкенд, бота и админку на сервере, где уже настроен WireGuard, и привязать выдачу реальных конфигов.

---

## 1. Как устроена авторизация

### Админ-панель (веб)

- **Вход:** логин (`ADMIN_LOGIN`) и пароль. Пароль хранится в `.env` в виде bcrypt-хэша (`ADMIN_PASSWORD_HASH`).
- **После входа:** в cookie выставляется сессия `admin_session` (случайный токен). Сессия хранится **в памяти процесса** (не в БД), живёт 24 часа.
- **REST API** (например для скриптов): отдельная авторизация по JWT (логин/пароль через `POST /auth/login` → в заголовке `Authorization: Bearer <token>`). Секрет подписи — `JWT_SECRET` в `.env`.

### Достаточно ли заходить по IP?

- **Технически:** да. По адресу `http://IP_СЕРВЕРА:8000/admin` можно открыть админку и войти по логину и паролю.
- **Минусы:** пароль и cookie передаются по HTTP в открытом виде. Любой, кто перехватит трафик (сеть, провайдер), увидит учётные данные.
- **Для прода обязательно:** доступ только по **HTTPS** (домен + SSL). Тогда:
  - Трафик шифруется.
  - Лучше привязать доступ к домену и при желании ограничить доступ по IP (firewall) или VPN.

Итого: на проде используй **домен + Nginx + Let's Encrypt** и заходи в админку по `https://твой-домен.ru/admin`. Если домена нет — по IP зайти можно, но пароль будет уходить по открытому каналу (рискованно).

---

## 2. Чек-лист настроек для прода

Перед деплоем подготовь и **никогда не коммить** в Git:

| Переменная | Обязательно на проде | Что сделать |
|------------|----------------------|-------------|
| `ADMIN_LOGIN` | Да | Оставь или смени (логин в админку). |
| `ADMIN_PASSWORD_HASH` | Да | Сгенерировать: `python -c "from app.auth import hash_password; print(hash_password('твой_надёжный_пароль'))"` — вывод в `.env`. |
| `JWT_SECRET` | Да | Длинная случайная строка (например `openssl rand -hex 32`). |
| `INTERNAL_SECRET` | Да | Другая длинная случайная строка; одна и та же в `.env` на сервере для бэкенда и бота. |
| `DATABASE_URL` | Да | Надёжный пароль БД, не дефолтный `postgres`. |
| `BOT_TOKEN` | Да | Токен от @BotFather. |
| `BACKEND_URL` | Да | На той же машине: `http://127.0.0.1:8000` (если снаружи заходим через Nginx по HTTPS). |
| `WG_SCRIPT_PATH` | Да | Полный путь к скрипту на VPS, например `/opt/vpn-manager/scripts/add-wg-client.sh`. |
| `SERVER_ENDPOINT` | Да | Публичный IP или домен этого VPS (попадает в конфиг клиента WireGuard). |
| `ADMIN_TELEGRAM_ID` | Желательно | Твой Telegram ID (уведомления о заявках). |
| `PAYMENT_PHONE` | По желанию | Номер для перевода (отображается в боте). |

Остальные переменные (`WG_CONF_PATH`, `WG_CLIENTS_DIR`, `WG_PORT`, `SUBSCRIPTION_DAYS`, `SUBSCRIPTION_AMOUNT`) — подставь под свой сервер и тарифы.

---

## 3. Требования к серверу

- **ОС:** Ubuntu 22.04 LTS (или 20.04, Debian 11+).
- **Порты:** 80 (HTTP), 443 (HTTPS), 51820/UDP (WireGuard). SSH по своему порту.
- **Уже настроено:** WireGuard (интерфейс `wg0`, конфиг `/etc/wireguard/wg0.conf`). Если ещё нет — сначала выполни [docs/WIREGUARD_SETUP.md](WIREGUARD_SETUP.md).
- На этом же сервере будут: приложение (FastAPI + бот), PostgreSQL, Nginx (обратный прокси + SSL).

---

## 4. Пошаговый деплой

### 4.1. Подключение и обновление

```bash
ssh root@IP_ТВОЕГО_СЕРВЕРА
# или: ssh ubuntu@IP_ТВОЕГО_СЕРВЕРА

apt update && apt upgrade -y
```

### 4.2. Установка зависимостей

```bash
apt install -y python3.11 python3.11-venv python3-pip postgresql nginx certbot python3-certbot-nginx git
```

Проверка PostgreSQL:

```bash
sudo -u postgres psql -c "SELECT version();"
```

### 4.3. База данных

```bash
sudo -u postgres createuser -P vpnapp
# Введи пароль для пользователя vpnapp (запомни для DATABASE_URL)

sudo -u postgres createdb -O vpnapp vpn_manager
```

Проверка:

```bash
sudo -u postgres psql -c "\l" | grep vpn_manager
```

### 4.4. Каталог проекта и код

```bash
mkdir -p /opt/vpn-manager
cd /opt/vpn-manager
git clone https://github.com/ТВОЙ_РЕПО/integrate_vps_connect.git .
# или залей код через scp/rsync
```

Создание venv и установка зависимостей:

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4.5. Файл .env на сервере

```bash
cp .env.example .env
nano .env
```

Заполни **все** переменные для прода (см. раздел 2). Пример минимального прод-набора:

```env
DATABASE_URL=postgresql+asyncpg://vpnapp:ТВОЙ_ПАРОЛЬ_БД@localhost:5432/vpn_manager
ADMIN_LOGIN=admin
ADMIN_PASSWORD_HASH=$2b$12$...   # вывод hash_password()
JWT_SECRET=длинная_случайная_строка_openssl_rand_hex_32
INTERNAL_SECRET=другая_длинная_случайная_строка

BOT_TOKEN=123456:ABC-...
BACKEND_URL=http://127.0.0.1:8000
ADMIN_TELEGRAM_ID=615110136

WG_SCRIPT_PATH=/opt/vpn-manager/scripts/add-wg-client.sh
WG_CONF_PATH=/etc/wireguard/wg0.conf
WG_CLIENTS_DIR=/etc/wireguard/clients
SERVER_ENDPOINT=82.117.84.212
WG_PORT=51820

SUBSCRIPTION_DAYS=30
SUBSCRIPTION_AMOUNT=100
PAYMENT_PHONE=+79001234567
```

Сгенерировать секреты:

```bash
openssl rand -hex 32   # для JWT_SECRET
openssl rand -hex 32   # для INTERNAL_SECRET
```

Хэш пароля админки (на сервере, из каталога проекта с активированным venv):

```bash
source /opt/vpn-manager/venv/bin/activate
cd /opt/vpn-manager
python -c "from app.auth import hash_password; print(hash_password('твой_пароль'))"
```

### 4.6. Скрипт WireGuard и права

Скрипт уже в репозитории: `scripts/add-wg-client.sh`. Его нужно запускать от root (доступ к `/etc/wireguard`, `wg`).

```bash
chmod +x /opt/vpn-manager/scripts/add-wg-client.sh
```

Приложение будет вызывать скрипт через `sudo`. Настроим sudo без пароля только для этого скрипта:

```bash
# Пользователь, от которого будет запускаться uvicorn (обычно отдельный системный пользователь или root)
# Вариант 1: приложение под root (проще, но менее безопасно)
# Тогда просто убедись, что скрипт вызывается с sudo — при запуске от root sudo может не спрашивать пароль.

# Вариант 2: приложение под пользователем vpnapp (рекомендуется)
adduser --disabled-password --gecos "" vpnapp
chown -R vpnapp:vpnapp /opt/vpn-manager
# Разрешить vpnapp запускать только скрипт от root:
echo 'vpnapp ALL=(root) NOPASSWD: /opt/vpn-manager/scripts/add-wg-client.sh' > /etc/sudoers.d/vpn-manager-wg
echo 'vpnapp ALL=(root) NOPASSWD: /usr/bin/wg syncconf wg0 -' >> /etc/sudoers.d/vpn-manager-wg
echo 'vpnapp ALL=(root) NOPASSWD: /usr/bin/wg-quick strip wg0' >> /etc/sudoers.d/vpn-manager-wg
chmod 440 /etc/sudoers.d/vpn-manager-wg
```

В `wireguard.py` скрипт вызывается так: `sudo /opt/vpn-manager/scripts/add-wg-client.sh client_name`. Для `revoke_client` используются `sudo wg syncconf` и `wg-quick strip` — строки выше это разрешают.

Если хочешь упростить первый запуск — можно пока запускать uvicorn и бота от root; тогда `sudo` при вызове скрипта сработает без доп. настроек. Позже переведёшь на пользователя `vpnapp`.

### 4.7. Миграции БД

Таблицы создаются при старте приложения (lifespan). Для уже существующей БД с предыдущими версиями выполни миграции:

```bash
cd /opt/vpn-manager
source venv/bin/activate
sudo -u postgres psql -d vpn_manager -f scripts/migrations/add_display_name.sql
sudo -u postgres psql -d vpn_manager -f scripts/migrations/add_user_is_blocked.sql
sudo -u postgres psql -d vpn_manager -f scripts/migrations/add_payment_months_vpn_block.sql
```

Если БД новая — достаточно одного первого запуска uvicorn (create_all создаст таблицы).

### 4.8. Systemd: бэкенд и бот

Создай два юнита.

**Бэкенд** `/etc/systemd/system/vpn-manager.service`:

```ini
[Unit]
Description=VPN Manager API (FastAPI)
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpn-manager
Environment=PATH=/opt/vpn-manager/venv/bin
ExecStart=/opt/vpn-manager/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Если используешь пользователя `vpnapp`, замени `User=root` на `User=vpnapp`.

**Бот** `/etc/systemd/system/vpn-manager-bot.service`:

```ini
[Unit]
Description=VPN Manager Telegram Bot
After=network.target vpn-manager.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpn-manager
Environment=PATH=/opt/vpn-manager/venv/bin
ExecStart=/opt/vpn-manager/venv/bin/python run_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Подгрузка и запуск:

```bash
systemctl daemon-reload
systemctl enable vpn-manager vpn-manager-bot
systemctl start vpn-manager vpn-manager-bot
systemctl status vpn-manager vpn-manager-bot
```

Проверка API:

```bash
curl -s http://127.0.0.1:8000/
# Должно вернуть {"service":"VPN Manager",...}
```

### 4.9. Nginx и HTTPS (доступ по домену)

Пусть домен указывает на IP сервера (A-запись). Установлен пакет `certbot python3-certbot-nginx`.

Создай конфиг Nginx:

```bash
nano /etc/nginx/sites-available/vpn-manager
```

Подставь свой домен:

```nginx
server {
    listen 80;
    server_name твой-домен.ru www.твой-домен.ru;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Включи сайт и получи сертификат:

```bash
ln -s /etc/nginx/sites-available/vpn-manager /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d твой-домен.ru -d www.твой-домен.ru
```

Certbot сам настроит HTTPS и редирект с HTTP на HTTPS. После этого админка доступна по `https://твой-домен.ru/admin`.

Если домена нет: можно временно заходить по `http://IP:8000/admin`, но тогда открой порт 8000 в файрволе и помни о риске передачи пароля по HTTP.

### 4.10. Файрвол

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 51820/udp
ufw enable
ufw status
```

Порт 8000 наружу не открывай — к приложению доступ только через Nginx (127.0.0.1:8000).

---

## 5. Проверка после деплоя

1. **Главная:** `https://твой-домен.ru/` — JSON с `service: "VPN Manager"`.
2. **Админка:** `https://твой-домен.ru/admin` — логин и пароль из `.env`.
3. **Бот в Telegram:** /start → «Подключиться к VPN» → ввод названия → выбор срока → заявка создаётся; в админке появляется платёж.
4. **Подтверждение оплаты:** в админке нажми «Подтвердить» у тестового платежа — должен создаться реальный peer в WireGuard и пользователю в боте прийти выбор «Текст конфига» / «QR-код». Проверь, что конфиг подключается (Endpoint = SERVER_ENDPOINT, порт 51820).

Если что-то падает — смотри логи:

```bash
journalctl -u vpn-manager -f
journalctl -u vpn-manager-bot -f
```

---

## 6. Обновление кода на сервере

```bash
cd /opt/vpn-manager
git pull
source venv/bin/activate
pip install -r requirements.txt
# При появлении новых миграций:
# sudo -u postgres psql -d vpn_manager -f scripts/migrations/имя_файла.sql
systemctl restart vpn-manager vpn-manager-bot
```

---

## 7. Кратко: что наладить для прода

- **Авторизация:** логин + bcrypt-пароль, сессия в cookie. Доступа по IP по HTTP достаточно только для теста; для прода — только HTTPS (домен + Nginx + Let's Encrypt).
- **Секреты:** свои `JWT_SECRET`, `INTERNAL_SECRET`, пароль БД, хэш пароля админки.
- **Бот:** тот же `BOT_TOKEN`, на сервере `BACKEND_URL=http://127.0.0.1:8000`.
- **WireGuard:** `WG_SCRIPT_PATH` указывает на скрипт на этом VPS; `SERVER_ENDPOINT` — IP или домен этого сервера; скрипт вызывается через sudo (при необходимости настроен sudoers для пользователя приложения).

После выполнения этой инструкции прод-версия развёрнута на сервере и работает с реальными конфигами WireGuard.
