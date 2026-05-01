# Observability Stack (Loki + Promtail + Grafana)

This folder contains a standalone compose file for logs + dashboards.

## Start

From `react-squirrel-backend/docker/observability`:

```bash
docker compose -f docker-compose.observability.yml up -d
```

Grafana will be available at `http://localhost:3000` (default credentials: `admin` / `admin`).

## Log Path

Promtail is configured to read:

```
/tmp/squirrel-logs/backend.log
```

The backend now writes to this path by default (via `SQUIRREL_LOG_PATH`).
If you run the backend in Docker, the compose file mounts `/tmp/squirrel-logs` into the containers so the host path is populated.

If you want a different log location, update:

- `docker/observability/promtail-config.yaml` (`__path__`)
- `SQUIRREL_LOG_PATH` (env var)

## Import the Dashboard

Use the prebuilt dashboard JSON:

```
react-squirrel-backend/docs/observability/grafana-analytics-dashboard.json
```

In Grafana: `Dashboards` -> `New` -> `Import` -> upload the JSON.
