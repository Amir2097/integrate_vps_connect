from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from app.auth import verify_password, create_access_token
from app.config import settings
from app.schemas.auth import Token

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    if form.username != settings.admin_login:
        raise HTTPException(401, "Invalid login or password")
    if not settings.admin_password_hash:
        raise HTTPException(500, "ADMIN_PASSWORD_HASH not set")
    if not verify_password(form.password, settings.admin_password_hash):
        raise HTTPException(401, "Invalid login or password")
    token = create_access_token({"sub": 0, "role": "admin"})
    return Token(access_token=token)
