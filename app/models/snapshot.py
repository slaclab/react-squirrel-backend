from datetime import datetime
from typing import TYPE_CHECKING, List, Any
from sqlalchemy import String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.pv import PV


class Snapshot(Base, UUIDMixin, TimestampMixin):
    """Snapshot of all PV values at a point in time."""
    __tablename__ = "snapshot"

    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    values: Mapped[List["SnapshotValue"]] = relationship(
        "SnapshotValue",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class SnapshotValue(Base, UUIDMixin):
    """Captured value of a single PV in a snapshot."""
    __tablename__ = "snapshot_value"

    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("snapshot.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    pv_id: Mapped[str] = mapped_column(
        ForeignKey("pv.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Captured PV name (denormalized for query performance)
    pv_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Value data (JSONB for flexibility with arrays, scalars, etc.)
    setpoint_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    readback_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # EPICS metadata
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)  # EPICS status
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # EPICS severity
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="values")
    pv: Mapped["PV"] = relationship("PV", back_populates="snapshot_values")
