from typing import TYPE_CHECKING, List
from sqlalchemy import String, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.pv import PV


class TagGroup(Base, UUIDMixin, TimestampMixin):
    """Tag group for organizing tags."""
    __tablename__ = "tag_group"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    tags: Mapped[List["Tag"]] = relationship(
        "Tag",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class Tag(Base, UUIDMixin, TimestampMixin):
    """Individual tag within a group."""
    __tablename__ = "tag"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("tag_group.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Relationships
    group: Mapped["TagGroup"] = relationship("TagGroup", back_populates="tags")
    pvs: Mapped[List["PV"]] = relationship(
        "PV",
        secondary="pv_tag",
        back_populates="tags"
    )
