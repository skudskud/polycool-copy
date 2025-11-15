# Alert Channel Bot

Telegram bot service that receives smart trading trade notifications and sends formatted alerts to a Telegram channel.

## Features

- **Webhook Receiver**: Receives real-time trade notifications from main bot
- **Database Poller**: Fallback mechanism that polls database every 60 seconds
- **Message Formatting**: Formats alerts with smart_score and confidence_score
- **Rate Limiting**: 10 alerts/hour, 60s minimum interval
- **Deduplication**: Tracks sent trades to prevent duplicates
- **History Logging**: Full history of all alerts sent

## Architecture

```
Main Bot (polycool-rebuild)
    ↓ (webhook)
Alert Channel Bot (this service)
    ↓ (Telegram API)
Telegram Channel (@polycool_alerts)
```

## Configuration

### Environment Variables

```bash
# Telegram Bot
BOT_TOKEN=your_telegram_bot_token
BOT_USERNAME=@PolycoolAlertBot
TELEGRAM_CHANNEL_ID=@polycool_alerts
MAIN_BOT_LINK=https://t.me/polycool_alerts

# Database (Supabase)
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:password@host:port/postgres

# Service Configuration
ALERT_WEBHOOK_PORT=8000
POLL_INTERVAL_SECONDS=60

# Rate Limiting
RATE_LIMIT_MAX_PER_HOUR=10
RATE_LIMIT_MIN_INTERVAL_SECONDS=60

# Filtering Criteria
MIN_TRADE_VALUE=300.0
MIN_WIN_RATE=0.55
MAX_AGE_MINUTES=5

# Logging
LOG_LEVEL=INFO
```

### Main Bot Integration

The main bot needs to set:
```bash
ALERT_CHANNEL_BOT_URL=https://polycool-copy-production.up.railway.app
```

## Database Tables

- `alert_channel_sent`: Deduplication table (tracks which trades were sent)
- `alert_channel_history`: Full history of all alerts (analytics & debugging)

## API Endpoints

- `GET /health`: Health check endpoint
- `POST /api/v1/alert-channel/notify`: Webhook endpoint for trade notifications

## Deployment

Deployed on Railway as a separate service:
- Project: `amused-playfulness`
- Service: `polycool-copy`
- Root Directory: `polycool-rebuild/alert-channel-bot`

## Message Format

Alerts are formatted exactly like the old alert channel:
- Market title
- Trade time
- Wallet address (shortened)
- Win Rate & Smart Score
- Position details
- Side (BUY Yes/No)
- Confidence Score (visual with 🟢/⚫ circles)

