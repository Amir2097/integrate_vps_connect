"""
REST API для админки: список пользователей, платежей, подтверждение оплаты.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_admin
from app.models import User, Payment, PaymentStatus, Subscription, VpnClient
from app.schemas.payment import PaymentResponse, PaymentConfirm
from app.services.subscription import subscription_service

router = APIRouter(prefix="/admin/api", tags=["admin"])


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    r = await db.execute(select(User).order_by(User.id))
    users = r.scalars().all()
    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
            "telegram_username": u.telegram_username,
            "full_name": u.full_name,
            "is_blocked": u.is_blocked,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/users/{user_id}/block")
async def block_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """Временно отключить доступ пользователя. Конфиг не удаляется, при разблокировке доступ восстанавливается."""
    r = await db.execute(select(User).where(User.id == user_id))
    user = r.scalars().one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_blocked = True
    await db.commit()
    return {"ok": True, "user_id": user_id, "is_blocked": True}


@router.post("/users/{user_id}/unblock")
async def unblock_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    """Включить доступ пользователя (разблокировать)."""
    r = await db.execute(select(User).where(User.id == user_id))
    user = r.scalars().one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_blocked = False
    await db.commit()
    return {"ok": True, "user_id": user_id, "is_blocked": False}


@router.get("/payments/pending")
async def list_pending_payments(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    r = await db.execute(
        select(Payment, User)
        .join(User, Payment.user_id == User.id)
        .where(Payment.status == PaymentStatus.pending)
        .order_by(Payment.created_at.desc())
    )
    rows = r.all()
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "amount": float(p.amount),
            "created_at": p.created_at.isoformat(),
            "user_telegram_id": u.telegram_id,
            "user_name": u.full_name or u.telegram_username,
        }
        for p, u in rows
    ]


@router.post("/payments/{payment_id}/confirm", response_model=PaymentResponse)
async def confirm_payment(
    payment_id: int,
    body: PaymentConfirm,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    payment = await subscription_service.confirm_payment(
        db,
        payment_id,
        confirmed=(body.status == PaymentStatus.confirmed),
        admin_notes=body.admin_notes,
        admin_user_id=admin.get("sub"),
    )
    await db.commit()
    if not payment:
        raise HTTPException(404, "Payment not found or already processed")
    return payment


@router.get("/subscriptions")
async def list_subscriptions(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_admin),
):
    r = await db.execute(
        select(Subscription, User)
        .join(User, Subscription.user_id == User.id)
        .order_by(Subscription.created_at.desc())
    )
    rows = r.all()
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "status": s.status.value,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "user_telegram_id": u.telegram_id,
        }
        for s, u in rows
    ]
