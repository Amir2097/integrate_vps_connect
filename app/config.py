from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/vpn_manager"
    admin_login: str = "admin"
    admin_password_hash: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    bot_token: str = ""
    backend_url: str = "http://localhost:8000"
    # Telegram ID админа для уведомлений (новая заявка, «Я оплатил»). Узнать свой ID: @userinfobot
    admin_telegram_id: str = "615110136"
    # Секрет для внутренних вызовов (бот -> бэкенд: подтверждение оплаты из Telegram)
    internal_secret: str = "unternal-sample-secret"

    wg_script_path: str = ""
    wg_conf_path: str = "/etc/wireguard/wg0.conf"
    wg_clients_dir: str = "/etc/wireguard/clients"
    server_endpoint: str = "82.117.84.212"
    wg_port: int = 51820

    subscription_days: int = 30  # ровно 30 = месяц; напоминание за 3 дня до истечения
    subscription_amount: float = 100.0  # сумма за один конфиг (₽), для отображения в админке и боте
    # Номер телефона для перевода (СБП/банк). Если пусто — в боте пишем «уточните у администратора»
    payment_phone: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
