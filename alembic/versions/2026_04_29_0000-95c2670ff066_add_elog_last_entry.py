"""Add elog_last_entry table for follow-up parent pre-fill.

Revision ID: 95c2670ff066
Revises: 6c1c0c2f8a1b
Create Date: 2026-04-29 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "95c2670ff066"
down_revision: str | None = "6c1c0c2f8a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "elog_last_entry",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("api_key_id", sa.UUID(), nullable=False),
        sa.Column("logbooks_key", sa.String(length=1024), nullable=False),
        sa.Column("entry_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_key.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("api_key_id", "logbooks_key", name="uq_elog_last_entry_scope"),
    )
    op.create_index("ix_elog_last_entry_api_key_id", "elog_last_entry", ["api_key_id"])


def downgrade() -> None:
    op.drop_index("ix_elog_last_entry_api_key_id", table_name="elog_last_entry")
    op.drop_table("elog_last_entry")
