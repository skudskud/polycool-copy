-- ========================================
-- Subsquid Silo Tests Migration
-- ========================================
-- Created: 2025-11-21
-- Description: Test tables for 3 off-chain pipelines (polling, WS, webhook) + on-chain indexer (DipDup)
-- Purpose: Isolated schema to test new data ingestion modes without impacting production

-- ========================================
-- 1. OFF-CHAIN: Polling (Gamma API) → subsquid_markets_poll
-- ========================================
CREATE TABLE IF NOT EXISTS subsquid_markets_poll (
    -- Identifiers
    market_id TEXT PRIMARY KEY,
    condition_id TEXT,
    slug TEXT UNIQUE,

    -- Market info
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,

    -- Status
    status TEXT,                        -- 'ACTIVE' or 'CLOSED'
    accepting_orders BOOLEAN DEFAULT false,
    archived BOOLEAN DEFAULT false,
    tradeable BOOLEAN DEFAULT false,

    -- Outcomes & prices (4 decimals)
    outcomes TEXT[],                    -- Array of outcome names: ['Yes', 'No']
    outcome_prices NUMERIC(8,4)[],      -- Array of prices: [0.6500, 0.3500]
    last_mid NUMERIC(8,4),              -- Mid price: (sum of prices) / count

    -- Volumes (4 decimals)
    volume NUMERIC(12,4),               -- Total volume
    volume_24hr NUMERIC(12,4),          -- 24h volume
    volume_1wk NUMERIC(12,4),           -- 1 week volume
    volume_1mo NUMERIC(12,4),           -- 1 month volume

    -- Liquidity & trading
    liquidity NUMERIC(12,4),            -- Total liquidity
    spread INTEGER,                     -- Spread in basis points

    -- Dates
    created_at TIMESTAMPTZ,             -- Market creation date
    end_date TIMESTAMPTZ,               -- Expected resolution date
    resolution_date TIMESTAMPTZ,        -- Actual resolution date (if closed)

    -- Price changes (4 decimals)
    price_change_1h NUMERIC(8,4),       -- 1 hour change
    price_change_1d NUMERIC(8,4),       -- 1 day change
    price_change_1w NUMERIC(8,4),       -- 1 week change

    -- CLOB tokens
    clob_token_ids TEXT,                -- JSON array of token IDs

    -- Events (parent events like "Who wins Superbowl 2026")
    events JSONB,                       -- Array of: {event_id, event_slug, event_title, event_category, event_volume}

    -- Metadata
    market_type TEXT DEFAULT 'normal',  -- 'normal' or other types
    restricted BOOLEAN DEFAULT false,

    -- Timestamps
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subsquid_markets_poll_updated_at
    ON subsquid_markets_poll(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_subsquid_markets_poll_status
    ON subsquid_markets_poll(status);
CREATE INDEX IF NOT EXISTS idx_subsquid_markets_poll_slug
    ON subsquid_markets_poll(slug);
CREATE INDEX IF NOT EXISTS idx_subsquid_markets_poll_category
    ON subsquid_markets_poll(category);
CREATE INDEX IF NOT EXISTS idx_subsquid_markets_poll_tradeable
    ON subsquid_markets_poll(tradeable);

COMMENT ON TABLE subsquid_markets_poll IS 'Markets data from Gamma API polling (60s interval) - enriched with all metadata, outcomes, volumes, events';

-- ========================================
-- 2. OFF-CHAIN: WebSocket (CLOB) → subsquid_markets_ws
-- ========================================
CREATE TABLE IF NOT EXISTS subsquid_markets_ws (
    market_id TEXT PRIMARY KEY,
    title TEXT,
    status TEXT,
    expiry TIMESTAMPTZ,
    last_bb NUMERIC(8,4),         -- Best bid
    last_ba NUMERIC(8,4),         -- Best ask
    last_mid NUMERIC(8,4),        -- Mid = (BB + BA) / 2
    last_trade_price NUMERIC(8,4),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subsquid_markets_ws_updated_at
    ON subsquid_markets_ws(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_subsquid_markets_ws_status
    ON subsquid_markets_ws(status);

COMMENT ON TABLE subsquid_markets_ws IS 'Markets data from CLOB WebSocket with real-time pricing';

-- ========================================
-- 3. OFF-CHAIN: Webhook (Redis Pub/Sub → Internal HTTP) → subsquid_markets_wh
-- ========================================
CREATE TABLE IF NOT EXISTS subsquid_markets_wh (
    id BIGSERIAL PRIMARY KEY,
    market_id TEXT NOT NULL,
    event TEXT NOT NULL,           -- e.g., 'market.status.active', 'clob.trade'
    payload JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subsquid_markets_wh_market_id_updated_at
    ON subsquid_markets_wh(market_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_subsquid_markets_wh_event
    ON subsquid_markets_wh(event);

COMMENT ON TABLE subsquid_markets_wh IS 'Webhook events from Redis Pub/Sub bridge (simulated internal webhooks)';

-- ========================================
-- 4. OFF-CHAIN: Event Metadata (parent of markets)
-- ========================================
CREATE TABLE IF NOT EXISTS subsquid_events (
    event_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT,                   -- 'active', 'closed', 'resolved'
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subsquid_events_status
    ON subsquid_events(status);
CREATE INDEX IF NOT EXISTS idx_subsquid_events_updated_at
    ON subsquid_events(updated_at DESC);

COMMENT ON TABLE subsquid_events IS 'Parent events (e.g., Superbowl 2026) containing multiple markets';

-- ========================================
-- 5. ON-CHAIN: DipDup - Conditional Token Fills → subsquid_fills_onchain
-- ========================================
CREATE TABLE IF NOT EXISTS subsquid_fills_onchain (
    fill_id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    user_address TEXT NOT NULL,
    outcome TEXT NOT NULL,         -- 'yes' or 'no'
    amount NUMERIC(18,8) NOT NULL,
    price NUMERIC(8,4) NOT NULL,
    tx_hash TEXT NOT NULL,
    block_number BIGINT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subsquid_fills_onchain_user_address_ts
    ON subsquid_fills_onchain(user_address, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_subsquid_fills_onchain_market_id_ts
    ON subsquid_fills_onchain(market_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_subsquid_fills_onchain_tx_hash
    ON subsquid_fills_onchain(tx_hash);

COMMENT ON TABLE subsquid_fills_onchain IS 'On-chain fills indexed by DipDup from Conditional Token transfers (Polygon)';

-- ========================================
-- 6. ON-CHAIN: DipDup - User Transactions (for copy trading)
-- ========================================
CREATE TABLE IF NOT EXISTS subsquid_user_transactions (
    tx_id TEXT PRIMARY KEY,
    user_id BIGINT,                -- Telegram user_id (nullable if not mapped)
    user_address TEXT NOT NULL,
    market_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    amount NUMERIC(18,8) NOT NULL,
    price NUMERIC(8,4) NOT NULL,
    tx_hash TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subsquid_user_transactions_user_id_ts
    ON subsquid_user_transactions(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_subsquid_user_transactions_market_id
    ON subsquid_user_transactions(market_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_subsquid_user_transactions_user_address
    ON subsquid_user_transactions(user_address);

COMMENT ON TABLE subsquid_user_transactions IS 'User-specific transactions indexed by DipDup, used for copy trading analysis';

-- ========================================
-- UPSERT Helpers (convenience functions for Python)
-- ========================================
-- These are provided for reference. Python code will handle upserts via asyncpg/psycopg2.

-- ========================================
-- Verify creation
-- ========================================
-- Run this query to verify all tables were created:
-- SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE 'subsquid_%';
