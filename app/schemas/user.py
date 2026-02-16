from pydantic import BaseModel


class UserCreate(BaseModel):
    telegram_id: int
    telegram_username: str | None = None
    full_name: str | None = None


class UserResponse(BaseModel):
    id: int
    telegram_id: int | None
    telegram_username: str | None
    full_name: str | None
    is_admin: bool

    class Config:
        from_attributes = True
