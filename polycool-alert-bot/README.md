# Polycool Alert Bot 🔥

A Telegram bot that monitors smart wallet trades on Polymarket and sends real-time alerts.

## 🎯 Purpose

This is a **marketing/lead generation bot** that:
- Tracks smart traders (Very Smart bucket, >55% win rate)
- Alerts on first-time market entries
- Redirects users to the main copy trading bot
- Operates independently from main trading infrastructure

## 🏗️ Architecture

```
polycool-alert-bot/
├── config/           # Configuration settings
├── core/             # Core business logic
│   ├── database.py   # Database operations
│   ├── poller.py     # Main polling loop
│   ├── filters.py    # Trade quality & rate limiting
│   └── health.py     # Health monitoring
├── telegram/         # Telegram bot integration
│   ├── bot.py        # Bot initialization
│   └── formatter.py  # Message formatting
├── utils/            # Utilities
│   ├── logger.py     # Logging
│   └── metrics.py    # Metrics tracking
├── migrations/       # Database migrations
└── main.py           # Entry point
```

## 📊 Database Tables

The bot uses **isolated tables** in your existing Supabase:

- `alert_bot_sent` - Tracks sent alerts (prevents duplicates)
- `alert_bot_rate_limit` - Enforces 10 alerts/hour limit
- `alert_bot_stats` - Daily statistics
- `alert_bot_health` - Real-time health monitoring
- `alert_bot_pending_trades` (view) - Quality trades ready to alert

## 🚀 Deployment

### Prerequisites

1. **Run Database Migration**
   ```bash
   # In Supabase SQL Editor, run:
   migrations/001_create_alert_bot_tables.sql
   ```

2. **Set Environment Variables in Railway**
   ```
   BOT_TOKEN=8306437331:AAGdsKk3Ntr9wYR_EoMTTMEP1fQ-Fn2b6dE
   BOT_USERNAME=@PolycoolAlertBot
   TELEGRAM_CHANNEL_ID=@your_channel_or_chat_id
   DATABASE_URL=postgresql://...
   MAIN_BOT_LINK=https://t.me/YourMainBot
   LOG_LEVEL=INFO
   DRY_RUN=false
   ```

### Railway Deployment

1. Create new Railway service: "polycool-alert-bot"
2. Link to this repository
3. Set root directory: `/polycool-alert-bot`
4. Add environment variables
5. Deploy!

## 🎛️ Configuration

### Filters (Aggressive Mode)

Located in `config/settings.py`:

```python
FILTERS = {
    'is_first_time': True,      # Only first-time market entries
    'min_value': 200,            # Minimum $200 trades
    'bucket_smart': 'Very Smart', # Only top-tier traders
    'require_market_question': True,
}
```

### Rate Limiting

```python
RATE_LIMITS = {
    'max_per_hour': 10,          # Max 10 alerts/hour
    'min_interval_seconds': 60,  # 1 min between alerts
}
```

### Polling

```python
POLL_INTERVAL_SECONDS = 30  # Check every 30 seconds
```

## 📱 Bot Commands

- `/start` - Welcome message
- `/stats` - View daily statistics
- `/health` - Check bot health

## 🧪 Testing Locally

1. **Install dependencies**
   ```bash
   cd polycool-alert-bot
   pip install -r requirements.txt
   ```

2. **Set up .env**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Run in dry-run mode**
   ```bash
   export DRY_RUN=true
   python main.py
   ```

4. **Check logs**
   - Should see: "Would send alert for trade..."
   - No actual messages sent in dry-run mode

## 📊 Monitoring

### Database Queries

```sql
-- Check pending trades
SELECT COUNT(*) FROM alert_bot_pending_trades;

-- Recent alerts
SELECT * FROM alert_bot_sent ORDER BY sent_at DESC LIMIT 10;

-- Today's stats
SELECT * FROM alert_bot_stats WHERE date = CURRENT_DATE;

-- Bot health
SELECT * FROM alert_bot_health;

-- Rate limit status
SELECT * FROM alert_bot_rate_limit 
WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
ORDER BY hour_bucket DESC;
```

### Expected Performance

- **30-50 quality trades per day**
- **2-4 alerts per hour** (well under 10/hour limit)
- **<2 minute latency** from trade to alert
- **0% duplicate alerts**

## 🔧 Troubleshooting

### Bot not starting

1. Check environment variables are set
2. Verify database connection string
3. Ensure migration was run
4. Check logs for errors

### No alerts being sent

1. Check `alert_bot_pending_trades` view has data
2. Verify TELEGRAM_CHANNEL_ID is correct
3. Check rate limit hasn't been hit
4. Look for filter skip reasons in logs

### Too many/few alerts

Adjust filters in `config/settings.py`:
- Increase `min_value` to reduce alerts
- Decrease `min_value` to increase alerts
- Add `min_win_rate` filter for quality

## 🔗 Integration with Main Bot

When users click "Start Copy Trading Bot" in alerts:
- They're redirected to your main trading bot
- Deep linking can be added for specific markets
- Track conversions via Telegram analytics

## 📈 Success Metrics

- **Alert Volume**: 10-30 per day
- **Alert Quality**: >80% user engagement
- **Conversion Rate**: % clicking through to main bot
- **Uptime**: >99%
- **Latency**: <2 minutes trade-to-alert

## 🛠️ Future Enhancements

- [ ] Multi-channel support (different channels for different categories)
- [ ] Customizable filters per user
- [ ] Performance tracking (alert → market outcome)
- [ ] Advanced analytics dashboard
- [ ] A/B testing message formats

## 📝 License

Part of the py-clob-client-with-bots project.

---

**Built with ❤️ for the Polymarket community**

