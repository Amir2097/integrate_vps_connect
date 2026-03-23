from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User, Subscription, SubscriptionStatus, Payment, PaymentStatus, VpnClient
from app.services.wireguard import wireguard_service


class SubscriptionService:
    @staticmethod
    def _utcnow_like(dt: datetime | None) -> datetime:
        """now() с той же tz-aware/naive природой, что и dt, чтобы безопасно сравнивать даты."""
        if dt is not None and dt.tzinfo is not None:
            return datetime.now(dt.tzinfo)
        return datetime.utcnow()

    @staticmethod
    async def get_or_create_user(
        db: AsyncSession,
        telegram_id: int,
        telegram_username: str | None = None,
        full_name: str | None = None,
    ) -> User:
        r = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = r.scalars().one_or_none()
        if user:
            if telegram_username is not None:
                user.telegram_username = telegram_username
            if full_name is not None:
                user.full_name = full_name
            return user
        user = User(
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            full_name=full_name,
        )
        db.add(user)
        await db.flush()
        return user

    @staticmethod
    async def create_payment_request(
        db: AsyncSession,
        user_id: int,
        display_name: str | None = None,
        months: int = 1,
        renew_subscription_id: int | None = None,
    ) -> tuple[Subscription, Payment]:
        """Создаёт подписку в pending_payment и платёж в pending. months: 1, 3, 5 или 12."""
        r = await db.execute(
            select(Payment.id).where(
                Payment.user_id == user_id,
                Payment.status == PaymentStatus.pending,
            ).limit(1)
        )
        if r.scalars().first():
            raise ValueError("У вас уже есть заявка, ожидайте подтверждения")
        if months not in (1, 3, 5, 12):
            months = 1
        if renew_subscription_id is not None:
            r = await db.execute(
                select(Subscription).where(
                    Subscription.id == renew_subscription_id,
                    Subscription.user_id == user_id,
                )
            )
            sub = r.scalars().one_or_none()
            if not sub:
                raise ValueError("Подписка для продления не найдена")
        else:
            # Отменить только те подписки в pending_payment, у которых нет ожидающего платежа (не трогаем активные заявки)
            r = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.status == SubscriptionStatus.pending_payment,
                )
            )
            for sub_old in r.scalars().all():
                r2 = await db.execute(
                    select(Payment.id).where(
                        Payment.subscription_id == sub_old.id,
                        Payment.status == PaymentStatus.pending,
                    ).limit(1)
                )
                if r2.scalars().first() is None:
                    sub_old.status = SubscriptionStatus.cancelled
            name_clean = (display_name or "").strip()[:128] or None
            sub = Subscription(
                user_id=user_id,
                status=SubscriptionStatus.pending_payment,
                display_name=name_clean,
            )
            db.add(sub)
            await db.flush()
        amount = float(settings.subscription_amount) * months
        payment = Payment(
            user_id=user_id,
            subscription_id=sub.id,
            subscription_months=months,
            amount=amount,
            status=PaymentStatus.pending,
        )
        db.add(payment)
        await db.flush()
        return sub, payment

    @staticmethod
    async def get_pending_payment_id_by_user(db: AsyncSession, user_id: int) -> int | None:
        """ID ожидающего оплаты по user_id или None."""
        r = await db.execute(
            select(Payment.id).where(
                Payment.user_id == user_id,
                Payment.status == PaymentStatus.pending,
            ).order_by(Payment.created_at.desc()).limit(1)
        )
        row = r.scalars().one_or_none()
        return int(row) if row is not None else None

    @staticmethod
    async def get_pending_payment_id_by_telegram(db: AsyncSession, telegram_id: int) -> int | None:
        """ID ожидающего оплаты по telegram_id пользователя или None."""
        r = await db.execute(select(User.id).where(User.telegram_id == telegram_id))
        user_id = r.scalars().one_or_none()
        if user_id is None:
            return None
        return await SubscriptionService.get_pending_payment_id_by_user(db, int(user_id))

    @staticmethod
    async def confirm_payment(
        db: AsyncSession,
        payment_id: int,
        confirmed: bool,
        admin_notes: str | None = None,
        admin_user_id: int | None = None,
    ) -> Payment | None:
        """
        Подтверждает или отклоняет платёж. При подтверждении: создаёт VPN-клиента (скрипт),
        активирует подписку на subscription_days дней.
        """
        r = await db.execute(select(Payment).where(Payment.id == payment_id))
        payment = r.scalars().one_or_none()
        if not payment or payment.status != PaymentStatus.pending:
            return None

        payment.status = PaymentStatus.confirmed if confirmed else PaymentStatus.rejected
        payment.admin_notes = admin_notes
        payment.confirmed_at = datetime.utcnow()
        payment.confirmed_by = admin_user_id

        if not confirmed and payment.subscription_id:
            r = await db.execute(select(Subscription).where(Subscription.id == payment.subscription_id))
            sub = r.scalars().one_or_none()
            if sub and sub.status == SubscriptionStatus.pending_payment and sub.started_at is None:
                sub.status = SubscriptionStatus.cancelled
            r = await db.execute(select(User).where(User.id == payment.user_id))
            user = r.scalars().one_or_none()
            if user and user.telegram_id:
                from app.services.telegram_notify import send_message
                await send_message(
                    user.telegram_id,
                    "❌ <b>Оплата не подтверждена.</b>\n\n"
                    "Если вы уже перевели средства — свяжитесь с поддержкой. "
                    "Вы можете оформить новую заявку (кнопка «Подключиться») или после повторной оплаты нажать «Я оплатил».",
                )

        if confirmed and payment.subscription_id:
            r = await db.execute(select(Subscription).where(Subscription.id == payment.subscription_id))
            sub = r.scalars().one_or_none()
            if not sub:
                payment.status = PaymentStatus.pending
                return None
            months = getattr(payment, "subscription_months", 1) or 1
            now = SubscriptionService._utcnow_like(sub.expires_at)
            base = sub.expires_at if (sub.expires_at and sub.expires_at > now) else now
            sub.status = SubscriptionStatus.active
            if not sub.started_at:
                sub.started_at = now
            sub.expires_at = base + timedelta(days=settings.subscription_days * months)

            # Уже есть VpnClient по этой подписке (повторное подтверждение) — только отправить выбор конфига
            r = await db.execute(
                select(VpnClient).where(VpnClient.subscription_id == payment.subscription_id).limit(1)
            )
            existing_vpn = r.scalars().one_or_none()
            if existing_vpn:
                r = await db.execute(select(User).where(User.id == payment.user_id))
                user = r.scalars().one_or_none()
                if user and user.telegram_id:
                    from app.services.telegram_notify import send_message
                    exp = sub.expires_at.strftime("%d.%m.%Y") if sub.expires_at else "—"
                    safe_name = (sub.display_name or existing_vpn.display_name or existing_vpn.name).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    await send_message(
                        user.telegram_id,
                        f"✅ Подписка <b>«{safe_name}»</b> продлена до {exp}. "
                        "Ваш текущий конфиг остаётся прежним.",
                    )
                await db.flush()
                return payment

            # Создать VPN-клиента: вызвать скрипт, сохранить в БД
            client_name = f"user{payment.user_id}_{sub.id}"
            try:
                data = await wireguard_service.add_client(client_name)
            except Exception as e:
                err_msg = str(e)
                print(f"[WG] add_client failed: {err_msg}")  # в логах systemd (journalctl)
                payment.admin_notes = (payment.admin_notes or "") + f" [WG error: {err_msg}]"
                await db.flush()
                # Уведомить пользователя и админа об ошибке
                r = await db.execute(select(User).where(User.id == payment.user_id))
                user = r.scalars().one_or_none()
                if user and user.telegram_id:
                    from app.services.telegram_notify import send_message, notify_admin
                    await send_message(
                        user.telegram_id,
                        "⚠️ При создании конфига произошла техническая ошибка. Администратор уведомлён, мы исправим в ближайшее время.",
                    )
                    await notify_admin(f"❌ Ошибка WG при подтверждении платежа {payment_id}: {err_msg}")
                return payment

            display_name = (sub.display_name or "").strip() or None
            vpn = VpnClient(
                user_id=payment.user_id,
                subscription_id=sub.id,
                name=client_name,
                display_name=display_name,
                wg_public_key=data["public_key"],
                wg_private_key=data["private_key"],
                allowed_ip=data["allowed_ip"],
                config_content=data["config_content"],
            )
            db.add(vpn)
            await db.flush()
            # Отправить выбор формата конфига (текст или QR) — пользователь нажмёт кнопку в боте
            r = await db.execute(select(User).where(User.id == payment.user_id))
            user = r.scalars().one_or_none()
            if user and user.telegram_id:
                from app.services.telegram_notify import send_activation_choice
                await send_activation_choice(user.telegram_id, vpn.id)
        await db.flush()
        return payment

    @staticmethod
    async def get_user_subscription(db: AsyncSession, user_id: int) -> Subscription | None:
        r = await db.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        return r.scalars().one_or_none()

    @staticmethod
    async def get_user_subscriptions_list(db: AsyncSession, user_id: int) -> list[dict]:
        """Список всех подписок пользователя: название, статус, дата окончания, is_blocked конфига."""
        r = await db.execute(
            select(Subscription, VpnClient)
            .outerjoin(VpnClient, VpnClient.subscription_id == Subscription.id)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.asc())
        )
        rows = r.all()
        return [
            {
                "id": s.id,
                "display_name": (s.display_name or "").strip() or f"Конфиг #{i + 1}",
                "status": s.status.value,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "is_blocked": vc.is_blocked if vc else False,
                "vpn_client_id": vc.id if vc and not vc.is_blocked else None,
            }
            for i, (s, vc) in enumerate(rows)
        ]

    @staticmethod
    async def get_user_vpn_config(db: AsyncSession, user_id: int, vpn_client_id: int | None = None) -> str | None:
        """Конфиг по user_id; если конфиг или пользователь заблокированы — None."""
        if vpn_client_id is not None:
            r = await db.execute(
                select(VpnClient).where(
                    VpnClient.id == vpn_client_id,
                    VpnClient.user_id == user_id,
                    VpnClient.is_blocked.is_(False),
                )
            )
            client = r.scalars().one_or_none()
            return client.config_content if client else None
        r = await db.execute(
            select(VpnClient)
            .where(VpnClient.user_id == user_id, VpnClient.is_blocked.is_(False))
            .order_by(VpnClient.created_at.desc())
            .limit(1)
        )
        client = r.scalars().one_or_none()
        return client.config_content if client else None

    @staticmethod
    async def get_user_vpn_configs_list(db: AsyncSession, user_id: int) -> list[dict]:
        """Список VPN-конфигов пользователя (только не заблокированные)."""
        r = await db.execute(
            select(VpnClient)
            .where(VpnClient.user_id == user_id, VpnClient.is_blocked.is_(False))
            .order_by(VpnClient.created_at.asc())
        )
        clients = r.scalars().all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "display_name": c.display_name or c.name,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in clients
        ]

    @staticmethod
    async def expire_subscriptions(db: AsyncSession) -> int:
        """
        Помечает подписки с истёкшим сроком и при необходимости отзывает VPN.
        Возвращает количество обновлённых подписок.
        """
        r = await db.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at <= datetime.utcnow(),
            )
        )
        subs = r.scalars().all()
        for sub in subs:
            sub.status = SubscriptionStatus.expired
            # Отозвать только конфиг этой подписки (по subscription_id)
            r2 = await db.execute(select(VpnClient).where(VpnClient.subscription_id == sub.id))
            for vpn in r2.scalars().all():
                await wireguard_service.revoke_client(vpn.wg_public_key)
        await db.flush()
        return len(subs)

    @staticmethod
    async def get_expiring_soon(db: AsyncSession, days: int = 3) -> list[tuple["Subscription", "User"]]:
        """Подписки, до истечения которых осталось примерно days дней (для напоминания)."""
        now = datetime.utcnow()
        # Напоминаем, если истекает через (days - 0.5) .. (days + 0.5) дней
        start = now + timedelta(days=days - 1, hours=12)
        end = now + timedelta(days=days, hours=12)
        r = await db.execute(
            select(Subscription, User)
            .join(User, Subscription.user_id == User.id)
            .where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at >= start,
                Subscription.expires_at <= end,
            )
        )
        return list(r.all())


subscription_service = SubscriptionService()
