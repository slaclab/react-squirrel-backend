# Database Migrations

Squirrel Backend uses Alembic for database schema migrations.

## Basic Commands

### Apply Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Apply to a specific revision
alembic upgrade abc123

# Apply next migration only
alembic upgrade +1
```

### Rollback Migrations

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to a specific revision
alembic downgrade abc123

# Rollback all migrations
alembic downgrade base
```

### Check Status

```bash
# Show current migration
alembic current

# Show migration history
alembic history

# Show pending migrations
alembic history --indicate-current
```

## Creating Migrations

### Auto-generate from Model Changes

After modifying SQLAlchemy models:

```bash
alembic revision --autogenerate -m "description of changes"
```

This compares the current models to the database and generates a migration script.

### Manual Migration

For complex changes:

```bash
alembic revision -m "description of changes"
```

Then edit the generated file in `alembic/versions/`.

## Migration File Structure

```python
"""Add device column to PV table

Revision ID: abc123def456
Revises: 789ghi012jkl
Create Date: 2024-01-15 10:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = 'abc123def456'
down_revision: Union[str, None] = '789ghi012jkl'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pvs', sa.Column('device', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('pvs', 'device')
```

## Best Practices

### 1. Always Test Migrations

```bash
# Test upgrade
alembic upgrade head

# Test downgrade
alembic downgrade -1

# Re-apply
alembic upgrade head
```

### 2. Keep Migrations Small

One logical change per migration:

- Adding a column
- Creating a table
- Adding an index

### 3. Handle Data Migrations

When you need to transform existing data:

```python
def upgrade() -> None:
    # Add new column
    op.add_column('pvs', sa.Column('full_address', sa.String(500)))

    # Populate it with existing data
    op.execute("""
        UPDATE pvs
        SET full_address = setpoint_address || ':' || COALESCE(readback_address, '')
    """)

    # Make it non-nullable if needed
    op.alter_column('pvs', 'full_address', nullable=False)
```

### 4. Use Transactions

Alembic runs migrations in transactions by default. For DDL that can't be in transactions (like `CREATE INDEX CONCURRENTLY`):

```python
def upgrade() -> None:
    op.execute('COMMIT')  # End current transaction
    op.create_index(
        'ix_pvs_setpoint_address',
        'pvs',
        ['setpoint_address'],
        postgresql_concurrently=True
    )
```

## Running in Docker

```bash
# Run migrations in the API container
docker exec -it squirrel-api alembic upgrade head

# Check current status
docker exec -it squirrel-api alembic current

# Create a new migration
docker exec -it squirrel-api alembic revision --autogenerate -m "add new column"
```

## Troubleshooting

### Migration Not Detected

If `--autogenerate` doesn't detect changes:

1. Ensure models are imported in `alembic/env.py`
2. Check that the model inherits from `Base`
3. Verify the table name is correct

### Conflicting Migrations

When multiple branches have migrations:

```bash
# Show branch heads
alembic heads

# Merge branches
alembic merge -m "merge migrations" abc123 def456
```

### Database Out of Sync

If the database doesn't match any migration:

```bash
# Mark current state as a specific revision
alembic stamp abc123

# Then upgrade from there
alembic upgrade head
```

### Reset Database

For development, sometimes it's easier to start fresh:

```bash
# Drop and recreate database
docker exec -it squirrel-db dropdb -U squirrel squirrel
docker exec -it squirrel-db createdb -U squirrel squirrel

# Re-run all migrations
alembic upgrade head

# Re-seed data
python -m scripts.seed_pvs --count 100
```

## Alembic Configuration

### alembic.ini

Key settings:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel

[logging]
level = INFO
```

### env.py

The `alembic/env.py` file configures how migrations run:

```python
from app.models.base import Base
from app.config import settings

# Import all models so Alembic can detect them
from app.models import pv, snapshot, tag, job

target_metadata = Base.metadata

def get_url():
    return settings.database_url
```
