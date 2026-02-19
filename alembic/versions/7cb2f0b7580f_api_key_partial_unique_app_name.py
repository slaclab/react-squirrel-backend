"""api_key_partial_unique_app_name

Revision ID: 7cb2f0b7580f
Revises: 004_add_api_key
Create Date: 2026-02-19 15:05:00.198022

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7cb2f0b7580f'
down_revision: Union[str, None] = '004_add_api_key'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Replace the existing unique constraints on app_name with a partial unique index that only applies to active API keys
    op.drop_constraint(op.f('api_key_app_name_key'), 'api_key', type_='unique')
    op.create_index('uq_api_key_app_name_active', 'api_key', ['app_name'], unique=True, postgresql_where=sa.text('is_active = TRUE'))

    # Remove indexes that are no longer needed
    op.drop_index(op.f('idx_pv_device'), table_name='pv')
    op.drop_index(op.f('idx_pv_readback_address'), table_name='pv')
    op.drop_index(op.f('idx_pv_search'), table_name='pv', postgresql_using='gin')
    op.drop_index(op.f('idx_pv_setpoint_address'), table_name='pv')
    op.drop_index(op.f('idx_snapshot_value_pv_name'), table_name='snapshot_value')
    op.drop_index(op.f('idx_snapshot_value_snapshot_pv'), table_name='snapshot_value')


def downgrade() -> None:
    # Restore the dropped indexes
    op.create_index(op.f('idx_snapshot_value_snapshot_pv'), 'snapshot_value', ['snapshot_id', 'pv_id'], unique=False)
    op.create_index(op.f('idx_snapshot_value_pv_name'), 'snapshot_value', ['pv_name'], unique=False)
    op.create_index(op.f('idx_pv_setpoint_address'), 'pv', ['setpoint_address'], unique=False)
    op.create_index(op.f('idx_pv_search'), 'pv', [sa.literal_column("to_tsvector('english'::regconfig, (((((COALESCE(setpoint_address, ''::character varying)::text || ' '::text) || COALESCE(readback_address, ''::character varying)::text) || ' '::text) || COALESCE(device, ''::character varying)::text) || ' '::text) || COALESCE(description, ''::text))")], unique=False, postgresql_using='gin')
    op.create_index(op.f('idx_pv_readback_address'), 'pv', ['readback_address'], unique=False)
    op.create_index(op.f('idx_pv_device'), 'pv', ['device'], unique=False)

    # Restore the original unique constraint on app_name
    op.drop_index('uq_api_key_app_name_active', table_name='api_key', postgresql_where=sa.text('is_active = TRUE'))
    op.create_unique_constraint(op.f('api_key_app_name_key'), 'api_key', ['app_name'], postgresql_nulls_not_distinct=False)
