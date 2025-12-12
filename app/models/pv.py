from typing import TYPE_CHECKING, List
from sqlalchemy import String, Float, Boolean, Text, Table, Column, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.tag import Tag
    from app.models.snapshot import SnapshotValue


# Association table for PV <-> Tag many-to-many
pv_tag = Table(
    "pv_tag",
    Base.metadata,
    Column("pv_id", ForeignKey("pv.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
)


class PV(Base, UUIDMixin, TimestampMixin):
    """Process Variable definition."""
    __tablename__ = "pv"

    # PV addresses (at least one required - enforced at service layer)
    setpoint_address: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    readback_address: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    config_address: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )

    # Metadata
    device: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tolerances for comparison
    abs_tolerance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rel_tolerance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Flags
    read_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    tags: Mapped[List["Tag"]] = relationship(
        "Tag",
        secondary=pv_tag,
        back_populates="pvs",
        lazy="selectin"
    )
    snapshot_values: Mapped[List["SnapshotValue"]] = relationship(
        "SnapshotValue",
        back_populates="pv",
        cascade="all, delete-orphan"
    )
