"""Tracks the most recent elog entry id per (api_key, logbook set).

The PostToElogDialog uses this to pre-fill the parent entry id when an
operator wants to follow up on their previous post (typical workflow:
morning snapshot then hourly follow-ups for the rest of the day).
"""
from sqlalchemy import Index, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class ElogLastEntry(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "elog_last_entry"

    api_key_id: Mapped[str] = mapped_column(ForeignKey("api_key.id", ondelete="CASCADE"), nullable=False)
    logbooks_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    entry_id: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("api_key_id", "logbooks_key", name="uq_elog_last_entry_scope"),
        Index("ix_elog_last_entry_api_key_id", "api_key_id"),
    )
