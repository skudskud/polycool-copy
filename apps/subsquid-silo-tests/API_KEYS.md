# API Keys & Secret Management

Guide for managing API keys, credentials, and secrets for the Subsquid Silo Tests.

## Overview

This project requires several API credentials for:
- **Database**: Supabase PostgreSQL
- **Cache**: Redis (staging)
- **Blockchain**: Polygon RPC endpoint
- **Market Data**: PolyMarket APIs (CLOB, Gamma)

## Security Best Practices

### DO ✅
- Use `.env.example` as template (commit this)
- Store secrets in `.env` (never commit this)
- Use Railway's built-in secret management for production
- Rotate credentials regularly
- Use staging credentials for development

### DON'T ❌
- Never commit `.env` file with real secrets
- Never paste secrets in code or comments
- Never share credentials in Slack/Discord
- Never use production credentials for testing
- Never hardcode API keys in source files

## Local Development (.env)

### Template (.env.example)

```bash
# Database (Supabase Staging)
DATABASE_URL=postgresql://user:password@staging.supabase.co:5432/postgres

# Redis (Staging)
REDIS_URL=redis://default:password@staging-redis.railway.internal:6379/0

# PolyMarket APIs
GAMMA_API_URL=https://gamma-api.polymarket.com
CLOB_WSS_URL=wss://ws.clob.polymarket.com
CLOB_REST_URL=https://clob.polymarket.com

# On-Chain
POLYGON_RPC_URL=https://polygon-rpc.com

# Feature Flag
EXPERIMENTAL_SUBSQUID=true

# Logging
LOG_LEVEL=INFO
```

### Setup Steps

1. **Create `.env` from template:**
   ```bash
   cp .env.example .env
   ```

2. **Get Supabase Staging Credentials:**
   - Log in to Supabase dashboard
   - Select staging project
   - Settings → Database → Connection String
   - Copy full URL (includes password)
   - Paste into `DATABASE_URL`

3. **Get Redis Staging Credentials:**
   - Log in to Railway dashboard
   - Find Redis instance
   - Copy connection string
   - Paste into `REDIS_URL`

4. **Get Polygon RPC:**
   - Use public RPC: `https://polygon-rpc.com`
   - Or get premium from Alchemy/Infura if needed

5. **Verify:**
   ```bash
   # Test database connection
   psql $DATABASE_URL -c "SELECT 1"
   
   # Test Redis connection
   redis-cli -u $REDIS_URL PING
   ```

## PolyMarket API Access

### Gamma API

**Endpoint:** `https://gamma-api.polymarket.com`

**No API Key Required** (public API)

**Rate Limits:**
- Default: 10 requests per second
- Per IP: 1000 requests per hour

**Example:**
```bash
curl https://gamma-api.polymarket.com/markets?active=true
```

### CLOB WebSocket

**Endpoint:** `wss://ws.clob.polymarket.com`

**No API Key Required** (public WebSocket)

**Channels:**
- `market` - Market data (orderbook, trades)
- `user` - User-specific data (if authenticated)

**Example:**
```bash
wscat -c wss://ws.clob.polymarket.com

# Subscribe to market
{"type":"subscribe","market_id":"0x..."}
```

### CLOB REST API

**Endpoint:** `https://clob.polymarket.com`

**No Authentication Required** for public queries

**Rate Limits:**
- 10 requests per second (IP-based)

**Example:**
```bash
curl https://clob.polymarket.com/markets?active=true
```

## Railway Secrets Management

### Add Secret to Railway Service

```bash
# Set environment variable
railway variable DATABASE_URL postgresql://...

# Verify (doesn't show value)
railway variable list

# Delete if needed
railway variable delete DATABASE_URL
```

### Secure Handoff Between Services

Use Railway's built-in networking:

```bash
# Poller → Database
DATABASE_URL=postgresql://user:pass@postgres:5432/db

# Bridge → Webhook
REDIS_BRIDGE_WEBHOOK_URL=http://webhook:8081/wh/market
```

### Production Setup

1. **Create Railway Project:** `railway new subsquid-silo-prod`
2. **Add Supabase:** Create production database in Supabase
3. **Add Redis:** Create production Redis in Railway
4. **Set Variables:**
   ```bash
   railway variable DATABASE_URL postgresql://prod...
   railway variable REDIS_URL redis://prod...
   ```
5. **Deploy:** `railway up --service poller`

## Accessing Staging Databases

### Supabase Staging

```bash
# View dashboard
# https://app.supabase.com → Select project

# Command line
psql postgresql://user:pass@staging.supabase.co:5432/postgres

# Inside psql
\c postgres                    # Connect to postgres db
\dt subsquid_*                # List our tables
SELECT COUNT(*) FROM subsquid_markets_poll;
```

### Railway Redis Staging

```bash
# Via Railway CLI
railway shell
redis-cli -u $REDIS_URL DBSIZE
KEYS subsquid_*

# Or directly
redis-cli -u redis://staging... PING
```

## Credential Rotation

### When to Rotate

- Quarterly (regular maintenance)
- Immediately if leaked
- When team member leaves
- After security incident

### Rotation Steps

1. **Create new credentials** (in target service)
2. **Update in local `.env`**
3. **Verify working** (test connections)
4. **Update in Railway** (one service at a time)
5. **Monitor for 1 hour** (check logs for errors)
6. **Revoke old credentials** (in source service)

### Database Password Rotation

```bash
# In Supabase
1. Go to project settings
2. Database → Users → Edit postgres user
3. Set new password
4. Update DATABASE_URL in .env
5. Test: psql $DATABASE_URL -c "SELECT 1"
6. Update Railway variables
7. Restart services: railway restart
```

### Redis Password Rotation

```bash
# In Railway
1. Pause Redis service
2. Delete and recreate with new password
3. Copy new connection string
4. Update REDIS_URL in .env
5. Test: redis-cli -u $REDIS_URL PING
6. Update Railway variables
7. Restart services: railway restart
```

## Audit Trail

### View Who Accessed What

**Supabase:**
- Settings → Logs → Query Performance
- Shows SQL queries, timestamps, users

**Railway:**
- Deployment history with timestamps
- Variable change logs
- Service restart logs

### Log Examples

```bash
# Check recent database access
psql $DATABASE_URL -c "
  SELECT 
    query, 
    query_start,
    usename
  FROM pg_stat_statements
  WHERE query LIKE '%subsquid%'
  ORDER BY query_start DESC
  LIMIT 10;
"

# Check Redis access
redis-cli -u $REDIS_URL MONITOR
```

## Emergency Access

### Lost Credentials

```bash
# Database
# 1. Go to Supabase dashboard
# 2. Settings → Database → Connection String (reset if needed)

# Redis
# 1. Go to Railway dashboard
# 2. Find Redis service
# 3. Copy new connection string

# Never share credentials directly!
# Use password manager or Railway's secret management
```

### Compromised Credentials

**Immediate Actions:**

1. **Revoke access:**
   ```bash
   # Database
   psql -U postgres << EOF
   ALTER ROLE silo_user PASSWORD 'new_random_password';
   EOF

   # Redis
   # Delete and recreate in Railway
   ```

2. **Update everywhere:**
   - Local `.env`
   - Railway production
   - All developer machines

3. **Audit logs:**
   - Check what was accessed
   - Review for suspicious activity
   - Consider data breach protocol

4. **Notify team:**
   - Alert all developers
   - Update security procedures
   - Document incident

## Testing Secret Management

### Verify No Secrets in Code

```bash
# Search for common secret patterns
grep -r "postgresql://" src/
grep -r "redis://" src/
grep -r "api.key" src/
grep -r "api_key" src/

# Should return no results!
```

### Verify Environment Variables Work

```bash
# In Docker
docker-compose exec orchestrator env | grep DATABASE_URL

# On Railway
railway shell
echo $DATABASE_URL
```

### Integration Test

```bash
# Run tests with test credentials
pytest tests/ -v

# Should pass without hardcoded secrets
```

## Checklist

- [ ] `.env.example` created and committed
- [ ] `.env` created locally (not committed)
- [ ] `DATABASE_URL` points to staging
- [ ] `REDIS_URL` points to staging
- [ ] All env vars in `.env.example` have values
- [ ] Tested local connections work
- [ ] Railway variables set for production
- [ ] No secrets in git history (`git log --grep="password"`)
- [ ] No secrets in code comments
- [ ] Team members have access instructions
- [ ] Rotation schedule established
- [ ] Audit trail reviewed monthly

## Resources

- Supabase Docs: https://supabase.com/docs/guides/database/connecting-to-postgres
- Railway Docs: https://docs.railway.app/
- PolyMarket Docs: https://docs.polymarket.com/
- Security Best Practices: https://owasp.org/www-community/Secrets_Management

## Support

### Credentials Not Working?

1. Check `.env` file exists and has correct values
2. Verify staging services are running
3. Check firewall/VPN if off-network
4. Look at logs: `docker-compose logs orchestrator`
5. Test connection directly: `psql $DATABASE_URL -c "SELECT 1"`

### Need New Credentials?

1. Contact project lead
2. Request via secure channel (not Slack)
3. Follow rotation procedure above
4. Test before committing to production

---

**Never commit `.env` file. Keep credentials secure!** 🔐
