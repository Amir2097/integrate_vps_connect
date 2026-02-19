from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import engine, Base, async_session
from app.routers import api, admin_api, admin_views, internal_api
from app.routers.auth_router import router as auth_router
from app.services.subscription import subscription_service


async def run_subscription_check():
    async with async_session() as db:
        try:
            n = await subscription_service.expire_subscriptions(db)
            await db.commit()
            if n:
                print(f"Expired {n} subscriptions")
        except Exception as e:
            await db.rollback()
            print(f"Scheduler error: {e}")


async def run_expiry_reminders():
    """Напоминание за 3 дня до истечения подписки."""
    from app.services.telegram_notify import send_message
    async with async_session() as db:
        try:
            expiring = await subscription_service.get_expiring_soon(db, days=3)
            for sub, user in expiring:
                if not user.telegram_id:
                    continue
                exp_date = sub.expires_at.strftime("%d.%m.%Y") if sub.expires_at else "—"
                text = (
                    f"Напоминание: ваша VPN-подписка истекает через 3 дня ({exp_date}). "
                    "Для продления создайте новую заявку: «Подключиться»."
                )
                await send_message(user.telegram_id, text)
        except Exception as e:
            print(f"Reminder error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_subscription_check, IntervalTrigger(hours=1))
    scheduler.add_job(run_expiry_reminders, IntervalTrigger(hours=12))  # напоминание за 3 дня
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="VPN Manager", lifespan=lifespan)

app.include_router(api.router)
app.include_router(admin_api.router)
app.include_router(internal_api.router)
app.include_router(admin_views.router)
app.include_router(auth_router)

_static_dir = Path(__file__).resolve().parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
async def root():
    return {"service": "VPN Manager", "docs": "/docs", "admin": "/admin"}
