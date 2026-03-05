# Deployment Runbook (Dev and Prod)

This project uses one codebase and two deployment environments:
- `dev` for testing and non-critical data
- `prod` for production workloads

## 1) Files Added for Environment Separation

- `docker/docker-compose.dev.yml`
- `docker/docker-compose.prod.yml`
- `.env.dev.example`
- `.env.prod.example`
- `.github/workflows/deploy-dev-prod.yml`

## 2) Environment Variables

Create real env files from templates:

```bash
cp .env.dev.example .env.dev
cp .env.prod.example .env.prod
```

Edit both files with real values.

Important:
- `dev` must point to non-critical EPICS gateways.
- `prod` must point to production gateways.
- Keep secrets out of git.

## 3) Local Dev Startup

Use dev compose:

```bash
docker compose -f docker/docker-compose.dev.yml --env-file .env.dev up -d --build
```

Service check:

```bash
docker compose -f docker/docker-compose.dev.yml --env-file .env.dev ps
```

Stop:

```bash
docker compose -f docker/docker-compose.dev.yml --env-file .env.dev down
```

## 4) Production Runtime Model

`docker/docker-compose.prod.yml` expects:
- External Postgres (from `.env.prod`)
- External Redis (from `.env.prod`)
- Prebuilt app image via `SQUIRREL_IMAGE`

Manual prod launch example:

```bash
export SQUIRREL_IMAGE=ghcr.io/<org>/<repo>:sha-<commit>
docker compose -f docker/docker-compose.prod.yml --env-file .env.prod pull
docker compose -f docker/docker-compose.prod.yml --env-file .env.prod up -d
```

## 5) CI/CD Workflow

Workflow: `.github/workflows/deploy-dev-prod.yml`

Behavior:
- Push to `main` -> build image -> deploy to `dev`
- Push tag `v*` -> build image -> deploy to `prod`

Required GitHub secrets:

Dev:
- `DEV_SSH_HOST`
- `DEV_SSH_USER`
- `DEV_SSH_KEY`

Prod:
- `PROD_SSH_HOST`
- `PROD_SSH_USER`
- `PROD_SSH_KEY`

Also configure GitHub Environments:
- `dev`
- `prod` (recommended: require manual approval)

## 6) First-Time Server Bootstrap

On target host(s):

1. Install Docker and Docker Compose plugin.
2. Clone repo to deployment path (workflow expects `/opt/react-squirrel-backend`).
3. Create env file:
   - `/opt/react-squirrel-backend/.env.dev` for dev host
   - `/opt/react-squirrel-backend/.env.prod` for prod host
4. Verify registry pull access (for GHCR private images if needed).
5. Run the compose commands from section 4.

## 7) Database Migrations

Run Alembic before or during deploy (policy decision):

```bash
source venv/bin/activate
alembic upgrade head
```

Recommended:
- auto-migrate in `dev`
- gated/approved migrate in `prod`

## 8) Health and Smoke Checks

After deployment:

1. API health (if endpoint exists)
```bash
curl -f http://<host>:8000/docs >/dev/null
```

2. Worker startup logs
```bash
docker logs --tail=100 <worker-container-name>
```

3. Monitor startup logs
```bash
docker logs --tail=100 <monitor-container-name>
```

## 9) Rollback

Rollback by redeploying a previous image tag:

```bash
export SQUIRREL_IMAGE=ghcr.io/<org>/<repo>:sha-<previous-commit>
docker compose -f docker/docker-compose.prod.yml --env-file .env.prod up -d
```

If a DB migration is incompatible, restore from backup before rollback.

## 10) Security Checklist

- Do not commit `.env.dev` or `.env.prod`.
- Use unique credentials for dev/prod.
- Use Redis auth in both environments.
- Restrict prod SSH keys to deployment-only accounts.
- Use GitHub Environment approval for `prod` deploys.
