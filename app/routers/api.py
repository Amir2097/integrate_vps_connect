"""
API для бота: регистрация пользователя, запрос подписки, «Я оплатил», получение конфига.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.services.subscription import subscription_service

router = APIRouter(prefix="/api", tags=["api"])


class RegisterRequest(BaseModel):
    telegram_id: int
    telegram_username: str | None = None
    full_name: str | None = None


class RegisterResponse(BaseModel):
    user_id: int


@router.post("/register", response_model=RegisterResponse)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = await subscription_service.get_or_create_user(
        db, data.telegram_id, data.telegram_username, data.full_name
    )
    await db.commit()
    return RegisterResponse(user_id=user.id)


class CreatePaymentRequest(BaseModel):
    user_id: int | None = None
    telegram_id: int | None = None
    display_name: str | None = None  # название конфига от пользователя
    months: int = 1  # срок подписки: 1, 3, 5 или 12 месяцев


class CreatePaymentResponse(BaseModel):
    subscription_id: int
    payment_id: int


@router.post("/payment/request", response_model=CreatePaymentResponse)
async def create_payment_request(data: CreatePaymentRequest, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.models import User as UserModel

    if data.telegram_id is not None:
        user = await subscription_service.get_or_create_user(db, data.telegram_id)
        await db.flush()
        user_id = user.id
    elif data.user_id is not None:
        user_id = data.user_id
        r = await db.execute(select(UserModel).where(UserModel.id == user_id))
        user = r.scalars().one_or_none()
    else:
        raise HTTPException(400, "Provide user_id or telegram_id")
    try:
        sub, payment = await subscription_service.create_payment_request(
            db, user_id, display_name=data.display_name, months=data.months
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    # Админ уведомляется только после нажатия пользователем «Я оплатил» (admin-notify-payment).
    return CreatePaymentResponse(subscription_id=sub.id, payment_id=payment.id)


class SubscriptionStatusResponse(BaseModel):
    status: str
    expires_at: str | None


@router.get("/user/{user_id}/subscription", response_model=SubscriptionStatusResponse)
async def get_subscription(user_id: int, db: AsyncSession = Depends(get_db)):
    sub = await subscription_service.get_user_subscription(db, user_id)
    if not sub:
        return SubscriptionStatusResponse(status="none", expires_at=None)
    return SubscriptionStatusResponse(
        status=sub.status.value,
        expires_at=sub.expires_at.isoformat() if sub.expires_at else None,
    )


@router.get("/user/by-telegram/{telegram_id}/subscription", response_model=SubscriptionStatusResponse)
async def get_subscription_by_telegram(telegram_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.models import User
    r = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = r.scalars().one_or_none()
    if not user:
        return SubscriptionStatusResponse(status="none", expires_at=None)
    if user.is_blocked:
        sub = await subscription_service.get_user_subscription(db, user.id)
        return SubscriptionStatusResponse(
            status="blocked",
            expires_at=sub.expires_at.isoformat() if sub and sub.expires_at else None,
        )
    sub = await subscription_service.get_user_subscription(db, user.id)
    if not sub:
        return SubscriptionStatusResponse(status="none", expires_at=None)
    return SubscriptionStatusResponse(
        status=sub.status.value,
        expires_at=sub.expires_at.isoformat() if sub.expires_at else None,
    )


@router.get("/user/by-telegram/{telegram_id}/subscriptions")
async def get_subscriptions_by_telegram(telegram_id: int, db: AsyncSession = Depends(get_db)):
    """Список всех подписок пользователя для «Моя подписка»: название, статус, дата окончания, is_blocked."""
    from sqlalchemy import select
    from app.models import User
    r = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = r.scalars().one_or_none()
    if not user:
        return []
    items = await subscription_service.get_user_subscriptions_list(db, user.id)
    for item in items:
        item["is_blocked"] = user.is_blocked
    return items


class PendingPaymentResponse(BaseModel):
    payment_id: int | None


@router.get("/user/by-telegram/{telegram_id}/pending-payment", response_model=PendingPaymentResponse)
async def get_pending_payment_by_telegram(telegram_id: int, db: AsyncSession = Depends(get_db)):
    """Для бота: ID ожидающего оплаты по telegram_id (чтобы отправить админу кнопки «Я оплатил»)."""
    payment_id = await subscription_service.get_pending_payment_id_by_telegram(db, telegram_id)
    return PendingPaymentResponse(payment_id=payment_id)


class VpnConfigResponse(BaseModel):
    config: str | None


class VpnConfigItem(BaseModel):
    id: int
    name: str
    created_at: str | None


@router.get("/user/{user_id}/vpn-config", response_model=VpnConfigResponse)
async def get_vpn_config(
    user_id: int,
    vpn_client_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models import User
    r = await db.execute(select(User).where(User.id == user_id))
    user = r.scalars().one_or_none()
    if not user or user.is_blocked:
        return VpnConfigResponse(config=None)
    config = await subscription_service.get_user_vpn_config(db, user_id, vpn_client_id=vpn_client_id)
    return VpnConfigResponse(config=config)


@router.get("/user/by-telegram/{telegram_id}/vpn-config", response_model=VpnConfigResponse)
async def get_vpn_config_by_telegram(
    telegram_id: int,
    vpn_client_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models import User
    r = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = r.scalars().one_or_none()
    if not user or user.is_blocked:
        return VpnConfigResponse(config=None)
    config = await subscription_service.get_user_vpn_config(db, user.id, vpn_client_id=vpn_client_id)
    return VpnConfigResponse(config=config)


@router.get("/user/by-telegram/{telegram_id}/vpn-configs")
async def get_vpn_configs_by_telegram(telegram_id: int, db: AsyncSession = Depends(get_db)):
    """Список конфигов пользователя (несколько подписок = несколько конфигов). При блокировке — пустой список."""
    from sqlalchemy import select
    from app.models import User
    r = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = r.scalars().one_or_none()
    if not user or user.is_blocked:
        return []
    return await subscription_service.get_user_vpn_configs_list(db, user.id)
