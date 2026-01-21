"""Add performance indexes for filtering and snapshot operations

Revision ID: 003_perf_indexes
Revises: 002_add_job
Create Date: 2024-12-12

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_perf_indexes"
down_revision: str | None = "002_add_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # B-tree index for device filtering
    op.create_index("idx_pv_device", "pv", ["device"], unique=False)

    # Index for PV address lookups
    op.create_index("idx_pv_setpoint_address", "pv", ["setpoint_address"], unique=False)
    op.create_index("idx_pv_readback_address", "pv", ["readback_address"], unique=False)

    # Composite index for snapshot value queries
    op.create_index("idx_snapshot_value_snapshot_pv", "snapshot_value", ["snapshot_id", "pv_id"], unique=False)

    # Index for PV name lookups in snapshot values
    op.create_index("idx_snapshot_value_pv_name", "snapshot_value", ["pv_name"], unique=False)

    # GIN index for text search (optional - for full-text search)
    # Note: This creates a GIN index for efficient ILIKE searches
    op.execute(
        """
        CREATE INDEX idx_pv_search ON pv
        USING gin(
            to_tsvector('english',
                coalesce(setpoint_address, '') || ' ' ||
                coalesce(readback_address, '') || ' ' ||
                coalesce(device, '') || ' ' ||
                coalesce(description, '')
            )
        )
    """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pv_search")
    op.drop_index("idx_snapshot_value_pv_name", table_name="snapshot_value")
    op.drop_index("idx_snapshot_value_snapshot_pv", table_name="snapshot_value")
    op.drop_index("idx_pv_readback_address", table_name="pv")
    op.drop_index("idx_pv_setpoint_address", table_name="pv")
    op.drop_index("idx_pv_device", table_name="pv")
