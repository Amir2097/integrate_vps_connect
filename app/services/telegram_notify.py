"""Отправка уведомлений пользователю в Telegram (конфиг, напоминания)."""
import io
import qrcode
import httpx
from app.config import settings

CONFIG_WARNING = (
    "⚠️ <b>Важно:</b> один конфиг — один клиент (одно устройство или один человек). "
    "Не используйте один и тот же конфиг на нескольких устройствах и не передавайте его другим — "
    "иначе возможны отключения и блокировка доступа. Для другого устройства или человека оформите отдельную подписку."
)


def config_to_qr_png(config_text: str) -> bytes | None:
    """Генерирует PNG QR-код конфига. Возвращает None при ошибке."""
    try:
        qr = qrcode.QRCode(version=1, box_size=4, border=2)
        qr.add_data(config_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


async def notify_admin(text: str) -> bool:
    """Отправить уведомление админу (если задан ADMIN_TELEGRAM_ID в .env)."""
    aid = (settings.admin_telegram_id or "").strip()
    if not aid:
        return False
    try:
        return await send_message(int(aid), text)
    except (ValueError, TypeError):
        return False


async def send_message(telegram_id: int, text: str) -> bool:
    """Отправить текстовое сообщение в Telegram."""
    if not settings.bot_token:
        return False
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                url,
                json={"chat_id": telegram_id, "text": text, "parse_mode": "HTML"},
                timeout=10.0,
            )
            return r.is_success
        except Exception:
            return False


def _inline_keyboard_confirm_reject(payment_id: int) -> list:
    """Кнопки «Подтвердить» / «Отклонить» для оплаты payment_id."""
    return [
        [
            {"text": "✅ Подтвердить", "callback_data": f"confirm_pay:{payment_id}"},
            {"text": "❌ Отклонить", "callback_data": f"reject_pay:{payment_id}"},
        ]
    ]


async def send_message_with_buttons(telegram_id: int, text: str, inline_keyboard: list) -> bool:
    """Отправить сообщение с inline-кнопками."""
    if not settings.bot_token:
        return False
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                url,
                json={
                    "chat_id": telegram_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": inline_keyboard},
                },
                timeout=10.0,
            )
            return r.is_success
        except Exception:
            return False


async def notify_admin_payment_buttons(payment_id: int, text: str) -> bool:
    """Отправить админу уведомление с кнопками Подтвердить/Отклонить."""
    aid = (settings.admin_telegram_id or "").strip()
    if not aid:
        return False
    try:
        return await send_message_with_buttons(
            int(aid),
            text,
            _inline_keyboard_confirm_reject(payment_id),
        )
    except (ValueError, TypeError):
        return False


def _activation_format_keyboard(vpn_client_id: int) -> list:
    """Кнопки выбора формата конфига при активации подписки."""
    return [
        [
            {"text": "Текст конфига (файл)", "callback_data": f"act_cfg:txt:{vpn_client_id}"},
            {"text": "QR-код", "callback_data": f"act_cfg:qr:{vpn_client_id}"},
        ]
    ]


async def send_activation_choice(telegram_id: int, vpn_client_id: int) -> bool:
    """
    Отправить пользователю сообщение «Подписка активирована» с выбором формата конфига.
    Конфиг пользователь получит после нажатия кнопки в боте (обработчики act_cfg:txt / act_cfg:qr).
    """
    if not settings.bot_token:
        return False
    text = (
        "✅ <b>Ваша подписка активирована.</b>\n\n"
        "Выберите формат получения конфига:"
    )
    return await send_message_with_buttons(
        telegram_id,
        text,
        _activation_format_keyboard(vpn_client_id),
    )


async def send_config_to_user(telegram_id: int, config_text: str) -> bool:
    """Прямая отправка конфига (текст + QR). Используется редко; обычно — send_activation_choice."""
    if not settings.bot_token:
        return False
    async with httpx.AsyncClient() as client:
        try:
            # 1. Предупреждение + конфиг текстом
            body = (
                "Ваша подписка активирована.\n\n"
                f"{CONFIG_WARNING}\n\n"
                "Конфиг WireGuard (скопируйте в приложение или сохраните как .conf):\n\n"
                f"<pre>{config_text.replace('<', '&lt;').replace('>', '&gt;')}</pre>"
            )
            r1 = await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": telegram_id, "text": body, "parse_mode": "HTML"},
                timeout=10.0,
            )
            if not r1.is_success:
                return False
            # 2. QR-код (удобно для телефона)
            qr_bytes = config_to_qr_png(config_text)
            if qr_bytes:
                r2 = await client.post(
                    f"https://api.telegram.org/bot{settings.bot_token}/sendPhoto",
                    data={"chat_id": telegram_id, "caption": "QR-код конфига — отсканируйте в приложении WireGuard."},
                    files={"photo": ("qr.png", qr_bytes, "image/png")},
                    timeout=10.0,
                )
            return True
        except Exception:
            return False
