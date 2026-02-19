"""Add api_key table for application access tokens

Revision ID: 004_add_api_key
Revises: 003_perf_indexes
Create Date: 2026-02-19

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_add_api_key"
down_revision: str | None = "003_perf_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("app_name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("read_access", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("write_access", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_name"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_api_key_token_hash"), "api_key", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_api_key_token_hash"), table_name="api_key")
    op.drop_table("api_key")
