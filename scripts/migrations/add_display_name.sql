-- Добавить поля display_name для названия конфига от пользователя (бот).
-- Выполнить один раз на существующей БД: psql -f add_display_name.sql ...

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS display_name VARCHAR(128) NULL;
ALTER TABLE vpn_clients ADD COLUMN IF NOT EXISTS display_name VARCHAR(128) NULL;
