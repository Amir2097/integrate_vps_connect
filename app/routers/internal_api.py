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
from app.models import User, Payment, PaymentStatus, Subscription
from app.services.subscription import subscription_service
from app.services.telegram_notify import notify_admin_payment_buttons
from app.services.broadcast import (
    AUDIENCE_LABELS,
    Audience,
    broadcast_text,
    get_recipient_telegram_ids,
)
from app.services.broadcast_messages import endpoint_update_broadcast_text

router = APIRouter(prefix="/api/internal", tags=["internal"])


def _parse_audience(audience: str) -> Audience:
    a = (audience or "").strip()
    if a not in AUDIENCE_LABELS:
        raise HTTPException(400, f"Unknown audience: {audience}")
    return a  # type: ignore[return-value]


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
    notified_marker = "[BOT_ADMIN_NOTIFIED]"
    r = await db.execute(
        select(Payment, User, Subscription)
        .join(User, Payment.user_id == User.id)
        .outerjoin(Subscription, Payment.subscription_id == Subscription.id)
        .where(Payment.id == body.payment_id, Payment.status == PaymentStatus.pending)
    )
    row = r.one_or_none()
    if not row:
        raise HTTPException(404, "Pending payment not found")
    payment, user, sub = row
    # Не плодим дубликаты: для одного pending-платежа шлём админу только одно уведомление «Я оплатил».
    notes = payment.admin_notes or ""
    if notified_marker in notes:
        return {"ok": True, "payment_id": body.payment_id, "deduplicated": True}
    name = (user.full_name or "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    username = (f"@{user.telegram_username}" if user.telegram_username else "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    months = getattr(payment, "subscription_months", 1) or 1
    amount = payment.amount
    is_renewal = bool(sub and sub.started_at is not None)
    sub_name = ((sub.display_name if sub else None) or f"#{payment.subscription_id or '—'}").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    pay_type = "Продление" if is_renewal else "Новое подключение"
    text = (
        f"💰 <b>«Я оплатил»</b>\n"
        f"Тип: <b>{pay_type}</b>\n"
        f"Пользователь: {name} ({username})\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Подписка: <b>{sub_name}</b>\n"
        f"Срок: <b>{months} мес.</b>\n"
        f"Сумма: <b>{amount} ₽</b>\n"
        f"Подтвердите оплату кнопкой ниже или в админке."
    )
    ok = await notify_admin_payment_buttons(payment.id, text)
    if ok:
        payment.admin_notes = (notes + " " + notified_marker).strip()
        await db.flush()
        await db.commit()
    return {"ok": ok, "payment_id": body.payment_id, "deduplicated": False}


@router.get("/broadcast/count")
async def internal_broadcast_count(
    audience: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(_check_internal_secret),
):
    aud = _parse_audience(audience)
    ids = await get_recipient_telegram_ids(db, aud)
    return {"count": len(ids), "audience": aud, "label": AUDIENCE_LABELS[aud]}


@router.get("/broadcast/preview")
async def internal_broadcast_preview(
    audience: str,
    preset: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(_check_internal_secret),
):
    aud = _parse_audience(audience)
    if preset == "endpoint_update":
        text = endpoint_update_broadcast_text()
    else:
        raise HTTPException(400, "Unknown preset")
    ids = await get_recipient_telegram_ids(db, aud)
    return {"count": len(ids), "audience": aud, "text": text}


class BroadcastBody(BaseModel):
    audience: str
    text: str


@router.post("/broadcast")
async def internal_broadcast(
    body: BroadcastBody,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(_check_internal_secret),
):
    aud = _parse_audience(body.audience)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "Empty text")
    if len(text) > 4000:
        raise HTTPException(400, "Text too long (max 4000)")
    ids = await get_recipient_telegram_ids(db, aud)
    stats = await broadcast_text(ids, text)
    return {"ok": True, "audience": aud, **stats}


class BroadcastPresetBody(BaseModel):
    preset: str
    audience: str = "with_vpn"


@router.post("/broadcast-preset")
async def internal_broadcast_preset(
    body: BroadcastPresetBody,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(_check_internal_secret),
):
    aud = _parse_audience(body.audience)
    if body.preset == "endpoint_update":
        text = endpoint_update_broadcast_text()
    else:
        raise HTTPException(400, "Unknown preset")
    ids = await get_recipient_telegram_ids(db, aud)
    stats = await broadcast_text(ids, text)
    return {"ok": True, "preset": body.preset, "audience": aud, **stats}
