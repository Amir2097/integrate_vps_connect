-- Срок подписки в месяцах (1, 3, 5, 12) и блокировка по конфигу.
-- Выполнить один раз: psql "postgresql://..." -f add_payment_months_vpn_block.sql

-- Платёж: на сколько месяцев оформлена подписка
ALTER TABLE payments ADD COLUMN IF NOT EXISTS subscription_months INTEGER NOT NULL DEFAULT 1;

-- VPN-клиент: связь с подпиской и флаг блокировки конфига
ALTER TABLE vpn_clients ADD COLUMN IF NOT EXISTS subscription_id INTEGER NULL REFERENCES subscriptions(id) ON DELETE SET NULL;
ALTER TABLE vpn_clients ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_vpn_clients_subscription_id ON vpn_clients(subscription_id);
