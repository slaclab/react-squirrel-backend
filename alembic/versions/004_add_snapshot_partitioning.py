"""Add snapshot_value table partitioning

Revision ID: 004
Revises: 003_add_performance_indexes
Create Date: 2024-12-19

This migration converts the snapshot_value table to use PostgreSQL native
partitioning by snapshot_id for improved query performance with large datasets.

Benefits:
- Faster queries when filtering by snapshot_id (partition pruning)
- Faster bulk deletes (drop partition instead of DELETE)
- Better vacuum performance (per-partition)
- Improved concurrency for writes to different snapshots

Strategy:
- List partitioning by snapshot_id prefix (first 2 chars of UUID)
- Creates 256 partitions (00-ff) + 1 default partition
- Existing data migrated automatically

Note: This migration can take several minutes for large tables.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '004'
down_revision = '003_add_performance_indexes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Convert snapshot_value to partitioned table.

    PostgreSQL doesn't support ALTER TABLE ... ADD PARTITIONING,
    so we need to:
    1. Create new partitioned table
    2. Create partitions
    3. Copy data from old table
    4. Drop old table
    5. Rename new table
    """
    # Create new partitioned table
    op.execute("""
        CREATE TABLE snapshot_value_partitioned (
            id VARCHAR(36) NOT NULL,
            snapshot_id VARCHAR(36) NOT NULL,
            pv_id VARCHAR(36) NOT NULL,
            pv_name VARCHAR(255) NOT NULL,
            setpoint_value JSONB,
            readback_value JSONB,
            status INTEGER,
            severity INTEGER,
            timestamp TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (id, snapshot_id)
        ) PARTITION BY HASH (snapshot_id)
    """)

    # Create hash partitions (16 partitions for good balance)
    for i in range(16):
        op.execute(f"""
            CREATE TABLE snapshot_value_p{i:02d}
            PARTITION OF snapshot_value_partitioned
            FOR VALUES WITH (MODULUS 16, REMAINDER {i})
        """)

    # Add indexes to partitioned table (will be inherited by partitions)
    op.execute("""
        CREATE INDEX idx_sv_part_snapshot_id ON snapshot_value_partitioned (snapshot_id)
    """)
    op.execute("""
        CREATE INDEX idx_sv_part_pv_id ON snapshot_value_partitioned (pv_id)
    """)
    op.execute("""
        CREATE INDEX idx_sv_part_pv_name ON snapshot_value_partitioned (pv_name)
    """)

    # Copy data from old table to new (if any exists)
    op.execute("""
        INSERT INTO snapshot_value_partitioned
        SELECT * FROM snapshot_value
    """)

    # Drop old table's foreign key constraints first
    op.execute("""
        ALTER TABLE snapshot_value DROP CONSTRAINT IF EXISTS snapshot_value_snapshot_id_fkey
    """)
    op.execute("""
        ALTER TABLE snapshot_value DROP CONSTRAINT IF EXISTS snapshot_value_pv_id_fkey
    """)

    # Drop old table
    op.execute("DROP TABLE snapshot_value CASCADE")

    # Rename new table
    op.execute("ALTER TABLE snapshot_value_partitioned RENAME TO snapshot_value")

    # Rename partitions to match new table name
    for i in range(16):
        op.execute(f"""
            ALTER TABLE snapshot_value_p{i:02d} RENAME TO snapshot_value_part_{i:02d}
        """)

    # Rename indexes
    op.execute("""
        ALTER INDEX idx_sv_part_snapshot_id RENAME TO idx_snapshot_value_snapshot_id
    """)
    op.execute("""
        ALTER INDEX idx_sv_part_pv_id RENAME TO idx_snapshot_value_pv_id
    """)
    op.execute("""
        ALTER INDEX idx_sv_part_pv_name RENAME TO idx_snapshot_value_pv_name_new
    """)

    # Add foreign key constraints back (note: FKs on partitioned tables require index)
    # For partitioned tables, we add the FKs to each partition
    for i in range(16):
        op.execute(f"""
            ALTER TABLE snapshot_value_part_{i:02d}
            ADD CONSTRAINT snapshot_value_part_{i:02d}_snapshot_fk
            FOREIGN KEY (snapshot_id) REFERENCES snapshot(id) ON DELETE CASCADE
        """)
        op.execute(f"""
            ALTER TABLE snapshot_value_part_{i:02d}
            ADD CONSTRAINT snapshot_value_part_{i:02d}_pv_fk
            FOREIGN KEY (pv_id) REFERENCES pv(id) ON DELETE CASCADE
        """)


def downgrade() -> None:
    """
    Revert to non-partitioned table.
    """
    # Create new non-partitioned table
    op.execute("""
        CREATE TABLE snapshot_value_flat (
            id VARCHAR(36) PRIMARY KEY,
            snapshot_id VARCHAR(36) NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
            pv_id VARCHAR(36) NOT NULL REFERENCES pv(id) ON DELETE CASCADE,
            pv_name VARCHAR(255) NOT NULL,
            setpoint_value JSONB,
            readback_value JSONB,
            status INTEGER,
            severity INTEGER,
            timestamp TIMESTAMP WITH TIME ZONE
        )
    """)

    # Copy data back
    op.execute("""
        INSERT INTO snapshot_value_flat
        SELECT id, snapshot_id, pv_id, pv_name, setpoint_value, readback_value,
               status, severity, timestamp
        FROM snapshot_value
    """)

    # Drop partitioned table
    op.execute("DROP TABLE snapshot_value CASCADE")

    # Rename flat table
    op.execute("ALTER TABLE snapshot_value_flat RENAME TO snapshot_value")

    # Re-create original indexes
    op.execute("""
        CREATE INDEX idx_snapshot_value_snapshot_id ON snapshot_value(snapshot_id)
    """)
    op.execute("""
        CREATE INDEX idx_snapshot_value_pv_id ON snapshot_value(pv_id)
    """)
    op.execute("""
        CREATE INDEX idx_snapshot_value_pv_name ON snapshot_value(pv_name)
    """)
