# VPN Manager — веб-сервис и бот

Управление пользователями WireGuard: подписки, ручное подтверждение оплаты, Telegram-бот, админ-панель.

## Стек

- **Backend:** FastAPI, SQLAlchemy 2 (async), PostgreSQL
- **Админка:** FastAPI + Jinja2 (логин по паролю, cookie)
- **Бот:** aiogram 3
- **Планировщик:** APScheduler (проверка истечения подписок раз в час)
- **WireGuard:** вызов `scripts/add-wg-client.sh` при подтверждении оплаты

## Структура БД

- **users** — telegram_id, username, full_name, is_admin
- **subscriptions** — user_id, status (pending_payment | active | expired | cancelled), started_at, expires_at
- **payments** — user_id, subscription_id, amount, status (pending | confirmed | rejected), admin_notes, confirmed_at, confirmed_by
- **vpn_clients** — user_id, name, wg_public_key, wg_private_key, allowed_ip, config_content

## PostgreSQL локально (Windows)

Варианты развернуть PostgreSQL для разработки:

**1. Официальный установщик (удобно и привычно)**  
- Скачай с [postgresql.org/download/windows](https://www.postgresql.org/download/windows/) (например EDB Installer).  
- При установке задай пароль суперпользователя `postgres`, порт 5432.  
- После установки в меню «Пуск» будет «pgAdmin» и «SQL Shell (psql)».  
- В psql или pgAdmin выполни: `CREATE DATABASE vpn_manager;`  
- В `.env`: `DATABASE_URL=postgresql+asyncpg://postgres:ТВОЙ_ПАРОЛЬ@localhost:5432/vpn_manager`

**2. Docker (если уже стоит Docker Desktop)**  
```bash
docker run -d --name vpn-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
```  
Через пару секунд база готова. Создай БД:  
`docker exec -it vpn-pg psql -U postgres -c "CREATE DATABASE vpn_manager;"`  
В `.env`: `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/vpn_manager`

**3. WSL + Ubuntu**  
Если разработка в WSL: `sudo apt install postgresql`, затем `sudo -u postgres createdb vpn_manager` и в `.env` хост по желанию `localhost` (если бэкенд в WSL) или IP WSL-интерфейса с Windows.

---

## Как всё связывается с сервером

Схема такая:

- **Локально (разработка):**  
  - Приложение на твоём ПК подключается к PostgreSQL (локально или в Docker) по `DATABASE_URL`.  
  - Бот и админка работают с этим же бэкендом.  
  - WireGuard на ПК нет — в `.env` оставляешь `WG_SCRIPT_PATH=` пустым: при «подтверждении оплаты» создаётся мок-конфиг, без реального peer на VPS.

- **На сервере (прод):**  
  - Backend, бот и (по желанию) PostgreSQL крутятся на **одном VPS** (том же, где WireGuard).  
  - `DATABASE_URL` — либо `postgresql+asyncpg://...@localhost:5432/vpn_manager` (если PostgreSQL на этом же VPS), либо адрес отдельного сервера БД.  
  - `WG_SCRIPT_PATH=/root/add-wg-client.sh` (или где лежит скрипт) — бэкенд **напрямую** вызывает этот скрипт на той же машине (subprocess), добавляет peer в `wg0.conf` и отдаёт конфиг пользователю. Отдельного «связывания с сервером» не нужно: приложение и WireGuard на одном хосте.

Итого: связь с «сервером» — это **подключение к PostgreSQL** по `DATABASE_URL` и (на VPS) **локальный вызов скрипта** по `WG_SCRIPT_PATH`. Отдельного API между твоим приложением и VPS не требуется, если backend крутится на том же VPS, что и WG.

---

## Настройки .env: локально и на сервере

| Переменная | Локально (разработка) | На VPS (прод) |
|------------|------------------------|---------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:пароль@localhost:5432/vpn_manager` | То же, если PostgreSQL на этом VPS; иначе хост — IP/домен сервера БД |
| `BACKEND_URL` | `http://localhost:8000` | `https://твой-домен.ru` или `http://127.0.0.1:8000` (если бот на той же машине) |
| `WG_SCRIPT_PATH` | Пусто | `/root/add-wg-client.sh` (полный путь к скрипту на этом VPS) |
| `WG_CONF_PATH` | Не важно | `/etc/wireguard/wg0.conf` |
| `WG_CLIENTS_DIR` | Не важно | `/etc/wireguard/clients` |
| `SERVER_ENDPOINT` | Любой (для мока) | Публичный IP или домен этого VPS (попадает в конфиг клиента) |
| `BOT_TOKEN` | Токен от @BotFather (тот же можно) | Тот же токен |
| `ADMIN_PASSWORD_HASH`, `JWT_SECRET` | Для теста любые | Обязательно свои, сложные |

---

## Локальный запуск с нуля (этот ПК)

Ниже — полная последовательность: Docker PostgreSQL → venv и библиотеки → .env → запуск.

### 1. PostgreSQL в Docker

```powershell
docker run -d --name vpn-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
```

Через несколько секунд создать БД:

```powershell
docker exec -it vpn-pg psql -U postgres -c "CREATE DATABASE vpn_manager;"
```

В `.env` должна быть строка (если пароль `postgres`):

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/vpn_manager
```

Таблицы (`users`, `subscriptions`, `payments`, `vpn_clients`) создаются автоматически при первом запуске бэкенда (lifespan в `app.main`). Если на другом ПК уже применялись миграции (например, `add_display_name.sql`), на чистой БД это не обязательно — модели уже содержат нужные поля.

При необходимости выполнить миграции вручную (если подключаешься к старой БД без новых колонок):

```powershell
# Подставь свои USER, PASSWORD, HOST, PORT, DATABASE
psql "postgresql://postgres:postgres@localhost:5432/vpn_manager" -f scripts/migrations/add_display_name.sql
```

Или через Docker:

```powershell
docker exec -i vpn-pg psql -U postgres -d vpn_manager < scripts/migrations/add_display_name.sql
```

### 2. Виртуальное окружение и зависимости

```powershell
cd c:\Users\Amir\PycharmProjects\integrate_vps_connect
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 3. База и .env

После того как PostgreSQL запущен и база `vpn_manager` создана (см. выше), скопируй `.env.example` в `.env` и подставь свой `DATABASE_URL` (логин/пароль/порт). Файл `.env` ты уже перенёс — проверь, что `DATABASE_URL` указывает на локальный контейнер: `postgresql+asyncpg://postgres:postgres@localhost:5432/vpn_manager`.

### 4. Остальные переменные в .env

Скопируй пример: `copy .env.example .env`. Обязательно для админки:

- `ADMIN_LOGIN` — логин входа (например `admin`)
- `ADMIN_PASSWORD_HASH` — хэш пароля (см. ниже)
- `JWT_SECRET` — любая длинная строка для подписи токенов

Сгенерировать хэш пароля:

```bash
python -c "from app.auth import hash_password; print(hash_password('твой_пароль'))"
```

Вставь вывод в `.env` как `ADMIN_PASSWORD_HASH=...`.

Для бота:

- `BOT_TOKEN` — токен от @BotFather
- `BACKEND_URL` — URL бэкенда (локально: `http://localhost:8000`)

Для теста без WireGuard на ПК оставь `WG_SCRIPT_PATH` пустым — будет мок (конфиг не реальный).

### 5. Запуск бэкенда

```bash
venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Таблицы создадутся при первом запросе (lifespan). Открой: http://localhost:8000 — главная, http://localhost:8000/admin — админка, http://localhost:8000/docs — Swagger.

### 6. Запуск бота и проверка Telegram

В `.env` должны быть заданы:
- `BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather) (команда /newbot).
- `BACKEND_URL=http://localhost:8000` — бот дергает API по этому адресу.

**Запуск бота (второй терминал, бэкенд уже крутится):**

```bash
venv\Scripts\activate
python run_bot.py
```

В консоли должно появиться что-то вроде «Started polling» без ошибок. Если видишь «Update skip» или ошибки — проверь, что бэкенд доступен по `BACKEND_URL` и что БД запущена.

**Как проверить в Telegram:**

1. Найди своего бота по имени (то, что задал в BotFather) или открой ссылку `https://t.me/ИМЯ_ТВОЕГО_БОТА`.
2. Нажми **Start** или отправь `/start` — бот зарегистрирует тебя и покажет кнопки.
3. Нажми **«Подключиться к VPN»** — в БД создастся заявка (pending), в админке http://localhost:8000/admin появится платёж на подтверждение.
4. Нажми **«Я оплатил»** — бот ответит, что нужно ждать подтверждения.
5. В админке нажми **«Подтвердить»** у этого платежа — бот отправит тебе в чат конфиг (мок, если `WG_SCRIPT_PATH` пустой).
6. **«Моя подписка»** — статус подписки; **«Получить конфиг»** — повторно выдать конфиг.

Если бот не отвечает — смотри вывод `python run_bot.py` и что бэкенд отвечает на http://localhost:8000/docs (проверь, например, GET /api/user/by-telegram/ТВОЙ_TELEGRAM_ID/subscription, подставив свой ID).

## Авторизация и доступ к админке

- **Вход в админку:** логин (`ADMIN_LOGIN`) и пароль. Пароль в `.env` хранится как bcrypt-хэш (`ADMIN_PASSWORD_HASH`). После входа в cookie выставляется сессия `admin_session` (хранится в памяти процесса, 24 ч).
- **Доступ по IP:** зайти по `http://IP:8000/admin` можно, но пароль и cookie передаются по HTTP в открытом виде. **Для прода обязательно использовать HTTPS** (домен + Nginx + Let's Encrypt) — см. [docs/DEPLOY_PROD.md](docs/DEPLOY_PROD.md).
- **REST API** (для скриптов): JWT через `POST /auth/login` → заголовок `Authorization: Bearer <token>`. Секрет подписи — `JWT_SECRET`.

---

## Деплой на VPS (прод)

**Подробная пошаговая инструкция:** [docs/DEPLOY_PROD.md](docs/DEPLOY_PROD.md) — установка зависимостей, PostgreSQL, клонирование проекта, настройка `.env`, скрипт WireGuard и sudo, миграции БД, systemd (бэкенд + бот), Nginx с SSL, файрвол.

Кратко:
- Установи PostgreSQL, Python 3.11+, Nginx, скопируй проект и `scripts/add-wg-client.sh` на сервер.
- В `.env` укажи реальные секреты и пути: `DATABASE_URL`, `ADMIN_PASSWORD_HASH`, `JWT_SECRET`, `INTERNAL_SECRET`, `BOT_TOKEN`, `BACKEND_URL=http://127.0.0.1:8000`, `WG_SCRIPT_PATH=/path/to/add-wg-client.sh`, `SERVER_ENDPOINT`.
- Запуск через systemd: `uvicorn app.main:app --host 127.0.0.1 --port 8000` (доступ снаружи только через Nginx по HTTPS), отдельно — `python run_bot.py`.

## Полезные эндпоинты

- `POST /api/register` — регистрация по telegram_id (вызывается ботом при /start)
- `POST /api/payment/request` — создать заявку (body: `{"telegram_id": 123}`)
- `GET /api/user/by-telegram/{id}/subscription` — статус подписки
- `GET /api/user/by-telegram/{id}/vpn-config` — конфиг для выдачи в боте
- `GET /admin` — дашборд (после логина)
- `POST /auth/login` — логин для API (form: username, password) → JWT для заголовка Authorization

---

## Работа с проектом на нескольких ПК (в т.ч. в Cursor)

Чтобы одинаково разрабатывать проект на разных компьютерах:

1. **Код — только в Git**
   - Все изменения кода храни в репозитории: `git add`, `git commit`, `git push` на одном ПК; на другом — `git pull`.
   - Не коммить `.env` (он уже в `.gitignore`) — на каждом ПК свой локальный `.env`.

2. **Локальные настройки на каждом ПК**
   - На каждом компьютере: свой `venv` (или переиспользуй один и тот же путь), свой `.env` (скопировал с другого ПК или собрал из `.env.example`).
   - PostgreSQL: на каждом ПК либо свой локальный Docker/установленный PostgreSQL, либо (реже) общая удалённая БД — тогда в `.env` на всех ПК один и тот же `DATABASE_URL`.

3. **Cursor**
   - Открывай одну и ту же папку проекта (клон репозитория). Cursor хранит настройки workspace в `.vscode/` — имеет смысл часть настроек (например, рекомендуемые расширения) закоммитить, а личные — оставить только локально.
   - Правила и подсказки для AI можно держать в репозитории: файлы в `.cursor/rules/` или корневой `AGENTS.md` — тогда на всех ПК при открытии проекта будет один и тот же контекст.

4. **Чек-лист при переходе на другой ПК**
   - `git pull` — подтянуть последний код.
   - Скопировать/проверить `.env` (или создать из `.env.example`).
   - Запустить PostgreSQL (Docker или сервис), при необходимости создать БД и применить миграции.
   - `python -m venv venv` (если venv ещё нет), `pip install -r requirements.txt`.
   - Запуск: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` и в другом терминале `python run_bot.py`.

Итого: код и общие настройки — в Git; секреты и локальные пути — в `.env` на каждой машине; БД — локально на каждом ПК или одна общая, по желанию.
