from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

from app.models.payment import PaymentStatus


class PaymentResponse(BaseModel):
    id: int
    user_id: int
    subscription_id: int | None
    amount: Decimal
    status: PaymentStatus
    admin_notes: str | None
    confirmed_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentConfirm(BaseModel):
    status: PaymentStatus  # confirmed | rejected
    admin_notes: str | None = None
