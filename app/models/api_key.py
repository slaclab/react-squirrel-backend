"""API_Key model for tracking API Keys for application access to the backend."""
from sqlalchemy import Index, String, Boolean, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class ApiKey(Base, UUIDMixin, TimestampMixin):
    """Model for tracking API Keys for application access to the backend."""

    __tablename__ = "api_key"

    app_name: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    read_access: Mapped[bool] = mapped_column(Boolean, default=False)
    write_access: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index(
            "uq_api_key_app_name_active",
            "app_name",
            unique=True,
            postgresql_where=text("is_active = TRUE"),
        ),
    )
