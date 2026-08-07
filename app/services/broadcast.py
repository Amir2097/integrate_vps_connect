"""Рассылка сообщений пользователям бота по Telegram ID."""
import asyncio
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User, Subscription, SubscriptionStatus, VpnClient
from app.services.telegram_notify import send_message

Audience = Literal["all", "with_vpn", "active_subscription"]

AUDIENCE_LABELS = {
    "all": "всем пользователям бота",
    "with_vpn": "пользователям с активным конфигом VPN",
    "active_subscription": "пользователям с активной подпиской",
}


async def get_recipient_telegram_ids(db: AsyncSession, audience: Audience) -> list[int]:
    """Telegram ID получателей (без заблокированных пользователей)."""
    admin_id: int | None = None
    aid = (settings.admin_telegram_id or "").strip()
    if aid:
        try:
            admin_id = int(aid)
        except ValueError:
            admin_id = None

    if audience == "all":
        q = select(User.telegram_id).where(
            User.telegram_id.isnot(None),
            User.is_blocked.is_(False),
        )
    elif audience == "with_vpn":
        q = (
            select(User.telegram_id)
            .distinct()
            .join(VpnClient, VpnClient.user_id == User.id)
            .where(
                User.telegram_id.isnot(None),
                User.is_blocked.is_(False),
                VpnClient.is_blocked.is_(False),
            )
        )
    elif audience == "active_subscription":
        q = (
            select(User.telegram_id)
            .distinct()
            .join(Subscription, Subscription.user_id == User.id)
            .where(
                User.telegram_id.isnot(None),
                User.is_blocked.is_(False),
                Subscription.status == SubscriptionStatus.active,
            )
        )
    else:
        return []

    rows = (await db.execute(q)).scalars().all()
    ids: list[int] = []
    seen: set[int] = set()
    for tid in rows:
        if tid is None:
            continue
        t = int(tid)
        if t in seen:
            continue
        seen.add(t)
        if admin_id is not None and t == admin_id:
            continue
        ids.append(t)
    return ids


async def broadcast_text(telegram_ids: list[int], text: str) -> dict:
    """Отправить текст каждому получателю. Небольшая пауза — лимиты Telegram."""
    sent = 0
    failed = 0
    for tid in telegram_ids:
        if await send_message(tid, text):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)
    return {"sent": sent, "failed": failed, "total": len(telegram_ids)}
