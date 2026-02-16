# Внедрение изменений (миграции и запуск)

## 1. База данных

**Если БД уже существует** — выполните миграции для новых колонок:

```bash
# Из корня проекта (по порядку):
psql "postgresql://USER:PASSWORD@HOST:PORT/DATABASE" -f scripts/migrations/add_display_name.sql
psql "postgresql://USER:PASSWORD@HOST:PORT/DATABASE" -f scripts/migrations/add_user_is_blocked.sql
psql "postgresql://USER:PASSWORD@HOST:PORT/DATABASE" -f scripts/migrations/add_payment_months_vpn_block.sql
```

Или через Docker:  
`docker exec -i vpn-pg psql -U postgres -d vpn_manager < scripts/migrations/add_payment_months_vpn_block.sql`

**Если БД создаётся с нуля** — ничего делать не нужно: `create_all` при старте приложения создаст таблицы со всеми полями.

---

## 2. Переменные окружения (.env)

Убедитесь, что заданы:

- **INTERNAL_SECRET** — одна и та же длинная случайная строка для бэкенда и бота (для подтверждения оплаты кнопками в Telegram).  
  Пример: `INTERNAL_SECRET=ваш-длинный-секрет-из-букв-и-цифр`

Остальное по необходимости (BOT_TOKEN, BACKEND_URL, ADMIN_TELEGRAM_ID, DATABASE_URL и т.д.).

---

## 3. Запуск сервисов

1. **Бэкенд** (FastAPI):
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Бот** (отдельный процесс):
   ```bash
   python run_bot.py
   ```

После этого:
- при активации подписки пользователь получит выбор «Текст конфига» / «QR-код»;
- при «Подключиться к VPN» бот спросит название конфига;
- «Моя подписка» покажет список всех подписок с датами и статусами.
