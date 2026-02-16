from datetime import datetime
from pydantic import BaseModel


class VpnClientResponse(BaseModel):
    id: int
    user_id: int
    name: str
    allowed_ip: str
    created_at: datetime

    class Config:
        from_attributes = True


class VpnClientConfigResponse(BaseModel):
    config_text: str
    qr_data: str  # тот же конфиг для QR
