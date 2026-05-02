# Squirrel Backend

High-performance Python FastAPI backend for EPICS control system snapshot/restore operations, designed to handle 40-50K PVs efficiently.

**Full documentation:** https://slaclab.github.io/react-squirrel-backend/

## Features

- **Distributed Architecture** — separate processes for API, PV monitoring, and background tasks
- **Fast Snapshot Creation** — instant Redis cache reads (<5s for 40K PVs), or direct EPICS reads for guaranteed-fresh values
- **Efficient Restore** — parallel EPICS writes for quick machine state restoration
- **Real-Time Updates** — WebSocket streaming with diff-based updates and multi-instance support
- **Tag-based Organization**, **Snapshot Comparison**, **Persistent Job Queue**, **Circuit Breaker**, **API Key Authentication**

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Database | PostgreSQL 16+ |
| ORM | SQLAlchemy 2.0 (async) |
| Cache/Queue | Redis 7+ |
| Task Queue | Arq |
| EPICS | aioca (Channel Access), p4p (PVAccess) |
| Migrations | Alembic |
| Validation | Pydantic v2 |

## Quick Start (Docker)

```bash
git clone https://github.com/slaclab/react-squirrel-backend.git
cd react-squirrel-backend/docker
cp .env.example .env              # edit for your EPICS network if needed
docker compose up -d --build     # migrations run automatically
docker exec squirrel-api python -m scripts.create_key my-app --read --write
```

The API is now available at http://localhost:8080 (Swagger docs at `/docs`).

!!! note
    The token printed by `create_key` is only shown once — save it. All endpoints require an `X-API-Key` header.

For local development, detailed setup, configuration, API reference, and architecture, see the [documentation site](https://slaclab.github.io/react-squirrel-backend/).

## Documentation

| Topic | Link |
|---|---|
| Getting Started | [docs/getting-started/](docs/getting-started/index.md) |
| Installation options | [docs/getting-started/installation.md](docs/getting-started/installation.md) |
| Configuration | [docs/getting-started/configuration.md](docs/getting-started/configuration.md) |
| API Keys | [docs/getting-started/api-keys.md](docs/getting-started/api-keys.md) |
| Architecture | [docs/architecture/](docs/architecture/index.md) |
| REST / WebSocket API | [docs/api-reference/](docs/api-reference/index.md) |
| Development | [docs/development/](docs/development/index.md) |

## Frontend

The React frontend lives at [slaclab/react-squirrel](https://github.com/slaclab/react-squirrel).

## License

Copyright © The Board of Trustees of the Leland Stanford Junior University, through SLAC National Accelerator Laboratory. Released under a 3-clause BSD–style license — see [LICENSE.md](LICENSE.md) for the full text.
