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

Есть два варианта.

**Вариант A: запуск через sudo** (по умолчанию, `WG_USE_SUDO=true` в `.env`).  
Скрипт лежит, например, в проекте: `scripts/add-wg-client.sh`. Его вызывает процесс через `sudo`, поэтому нужны права sudo без пароля для этого скрипта и для `wg syncconf` / `wg-quick strip` (см. примеры sudoers в старых версиях инструкции).

**Вариант B: запуск без sudo** (пользователь процесса имеет прямые права на скрипт и каталог WireGuard).  
На сервере скрипт стоит, например, в `/usr/local/bin/add-wg-client.sh`, пользователь `amir` может запускать его напрямую и имеет доступ к `/etc/wireguard` (чтение/запись `wg0.conf`, каталог `clients`). В `.env` задаёшь:

```env
WG_SCRIPT_PATH=/usr/local/bin/add-wg-client.sh
WG_USE_SUDO=false
```

Сервис systemd должен запускаться от этого же пользователя (`User=amir` в unit). Тогда приложение вызывает скрипт и команды `wg` / `wg-quick` **без** `sudo` — окружение systemd не мешает, конфликта с sudo нет.

Скрипт `add-wg-client.sh` по умолчанию проверяет `id -u = 0` (root). Если запускаешь без sudo от пользователя `amir`, либо убери эту проверку в своей копии скрипта в `/usr/local/bin/`, либо выдай amir права на запись в `/etc/wireguard` и на выполнение `wg` (например, через группу или setcap).

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
# Явно подгрузить .env (нужно бэкенду для BOT_TOKEN — отправка сообщений пользователю после подтверждения оплаты)
EnvironmentFile=/opt/vpn-manager/.env
Environment=PATH=/opt/vpn-manager/venv/bin
ExecStart=/opt/vpn-manager/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Важно: без `EnvironmentFile` или без корректного `WorkingDirectory` процесс может не увидеть `BOT_TOKEN` из `.env`, и после подтверждения оплаты пользователь не получит сообщение в Telegram (бот при этом работает, т.к. запускается отдельным процессом со своим чтением `.env`).

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

---

## 8. Ошибка при подтверждении оплаты: уведомление и конфиг не приходят

**Симптомы:** после нажатия «Подтвердить» в админке пользователь не получает в Telegram сообщение с выбором конфига, конфиг не работает.

**Причина:** приложение вызывает скрипт WireGuard (`add-wg-client.sh`). Если вызов падает (скрипт не найден, нет прав, ошибка внутри скрипта), конфиг не создаётся и сообщение пользователю не отправляется. Ошибка пишется в логи и в поле «Заметка» подтверждённого платежа в админке.

### Что проверить по шагам

1. **Логи бэкенда** (сразу после подтверждения оплаты):
   ```bash
   journalctl -u vpn-manager -n 100 --no-pager
   ```
   Ищи строки `[WG] add_client failed:` или `[WG] Script not found at ...` — по ним видно причину.

2. **Админка → подписки/платежи:** открой уже подтверждённый платёж и посмотри поле «Заметка» (admin_notes). Если там есть `[WG error: ...]` — текст после него и есть ошибка (например «Script failed: ...» или «Config file not created»).

3. **Переменные в `.env` на сервере** (без лишних пробелов и кавычек):
   - `WG_SCRIPT_PATH` — **полный путь** к скрипту, например `/opt/vpn-manager/scripts/add-wg-client.sh`. Путь должен быть таким, как на самом сервере (где лежит проект).
   - `WG_CLIENTS_DIR=/etc/wireguard/clients` — каталог, куда скрипт пишет `.conf` файлы (должен совпадать с тем, что внутри скрипта).
   - `WG_CONF_PATH=/etc/wireguard/wg0.conf` — конфиг интерфейса WireGuard.
   - `SERVER_ENDPOINT` — IP или домен этого VPS (как в конфиге клиента).

4. **Скрипт на месте и запускается вручную:**
   ```bash
   ls -la /opt/vpn-manager/scripts/add-wg-client.sh
   sudo /opt/vpn-manager/scripts/add-wg-client.sh testclient1 82.117.84.212
   ```
   Подставь свой `SERVER_ENDPOINT` вместо `82.117.84.212`. Если команда падает — исправь окружение WireGuard (права, ключи, `wg0` поднят). Если выполняется без ошибок — проверь, что в `.env` указан **тот же** путь в `WG_SCRIPT_PATH`.

5. **Права на запуск от пользователя systemd:** бэкенд (uvicorn) запускается от пользователя из `User=` в `vpn-manager.service`. Этот пользователь должен иметь возможность выполнить:
   ```bash
   sudo /opt/vpn-manager/scripts/add-wg-client.sh testclient2 $(grep SERVER_ENDPOINT /opt/vpn-manager/.env | cut -d= -f2)
   ```
   без ввода пароля. Если пароль спрашивается — настрой sudoers (см. раздел 4.6). Либо временно запускай сервис от root (`User=root` в unit), тогда `sudo` сработает без доп. настроек.

6. **Чтение созданного конфига:** после успешного запуска скрипт создаёт файл в `WG_CLIENTS_DIR`, например `/etc/wireguard/clients/user1_1.conf`. Пользователь, от которого работает uvicorn, должен иметь право **читать** этот каталог и файлы (скрипт создаёт их от root; если uvicorn не root — дай права на чтение: `chmod 755 /etc/wireguard/clients` и на созданные файлы, или запускай uvicorn от root).

### Бот и config.py

- **Отдельный `.env` для бота не нужен.** Бот и бэкенд на одном сервере используют один и тот же каталог и один `.env`. В нём должны быть заполнены и `BOT_TOKEN`, и все переменные для бэкенда.
- **`config.py` не заполняешь вручную** — он читает настройки из `.env` через pydantic-settings. Достаточно правильного `.env` в корне проекта.

### После исправления

Перезапусти бэкенд и снова подтверди платёж (или создай новую тестовую заявку и подтверди её):

```bash
systemctl restart vpn-manager
```
