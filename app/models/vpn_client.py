from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VpnClient(Base):
    __tablename__ = "vpn_clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)  # связь с подпиской для блокировки по конфигу
    name: Mapped[str] = mapped_column(String(64))  # латинское имя на сервере WG
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # название от пользователя для бота
    wg_public_key: Mapped[str] = mapped_column(String(64), unique=True)
    wg_private_key: Mapped[str] = mapped_column(Text)  # храним для выдачи конфига
    allowed_ip: Mapped[str] = mapped_column(String(32))  # 10.66.0.2
    config_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # готовый .conf для выдачи
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)  # доступ по этому конфигу приостановлен админом
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="vpn_clients")
