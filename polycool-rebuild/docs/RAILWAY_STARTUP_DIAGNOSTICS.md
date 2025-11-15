# Railway Startup Diagnostics

## Symptom
- Deployments of the monolithic `polycool` service on Railway returned HTTP 502 (“Application failed to respond”).
- Logs were mostly empty because the process failed before the FastAPI server could start listening.
- Railway dashboard showed repeated crashes within ~60 seconds of boot.

## Root cause
The monolithic entrypoint (`telegram_bot/main.py`) launches **all** subsystems inside the FastAPI lifespan:

1. Database migrations (`init_db()`)
2. Cache manager initialization
3. Websocket streamer (`StreamerService.start`)
4. Redis Pub/Sub service
5. TP/SL monitor
6. Copy-trading listener
7. Watched-address cache sync
8. Telegram bot (polling/webhook)

On Railway the startup budget is limited (~30–45 seconds). The combined initialization time (especially the websocket handshake and copy-trading listener subscribing to Redis) routinely exceeds this window, so the process exits before FastAPI can bind the port. That leads to Railway’s health probe failing and the deployment staying in a crashed state.

## Resolution
Split the runtime into dedicated services with lean entrypoints:

- `api_only.py` → FastAPI only (no background workers)
- `bot_only.py` → Telegram bot only
- `workers.py` → streamer, poller, TP/SL monitor, copy-trading listener

Each service now starts in a few seconds, honoring Railway’s health checks while keeping background jobs independent. The helper script `scripts/deployment/push_service.sh` ensures each service uses the correct `railway*.json` configuration during deployment.
