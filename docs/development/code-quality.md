# Code Quality

This guide covers linting, formatting, and type checking for Squirrel Backend.

## Tools Overview

| Tool | Purpose |
|------|---------|
| **Ruff** | Linting and formatting |
| **MyPy** | Static type checking |
| **Pre-commit** | Git hooks for automated checks |

## Ruff

Ruff is an extremely fast Python linter and formatter.

### Linting

```bash
# Check for issues
ruff check .

# Check specific file/directory
ruff check app/services/

# Show all issues with explanation
ruff check . --show-fixes
```

### Auto-fix

```bash
# Fix auto-fixable issues
ruff check . --fix

# Fix and show what changed
ruff check . --fix --show-fixes
```

### Formatting

```bash
# Format all files
ruff format .

# Check formatting without changing files
ruff format . --check

# Format specific file
ruff format app/main.py
```

### Configuration

Ruff is configured in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # Pyflakes
    "I",      # isort
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "UP",     # pyupgrade
]
ignore = [
    "E501",   # line too long (handled by formatter)
]

[tool.ruff.lint.isort]
known-first-party = ["app"]
```

## MyPy

MyPy performs static type checking.

### Running MyPy

```bash
# Check all code
mypy app/

# Check specific module
mypy app/services/

# Show error codes
mypy app/ --show-error-codes
```

### Configuration

MyPy is configured in `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = false
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "tests.*"
ignore_errors = true
```

### Type Hints Best Practices

```python
from typing import Optional, List
from uuid import UUID

async def get_pv_by_id(pv_id: UUID) -> Optional[PV]:
    """Get a PV by its ID."""
    ...

async def search_pvs(
    query: str,
    limit: int = 100,
    offset: int = 0
) -> List[PV]:
    """Search for PVs matching a query."""
    ...
```

## Pre-commit Hooks

Pre-commit runs checks automatically before each commit.

### Installation

```bash
# Install pre-commit
pip install pre-commit

# Install git hooks
pre-commit install
```

### Running Manually

```bash
# Run on all files
pre-commit run --all-files

# Run specific hook
pre-commit run ruff --all-files

# Skip hooks for a commit
git commit --no-verify -m "WIP"
```

### Configuration

Pre-commit is configured in `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies:
          - types-redis
          - sqlalchemy[mypy]
```

## Code Style Guidelines

### Imports

Organize imports in this order:

1. Standard library
2. Third-party packages
3. Local imports

```python
import asyncio
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.pv import PVCreate, PVResponse
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `PVService` |
| Functions | snake_case | `get_pv_by_id` |
| Variables | snake_case | `pv_count` |
| Constants | UPPER_SNAKE | `MAX_BATCH_SIZE` |
| Private | _leading_underscore | `_internal_method` |

### Docstrings

Use Google-style docstrings:

```python
async def create_snapshot(
    title: str,
    pv_ids: List[UUID],
    use_cache: bool = True
) -> Snapshot:
    """Create a new snapshot of PV values.

    Args:
        title: Human-readable name for the snapshot.
        pv_ids: List of PV IDs to include.
        use_cache: If True, read from Redis cache. If False, read from EPICS.

    Returns:
        The created Snapshot object.

    Raises:
        ValueError: If no PV IDs are provided.
        EPICSError: If EPICS read fails and use_cache is False.
    """
    ...
```

### Async/Await

Always use `async/await` for I/O operations:

```python
# Good
async def get_pv(pv_id: UUID) -> Optional[PV]:
    return await self.repository.get_by_id(pv_id)

# Bad - blocks the event loop
def get_pv_sync(pv_id: UUID) -> Optional[PV]:
    return self.repository.get_by_id_sync(pv_id)
```

## CI/CD Integration

Code quality checks run in GitHub Actions:

```yaml
# .github/workflows/pre-commit.yml
name: Pre-commit

on:
  pull_request:
    branches: [main]

jobs:
  pre-commit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - uses: pre-commit/action@v3.0.0
```

## Quick Reference

```bash
# Format and lint
ruff format . && ruff check . --fix

# Type check
mypy app/

# Run all checks (like CI)
pre-commit run --all-files

# Full quality check
ruff format . && ruff check . --fix && mypy app/ && pytest
```
