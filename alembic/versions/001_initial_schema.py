"""Initial schema creation

Revision ID: 001_initial
Revises:
Create Date: 2024-12-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create tag_group table
    op.create_table(
        "tag_group",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tag_group_name"), "tag_group", ["name"], unique=True)

    # Create tag table
    op.create_table(
        "tag",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["tag_group.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tag_group_id"), "tag", ["group_id"], unique=False)

    # Create pv table
    op.create_table(
        "pv",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("setpoint_address", sa.String(length=255), nullable=True),
        sa.Column("readback_address", sa.String(length=255), nullable=True),
        sa.Column("config_address", sa.String(length=255), nullable=True),
        sa.Column("device", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("abs_tolerance", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("rel_tolerance", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pv_setpoint_address"), "pv", ["setpoint_address"], unique=True)
    op.create_index(op.f("ix_pv_readback_address"), "pv", ["readback_address"], unique=True)
    op.create_index(op.f("ix_pv_config_address"), "pv", ["config_address"], unique=True)
    op.create_index(op.f("ix_pv_device"), "pv", ["device"], unique=False)

    # Create pv_tag association table
    op.create_table(
        "pv_tag",
        sa.Column("pv_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["pv_id"], ["pv.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("pv_id", "tag_id"),
    )

    # Create snapshot table
    op.create_table(
        "snapshot",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_snapshot_title"), "snapshot", ["title"], unique=False)

    # Create snapshot_value table
    op.create_table(
        "snapshot_value",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("pv_id", sa.UUID(), nullable=False),
        sa.Column("pv_name", sa.String(length=255), nullable=False),
        sa.Column("setpoint_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("readback_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["pv_id"], ["pv.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_snapshot_value_snapshot_id"), "snapshot_value", ["snapshot_id"], unique=False)
    op.create_index(op.f("ix_snapshot_value_pv_id"), "snapshot_value", ["pv_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_snapshot_value_pv_id"), table_name="snapshot_value")
    op.drop_index(op.f("ix_snapshot_value_snapshot_id"), table_name="snapshot_value")
    op.drop_table("snapshot_value")
    op.drop_index(op.f("ix_snapshot_title"), table_name="snapshot")
    op.drop_table("snapshot")
    op.drop_table("pv_tag")
    op.drop_index(op.f("ix_pv_device"), table_name="pv")
    op.drop_index(op.f("ix_pv_config_address"), table_name="pv")
    op.drop_index(op.f("ix_pv_readback_address"), table_name="pv")
    op.drop_index(op.f("ix_pv_setpoint_address"), table_name="pv")
    op.drop_table("pv")
    op.drop_index(op.f("ix_tag_group_id"), table_name="tag")
    op.drop_table("tag")
    op.drop_index(op.f("ix_tag_group_name"), table_name="tag_group")
    op.drop_table("tag_group")
