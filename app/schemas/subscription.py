from datetime import datetime
from pydantic import BaseModel

from app.models.subscription import SubscriptionStatus


class SubscriptionResponse(BaseModel):
    id: int
    user_id: int
    status: SubscriptionStatus
    started_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True
