"""
Внутренний API для бота: подтверждение/отклонение оплаты из Telegram, уведомление админу с кнопками.
Вызовы защищены заголовком X-Internal-Secret.
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.config import settings
from app.models import User, Payment, PaymentStatus
from app.services.subscription import subscription_service
from app.services.telegram_notify import notify_admin_payment_buttons

router = APIRouter(prefix="/api/internal", tags=["internal"])


def _check_internal_secret(x_internal_secret: str | None = Header(None, alias="X-Internal-Secret")):
    if not settings.internal_secret or x_internal_secret != settings.internal_secret:
        raise HTTPException(403, "Forbidden")
    return True


class ConfirmPaymentBody(BaseModel):
    payment_id: int
    action: str  # "confirm" | "reject"


@router.post("/confirm-payment")
async def internal_confirm_payment(
    body: ConfirmPaymentBody,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(_check_internal_secret),
):
    """Вызывается ботом при нажатии админом «Подтвердить»/«Отклонить» в Telegram."""
    confirmed = body.action.strip().lower() == "confirm"
    payment = await subscription_service.confirm_payment(
        db,
        body.payment_id,
        confirmed=confirmed,
        admin_notes="Подтверждено из Telegram",
        admin_user_id=None,
    )
    await db.commit()
    if not payment:
        raise HTTPException(404, "Payment not found or already processed")
    return {"ok": True, "status": payment.status.value}


class AdminNotifyPaymentBody(BaseModel):
    payment_id: int


@router.post("/admin-notify-payment")
async def internal_admin_notify_payment(
    body: AdminNotifyPaymentBody,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(_check_internal_secret),
):
    """Отправить админу сообщение «Я оплатил» с кнопками Подтвердить/Отклонить (вызывает бот)."""
    r = await db.execute(
        select(Payment, User)
        .join(User, Payment.user_id == User.id)
        .where(Payment.id == body.payment_id, Payment.status == PaymentStatus.pending)
    )
    row = r.one_or_none()
    if not row:
        raise HTTPException(404, "Pending payment not found")
    payment, user = row
    name = user.full_name or "—"
    username = f"@{user.telegram_username}" if user.telegram_username else "—"
    text = (
        f"💰 <b>«Я оплатил»</b>\n"
        f"Пользователь: {name} ({username})\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Подтвердите оплату кнопкой ниже или в админке."
    )
    ok = await notify_admin_payment_buttons(payment.id, text)
    return {"ok": ok, "payment_id": body.payment_id}
