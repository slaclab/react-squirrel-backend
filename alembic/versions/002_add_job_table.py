"""Add job table for async task tracking

Revision ID: 002_add_job
Revises: 001_initial
Create Date: 2024-12-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_add_job'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create job table for tracking async background tasks
    op.create_table(
        'job',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('message', sa.String(length=255), nullable=True),
        sa.Column('result_id', sa.String(length=36), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('job_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_type'), 'job', ['type'], unique=False)
    op.create_index(op.f('ix_job_status'), 'job', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_job_status'), table_name='job')
    op.drop_index(op.f('ix_job_type'), table_name='job')
    op.drop_table('job')
