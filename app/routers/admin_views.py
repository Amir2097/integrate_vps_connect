"""
Админ-панель: HTML страницы (логин, дашборд, подтверждение платежей).
Вход по паролю + простая сессия в cookie (без JWT), чтобы не зависеть от JWT_SECRET.
"""
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import verify_password
from app.config import settings
from app.models import User, Payment, PaymentStatus, Subscription

router = APIRouter(prefix="/admin", tags=["admin-panel"])
_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Простые сессии в памяти: session_id -> время создания (истекают через 24 ч)
_admin_sessions: dict[str, float] = {}
_SESSION_MAX_AGE = 86400  # секунд


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@router.post("/login")
async def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
):
    if login != settings.admin_login:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Неверный логин или пароль"},
        )
    raw_hash = (settings.admin_password_hash or "").strip()
    if not raw_hash:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "ADMIN_PASSWORD_HASH не задан. В терминале: python -c \"from app.auth import hash_password; print(hash_password('твой_пароль'))\" — вывод вставь в .env как ADMIN_PASSWORD_HASH=..."},
        )
    if not (raw_hash.startswith("$2b$") or raw_hash.startswith("$2a$")):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "ADMIN_PASSWORD_HASH должен быть bcrypt-хэш (начинается с $2b$). Сгенерируй: python -c \"from app.auth import hash_password; print(hash_password('твой_пароль'))\""},
        )
    if not verify_password(password, raw_hash):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Неверный логин или пароль"},
        )
    session_id = secrets.token_urlsafe(32)
    _admin_sessions[session_id] = time.time()
    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(
        "admin_session",
        session_id,
        httponly=True,
        max_age=_SESSION_MAX_AGE,
        path="/",
        samesite="lax",
    )
    return response


def _is_admin_session(request: Request) -> bool:
    sid = (request.cookies.get("admin_session") or "").strip()
    if not sid or sid not in _admin_sessions:
        return False
    if time.time() - _admin_sessions[sid] > _SESSION_MAX_AGE:
        del _admin_sessions[sid]
        return False
    return True


@router.get("/logout")
async def admin_logout(request: Request):
    sid = (request.cookies.get("admin_session") or "").strip()
    if sid and sid in _admin_sessions:
        del _admin_sessions[sid]
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_session", path="/")
    return response


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin_session(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    r = await db.execute(
        select(Payment, User)
        .join(User, Payment.user_id == User.id)
        .where(Payment.status == PaymentStatus.pending)
        .order_by(Payment.created_at.desc())
    )
    pending = [
        {"payment": p, "user": u}
        for p, u in r.all()
    ]

    r2 = await db.execute(
        select(Subscription, User)
        .join(User, Subscription.user_id == User.id)
        .order_by(Subscription.created_at.desc())
        .limit(50)
    )
    subs_with_users = [{"sub": s, "user": u} for s, u in r2.all()]

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {"request": request, "pending_payments": pending, "subscriptions": subs_with_users},
    )


@router.post("/payments/{payment_id}/confirm")
async def admin_confirm_payment(
    payment_id: int,
    request: Request,
    action: str = Form(...),
    admin_notes: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin_session(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    from app.services.subscription import subscription_service
    await subscription_service.confirm_payment(
        db,
        payment_id,
        confirmed=(action == "confirm"),
        admin_notes=admin_notes or None,
        admin_user_id=None,
    )
    await db.commit()
    return RedirectResponse(url="/admin", status_code=302)
