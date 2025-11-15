# Subsquid TypeScript Indexer - Polymarket Copy Trading

Indexes Conditional Tokens Transfer events on Polygon blockchain for real-time copy trading transaction tracking.

## Architecture

```
Polygon Blockchain (Conditional Tokens)
    ↓ Transfer events
Subsquid EVM Indexer (TypeScript)
    ↓ Parse: market_id, outcome, tx_type (BUY/SELL)
    ↓ Write: subsquid_user_transactions (price=NULL initially)
PostgreSQL (Supabase)
    ↓ Read by
Background Job (60s interval)
    ↓ Enrich prices from subsquid_markets_poll.last_mid
Telegram Bot (Python)
    ↓ Copy Trading Logic
```

## Quick Start

### Local Setup

```bash
# Install dependencies
npm install

# Compile TypeScript
npm run build

# Create .env with your database credentials
cp .env.example .env

# Run indexer
npm start

# In another terminal, run price enrichment job
npm run enrich
```

### Environment Variables

```bash
# Database
DB_HOST=db.gvckzwmuuyrlcyjmgdpo.supabase.co
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password

# RPC Endpoint for Polygon
RPC_POLYGON_HTTP=https://polygon-mainnet.g.alchemy.com/v2/your_key
```

## Data Flow

### 1. Event Indexing
- Listens to Conditional Tokens `Transfer` events on Polygon
- Parses:
  - `token_id` → extract `market_id` and `outcome` (0=NO, 1=YES)
  - `from`/`to` addresses → determine `tx_type` (BUY/SELL)
  - Ignores burns (transfers to 0x0)
- Writes to `subsquid_user_transactions` with `price=NULL`

### 2. Price Enrichment (Background Job)
- Runs every 60 seconds
- Joins `subsquid_user_transactions` with `subsquid_markets_poll`
- Fills in `price` column with `last_mid` from market data
- Enables copy trading bot to execute with accurate pricing

### 3. Copy Trading Integration
Bot reads from `subsquid_user_transactions`:
- Detects new fills from tracked traders
- Looks up leader address in `copy_trading_subscriptions`
- Executes matching orders for all followers
- Uses enriched prices for sizing and execution

## Database Schema

### `subsquid_user_transactions` (written by indexer)
```sql
tx_id              TEXT PRIMARY KEY      -- {txHash}_{logIndex}
user_address       TEXT NOT NULL         -- Wallet address of trader
market_id          TEXT NOT NULL         -- Market ID (numeric string)
outcome            INT NOT NULL          -- 0=NO, 1=YES
amount             NUMERIC(18,8)         -- Token amount
price              NUMERIC(8,4)          -- Filled price (NULL → enriched to last_mid)
tx_hash            TEXT NOT NULL         -- Transaction hash on Polygon
timestamp          TIMESTAMPTZ NOT NULL  -- Block timestamp
```

## Deployment

### Railway Setup

1. Link repository:
```bash
railway link
```

2. Create indexer service:
```bash
railway up -d apps/subsquid-silo-tests/indexer-ts
```

3. Set environment variables on Railway UI:
   - `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
   - `RPC_POLYGON_HTTP`

4. Monitor logs:
```bash
railway logs
```

### Price Enrichment Service (optional separate service)

Create second Railway service for background job:
```bash
railway service create price-enricher
railway up -d apps/subsquid-silo-tests/indexer-ts --service price-enricher
```

Start Command: `npm run enrich`

## Verification

### Check if transactions are being indexed:
```sql
SELECT COUNT(*) FROM subsquid_user_transactions;
SELECT * FROM subsquid_user_transactions LIMIT 5;
```

### Check if prices are being enriched:
```sql
SELECT 
  COUNT(*) as total,
  COUNT(price) as with_price,
  COUNT(*) - COUNT(price) as without_price
FROM subsquid_user_transactions;
```

### Real-time transaction view:
```sql
SELECT 
  ut.tx_id,
  ut.user_address,
  ut.market_id,
  ut.outcome,
  CASE WHEN ut.outcome = 0 THEN 'NO' ELSE 'YES' END as outcome_name,
  ut.amount,
  ut.price,
  ut.timestamp,
  mp.title as market_title
FROM subsquid_user_transactions ut
LEFT JOIN subsquid_markets_poll mp ON mp.market_id::text = ut.market_id
WHERE ut.timestamp > NOW() - INTERVAL '1 hour'
ORDER BY ut.timestamp DESC
LIMIT 20;
```

## Event Parsing

### Token ID Encoding
PolyMarket uses ERC1155 token IDs to encode market and outcome:
```
token_id = market_id * 2 + outcome
```

Example:
- Market ID 248905, Outcome YES (1) → token_id = 248905*2 + 1 = 497811
- Market ID 248905, Outcome NO (0) → token_id = 248905*2 + 0 = 497810

### Transaction Classification
- **BUY**: `from` is 0x0 (minting), `to` is user → user bought YES/NO
- **SELL**: both `from` and `to` are non-zero (transfer between users) → user sold position
- **BURN** (ignored): `to` is 0x0 → ignore (redemption, not user trading)

## Performance

- **Block start**: ~50M (Polygon, ~2 days ago from mainnet height)
- **Finality**: 75 blocks (~3 minutes)
- **Price enrichment**: Every 60 seconds
- **Estimated latency** for copy trading: ~70 seconds (indexer + enrichment)

## Troubleshooting

### Indexer not starting
```bash
npm install
npm run build
# Check .env variables are set
```

### No transactions appearing
- Check RPC endpoint is accessible: `curl $RPC_POLYGON_HTTP`
- Verify Conditional Tokens contract address: `0xd5524179cb7ae012f5b642c1d6d700a289d07fb3`
- Check database connection: `psql $DATABASE_URL`

### Prices not enriching
- Verify `subsquid_markets_poll` has recent data (Poller running?)
- Check background job is running: `ps aux | grep enrich`
- Run manually: `npm run enrich`

## Related Services

- **Poller** (Python): Fetches market metadata from Gamma API every 60s
- **Streamer** (Python): Real-time prices from CLOB WebSocket
- **Telegram Bot** (Python): Executes copy trading based on indexed fills
- **Redis Bridge** (Python): Forwards real-time events to database

## References

- [Subsquid Documentation](https://docs.subsquid.io)
- [Conditional Tokens Contract](https://etherscan.io/token/0xd5524179cb7ae012f5b642c1d6d700a289d07fb3) (Polygon)
- [PolyMarket Copy Trading Architecture](../COPY_TRADING_ARCHITECTURE.md)
