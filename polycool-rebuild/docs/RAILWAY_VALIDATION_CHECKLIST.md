# Railway Validation Checklist

Use this checklist after deploying the multi-service architecture to Railway.

## 1. CLI & project linkage
- [ ] `railway status` shows `Project: cheerful-fulfillment`, `Environment: production`
- [ ] `railway list` includes `polycool-api`, `polycool-bot`, `polycool-workers`, `polycool-indexer`, and `Redis`

## 2. Environment variables
- [ ] `railway variables --service polycool-api` contains `DATABASE_URL`, `REDIS_URL`, `TELEGRAM_BOT_TOKEN`
- [ ] `railway variables --service polycool-bot` mirrors API secrets but keeps `STREAMER_ENABLED=false`
- [ ] `railway variables --service polycool-workers` has `STREAMER_ENABLED=true`, `TPSL_MONITORING_ENABLED=true`
- [ ] `railway variables --service polycool-indexer` contains Subsquid-specific values
- [ ] Redis service exposes the same `REDIS_URL` used by all runtimes

## 3. API service (`polycool-api`)
- [ ] `curl https://polycool-api-production.up.railway.app/health/live` returns HTTP 200
- [ ] `curl https://polycool-api-production.up.railway.app/health/ready` returns HTTP 200
- [ ] `railway logs --service polycool-api | tail -20` shows “Polycool API service startup complete”

## 4. Telegram bot (`polycool-bot`)
- [ ] `railway logs --service polycool-bot | tail -20` shows “Telegram bot running”
- [ ] `/start` command in Telegram replies successfully
- [ ] (Optional) Webhook configured if running in production mode (`WEBHOOK_URL`, `WEBHOOK_SECRET`)

## 5. Worker service (`polycool-workers`)
- [ ] `railway logs --service polycool-workers | tail -50` shows streamer, TP/SL monitor, copy-trading listener messages
- [ ] Redis Pub/Sub connection confirmed via logs (“Redis PubSub connected”)
- [ ] Watched-address cache sync logs appear every 5 minutes

## 6. Indexer (`polycool-indexer`)
- [ ] `railway logs --service polycool-indexer | tail -50` shows block processing / trade detection
- [ ] Redis publishes `copy_trade:*` messages when trades occur (check via Redis CLI if needed)

## 7. Supabase connectivity
- [ ] `mcp_supabase_list_tables(project_id="xxzdlbwfyetaxcmodiec")` returns the expected tables
- [ ] RLS policies verified (`docs/RLS_SECURITY_STATUS.md`)
- [ ] Database credentials rotateable (documented in `env.railway.example`)

## 8. Monitoring & rollbacks
- [ ] Alerts configured on Railway (optional) for failed deployments
- [ ] `railway deployment list --service <name>` shows last deploy as `SUCCESS`
- [ ] `railway redeploy --service <name>` tested on at least one service

Checking off every item ensures the stack is fully operational after each deployment. Save this checklist with release notes to keep a history of validation runs.
