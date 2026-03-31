"""Adjust PV address uniqueness constraints.

Revision ID: 6c1c0c2f8a1b
Revises: 61476c608fc3
Create Date: 2026-03-10 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c1c0c2f8a1b"
down_revision: str | None = "61476c608fc3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_pv_readback_address"), table_name="pv")
    op.drop_index(op.f("ix_pv_config_address"), table_name="pv")

    op.create_index(op.f("ix_pv_readback_address"), "pv", ["readback_address"], unique=False)
    op.create_index(op.f("ix_pv_config_address"), "pv", ["config_address"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pv_readback_address"), table_name="pv")
    op.drop_index(op.f("ix_pv_config_address"), table_name="pv")

    op.create_index(op.f("ix_pv_readback_address"), "pv", ["readback_address"], unique=True)
    op.create_index(op.f("ix_pv_config_address"), "pv", ["config_address"], unique=True)
