# Development Guide

This guide covers setting up a development environment and contributing to Squirrel Backend.

For the project layout, see [Architecture › Directory Structure](../architecture/index.md#directory-structure).
For detailed local-install steps, see [Installation › Local Development](../getting-started/installation.md#option-2-local-development).

## Development Workflow

### Making Changes

1. Create a feature branch
2. Make your changes
3. Run tests: `pytest`
4. Run linting: `ruff check .`
5. Run type checking: `mypy app/`
6. Submit a pull request

### Hot Reload

The API server supports hot reload with `--reload`:

```bash
uvicorn app.main:app --reload --port 8000
```

Changes to Python files will automatically restart the server.

### Debugging

Enable debug logging:

```bash
export SQUIRREL_DEBUG=true
uvicorn app.main:app --reload --port 8000
```

## Utility Scripts

The `scripts/` directory contains management commands for API keys. See [API Key Management](../getting-started/api-keys.md) for full usage of `create_key.py`, `list_keys.py`, and `deactivate_key.py`.

## IDE Setup

### VS Code

Recommended extensions:

- Python
- Pylance
- Ruff

Settings (`.vscode/settings.json`):

```json
{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.analysis.typeCheckingMode": "basic",
    "[python]": {
        "editor.formatOnSave": true,
        "editor.codeActionsOnSave": {
            "source.fixAll": "explicit",
            "source.organizeImports": "explicit"
        },
        "editor.defaultFormatter": "charliermarsh.ruff"
    }
}
```

### PyCharm

1. Set project interpreter to `./venv/bin/python`
2. Enable Ruff plugin
3. Configure pytest as default test runner

## Pre-commit Hooks

The project uses pre-commit hooks for code quality:

```bash
# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

## Next Steps

- [Testing](testing.md) — running and writing tests
- [Database Migrations](migrations.md) — managing schema changes
- [Code Quality](code-quality.md) — linting and formatting
