# Railway Multi-Service Deployment Guide

This guide explains how to deploy the Polycool stack to Railway using separate services:

| Service            | Role                                                     | Start command            |
|--------------------|----------------------------------------------------------|--------------------------|
| `polycool-api`     | FastAPI HTTP API (no bot / workers)                      | `python api_only.py`     |
| `polycool-bot`     | Telegram bot runtime (no HTTP server)                    | `python bot_only.py`     |
| `polycool-workers` | Streamer, poller, TP/SL monitor, Redis Pub/Sub listeners | `python workers.py`      |
| `polycool-indexer` | Subsquid TypeScript indexer (separate repository folder) | `npm start`              |
| `Redis`            | Managed Redis instance (Railway add-on)                  | Managed by Railway       |

The repository ships with dedicated entry points (`api_only.py`, `bot_only.py`, `workers.py`)
and Railway configuration files (`railway.json`, `railway.bot.json`, `railway.workers.json`).
The `scripts/deployment/push_service.sh` helper script automates switching configs before
calling `railway up`.

## 1. Prerequisites

1. Install the [Railway CLI](https://docs.railway.com/develop/cli).
2. Log in and link the project:
   ```bash
   railway login
   railway link -p cheerful-fulfillment
   ```
3. Ensure the workspace is on the project root (`/Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild`).
4. Supabase credentials must already exist (project `xxzdlbwfyetaxcmodiec`). Use the Supabase MCP tools (`mcp_supabase_*`) if you need to inspect the database or regenerate API keys.

## 2. Create the Railway services

You can create empty services (or verify that they exist) with:

```bash
railway service create redis --name polycool-redis            # Optional if Redis already exists
railway service create --name polycool-api
railway service create --name polycool-bot
railway service create --name polycool-workers
railway service create --name polycool-indexer
```

Alternatively, use the Railway dashboard to provision the services. Make sure Redis is a managed datastore so all runtime instances can use the same cache.

## 3. Configure environment variables

All Python services share the same secret values. Start from `.env.local` (or `env.template`)
and copy variables to each Railway service:

```bash
# Example – repeat for bot/workers/indexer (as needed)
railway variables --service polycool-api --set "DATABASE_URL=postgresql://..."
railway variables --service polycool-api --set "REDIS_URL=redis://default:...@redis.railway.internal:6379"
railway variables --service polycool-api --set "CLOB_API_KEY=..."
railway variables --service polycool-api --set "CLOB_API_SECRET=..."
railway variables --service polycool-api --set "CLOB_API_PASSPHRASE=..."
railway variables --service polycool-api --set "TELEGRAM_BOT_TOKEN=..."
railway variables --service polycool-api --set "ENCRYPTION_KEY=..."
railway variables --service polycool-api --set "STREAMER_ENABLED=false"    # API does not launch workers
railway variables --service polycool-api --set "TPSL_MONITORING_ENABLED=false"
```

Recommended overrides:

| Service            | Override                                                                 |
|--------------------|---------------------------------------------------------------------------|
| `polycool-api`     | `STREAMER_ENABLED=false`, `TPSL_MONITORING_ENABLED=false`                 |
| `polycool-bot`     | `STREAMER_ENABLED=false`, `TPSL_MONITORING_ENABLED=false`                 |
| `polycool-workers` | `STREAMER_ENABLED=true`, `TPSL_MONITORING_ENABLED=true`, leave bot token? |
| `polycool-workers` | Remove Telegram webhook specific variables (not required)                |
| `polycool-indexer` | Provide Subsquid/Postgres/Redis URLs as per `indexer-ts/README.md`        |

> Tip: For bulk updates, call `railway variables --service <name> --set "$(cat .env.production | sed -n 's/^KEY=/KEY=/p')"` or script it via `scripts/deployment/push_service.sh`.

Use Supabase MCP to validate that RLS is enabled and tables are reachable:

```bash
mcp_supabase_list_tables(project_id="xxzdlbwfyetaxcmodiec")
```

## 4. Deploy services with the helper script

Use the `push_service.sh` script to update the correct service. The script temporarily swaps
`railway.json` with the matching config and restores it afterward.

```bash
# From the repository root
./scripts/deployment/push_service.sh api
./scripts/deployment/push_service.sh bot
./scripts/deployment/push_service.sh workers
./scripts/deployment/push_service.sh indexer
```

Each command wraps:

* `polycool-api` → uses `railway.json` (FastAPI entrypoint `api_only.py`)
* `polycool-bot` → copies `railway.bot.json` before running `railway up`
* `polycool-workers` → copies `railway.workers.json` before running `railway up`
* `polycool-indexer` → switches to `apps/subsquid-silo-tests/indexer-ts/` and runs `railway up`

If you prefer manual deployment:

```bash
# Deploy API manually
cp railway.bot.json railway.json
railway up --service polycool-bot
git checkout -- railway.json
```

## 5. Post-deploy verification

1. **API**
   ```bash
   curl https://polycool-api-production.up.railway.app/health/live
   curl https://polycool-api-production.up.railway.app/health/ready
   ```
   Use Railway logs if the status is not `{"status": "up"}`.

2. **Bot**
   ```bash
   railway logs --service polycool-bot | tail -20
   ```
   Expect to see “Telegram bot running”. Trigger `/start` in Telegram to confirm.

3. **Workers**
   ```bash
   railway logs --service polycool-workers | tail -50
   ```
   Look for messages indicating streamer, TP/SL monitor, and copy-trading listener started.

4. **Indexer**
   ```bash
   railway logs --service polycool-indexer | tail -50
   ```
   Ensure the Subsquid indexer is processing blocks and publishing to Redis.

5. **Redis**
   ```bash
   railway variables --service polycool-redis | grep REDIS_URL
   ```
   Confirm all services reference the same internal URL.

6. **Database**
   Run Supabase MCP diagnostics if needed:
   ```bash
   mcp_supabase_get_project(id="xxzdlbwfyetaxcmodiec")
   ```

## 6. Monitoring & rollbacks

* Use `railway logs --service <name>` for streaming logs.
* `railway deployment list --service <name>` to inspect past deploys.
* Roll back by re-deploying the last successful build: `railway redeploy --service <name>`.
* For emergency disable, scale the service to zero or pause it via the Railway dashboard.

## 7. Known operational tips

* Keep `STREAMER_ENABLED` and `TPSL_MONITORING_ENABLED` disabled on services that do not handle workers.
* The bot service requires the same env vars as the API (database, Redis, secrets).
* `workers.py` shuts down gracefully on `SIGTERM` to avoid dangling websocket subscriptions.
* Ensure the Telegram webhook URL is set only on the service that actually runs the bot.
* The indexer runs inside the TypeScript project (`npm start`). Use its `railway.json` for deployments.

With this structure each component can scale independently, deployments are faster, and a failing worker no longer brings down the HTTP API or Telegram bot. All commands are safe to run repeatedly, and the helper script restores the original configuration after each deploy.
