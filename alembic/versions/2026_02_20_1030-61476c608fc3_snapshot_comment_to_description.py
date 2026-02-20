"""snapshot_comment_to_description

Revision ID: 61476c608fc3
Revises: d365210f8676
Create Date: 2026-02-20 10:30:10.488591

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "61476c608fc3"
down_revision: str | None = "d365210f8676"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename the 'comment' column to 'description' in the 'snapshot' table.
    op.alter_column("snapshot", "comment", new_column_name="description")


def downgrade() -> None:
    # Rename the 'description' column back to 'comment' in the 'snapshot' table.
    op.alter_column("snapshot", "description", new_column_name="comment")
