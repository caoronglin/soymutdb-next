"""System settings key-value model for dynamic configuration (CDN, feature flags, etc.)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SystemSetting(Base):
    """Key-value store for dynamic system settings.

    Used to store configuration that can be updated at runtime (e.g. CDN URLs,
    feature flags) without requiring a deployment or environment variable change.
    """

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:
        return f"<SystemSetting id={self.id} key={self.key!r}>"


__all__ = [
    "SystemSetting",
]
