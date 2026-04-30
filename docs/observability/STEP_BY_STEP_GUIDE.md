# Squirrel Analytics (Loki + Promtail + Grafana) — Complete Step‑by‑Step Guide

This is a long, beginner‑friendly guide. It assumes no prior experience with logs, monitoring, or Grafana.

If you follow the steps in order, you will end up with a live dashboard showing how people use Squirrel.

---

## Table of Contents

1. What This Gives You
2. What You Need Before Starting
3. Overview of How It Works
4. Step 1 — Start the Backend
5. Step 2 — Start Observability (Grafana + Loki + Promtail)
6. Step 3 — Open Grafana
7. Step 4 — Import the Dashboard
8. Step 5 — Start the Frontend (UI)
9. Step 6 — Generate Analytics Events
10. Step 7 — Verify Events Are Flowing
11. Where Logs Are Written
12. What Type of Logs These Are
13. How Logs Are Read and Shipped
14. What Loki Does
15. What Grafana Does
16. How to Add a New Tracked Action
17. Common Issues and Fixes
18. Full Reset (Start From Scratch)
19. Quick Reference Commands

---

## 1. What This Gives You

- A clear view of how people use Squirrel
- A dashboard that updates automatically
- Searchable analytics logs stored in Loki

You will see things like:
- Page views
- Snapshot create / restore events
- PV browser usage and filtering
- Tag creation and edits

---

## 2. What You Need Before Starting

- Docker Desktop installed and running
- This repository cloned on your computer

---

## 3. Overview of How It Works

Think of it as a pipeline:

```
Squirrel Backend writes logs
-> Promtail reads the log file
-> Promtail sends logs to Loki
-> Grafana shows dashboards from Loki data
```

Each step must be running for the dashboard to show data.

---

## 4. Step 1 — Start the Backend

From the repository root:

```bash
docker compose -f react-squirrel-backend/docker/docker-compose.yml up -d
```

This starts:
- Postgres database
- Redis
- Squirrel backend API
- Worker
- Monitor

---

## 5. Step 2 — Start Observability (Grafana + Loki + Promtail)

From the repository root:

```bash
docker compose -f react-squirrel-backend/docker/observability/docker-compose.observability.yml up -d
```

This starts:
- Loki (log storage)
- Promtail (log shipper)
- Grafana (dashboards)

---

## 6. Step 3 — Open Grafana

Open your browser and go to:

```
http://localhost:3000
```

Login:
- Username: `admin`
- Password: `admin`

Grafana may ask you to change the password. You can do it or skip it for local use.

---

## 7. Step 4 — Import the Dashboard

1. In Grafana, click `Dashboards` → `New` → `Import`
2. Upload this file:

```
react-squirrel-backend/docs/observability/grafana-analytics-dashboard.json
```

3. Click `Import`

Now the dashboard appears in your list.

---

## 8. Step 5 — Start the Frontend (UI)

From the repository root:

```bash
cd react-squirrel
pnpm install
pnpm run dev
```

Open the URL printed in your terminal, usually:

```
http://localhost:5173
```

---

## 9. Step 6 — Generate Analytics Events

Just click around the UI. Every click you make creates analytics events:

- Page views
- Snapshot create / restore
- PV browsing, search, filters
- Tag creation and edits

---

## 10. Step 7 — Verify Events Are Flowing

This is the most important check. Use the steps below.

### Check the log file

```bash
tail -n 5 /tmp/squirrel-logs/backend.log
```

You should see lines like:

```
2026-04-28 23:46:33,219 - analytics - INFO - {"type": "analytics", "event": "page_view", ...}
```

### Check Promtail

```bash
docker logs --tail=20 squirrel-promtail
```

You should see that it is tailing `/tmp/squirrel-logs/backend.log`.

### Check Loki

```bash
curl -s "http://localhost:3100/loki/api/v1/labels" | python3 -m json.tool
```

If Loki shows labels such as `event` and `route`, it is receiving data.

---

## 11. Where Logs Are Written

The backend writes logs to this file by default:

```
/tmp/squirrel-logs/backend.log
```

This path is set in:

- `react-squirrel-backend/app/logging_config.py`

If you want to change the path, set the environment variable:

```
SQUIRREL_LOG_PATH=/your/path/backend.log
```

---

## 12. What Type of Logs These Are

Analytics logs are JSON‑formatted events, inside normal log lines.

Example log line:

```
2026-04-28 23:46:33,219 - analytics - INFO - {"type": "analytics", "event": "page_view", "route": "/snapshots", ...}
```

That JSON is what Loki and Grafana care about.

---

## 13. How Logs Are Read and Shipped

Promtail is the tool that **reads** the log file and **ships** it to Loki.

Promtail is configured here:

- `react-squirrel-backend/docker/observability/promtail-config.yaml`

Key settings inside:

- `__path__` tells Promtail which file to read
- `pipeline_stages` tells Promtail how to parse the JSON

---

## 14. What Loki Does

Loki is a log database. It stores the logs in a way that Grafana can search and graph.

Loki runs in Docker in the observability stack:

- `squirrel-loki` container
- Accessible at `http://localhost:3100`

Promtail pushes logs to Loki using the Loki HTTP API.

---

## 15. What Grafana Does

Grafana is the dashboard tool.

Grafana queries Loki and shows charts such as:

- Page views over time
- Snapshot success vs failure
- PV browser usage
- Tag changes

Grafana runs in Docker in the observability stack:

- `squirrel-grafana` container
- Accessible at `http://localhost:3000`

---

## 16. How to Add a New Tracked Action

You can add analytics in **two places**: frontend or backend.

### Frontend (UI)

Call this function:

```
analyticsService.track({ event: "your_event_name", properties: { ... } })
```

Location:
- `react-squirrel/src/services/analyticsService.ts`

Typical usage:
- Page views
- Button clicks
- Filter usage

### Backend

Call this function:

```
log_analytics_event("your_event_name", source="backend", properties={...})
```

Location:
- `react-squirrel-backend/app/services/analytics_service.py`

Typical usage:
- Snapshot completed
- Restore failed
- Background jobs finished

---

## 17. Common Issues and Fixes

### Issue: Dashboard is empty

Possible causes:
- UI is not running
- Backend logs are not being written
- Promtail is not shipping logs
- Grafana is querying the wrong time range

Fix checklist:

1. Check backend logs:

```bash
tail -n 5 /tmp/squirrel-logs/backend.log
```

2. Check Promtail:

```bash
docker logs --tail=20 squirrel-promtail
```

3. Check Loki labels:

```bash
curl -s "http://localhost:3100/loki/api/v1/labels" | python3 -m json.tool
```

4. In Grafana, set time range to `Last 15 minutes`

---

### Issue: UI won’t start because API_KEY is missing

Fix:

1. Create a new API key (if no keys exist):

```bash
curl -s -X POST http://localhost:8080/v1/api-keys/bootstrap | python3 -m json.tool
```

2. Set the token in `react-squirrel/.env`:

```
API_KEY=your_token_here
```

---

### Issue: Database fails to start

Cause: Missing environment variables.

Fix by setting defaults in:

- `react-squirrel-backend/docker/.env`

Values:

```
POSTGRES_USER=username
POSTGRES_PASSWORD=password
POSTGRES_DB=squirrel
REDIS_PASSWORD=password
SQUIRREL_DEBUG=false
```

---

## 18. Full Reset (Start From Scratch)

Warning: This deletes containers and volumes.

```bash
docker stop $(docker ps -q)
docker rm $(docker ps -a -q)
docker volume rm $(docker volume ls -q)
```

Then start again from Step 4.

---

## 19. Quick Reference Commands

Start backend:

```bash
docker compose -f react-squirrel-backend/docker/docker-compose.yml up -d
```

Start observability:

```bash
docker compose -f react-squirrel-backend/docker/observability/docker-compose.observability.yml up -d
```

Check backend logs:

```bash
tail -n 5 /tmp/squirrel-logs/backend.log
```

Check Promtail:

```bash
docker logs --tail=20 squirrel-promtail
```

Check Loki:

```bash
curl -s http://localhost:3100/ready
```

Open Grafana:

```
http://localhost:3000
```

---

## Summary

- Backend writes analytics logs to `/tmp/squirrel-logs/backend.log`
- Promtail reads the file and ships logs to Loki
- Loki stores logs and makes them searchable
- Grafana visualizes the data

You now have a full analytics pipeline for Squirrel.
