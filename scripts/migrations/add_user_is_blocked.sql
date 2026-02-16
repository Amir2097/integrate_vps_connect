-- Блокировка пользователя админом (доступ приостановлен, конфиг не удаляется).
-- Выполнить один раз на существующей БД: psql "postgresql://..." -f add_user_is_blocked.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE;
