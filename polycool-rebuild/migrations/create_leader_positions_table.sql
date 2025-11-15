-- =================================================
-- MIGRATION: Create Leader Positions Table
-- Date: November 9, 2025
-- Description: Track token quantities for leaders per market/outcome for position-based SELL calculations
-- Cumulates BUY (+), subtracts SELL (-) for real-time position tracking
-- =================================================

CREATE TABLE leader_positions (
    id SERIAL PRIMARY KEY,
    watched_address_id INTEGER NOT NULL REFERENCES watched_addresses(id) ON DELETE CASCADE,
    market_id VARCHAR(100) NOT NULL,
    outcome VARCHAR(10) NOT NULL, -- 'YES' or 'NO'

    -- Token quantity tracking (cumulative)
    token_quantity NUMERIC(20,6) NOT NULL DEFAULT 0, -- BUY adds, SELL subtracts

    -- Last trade reference
    last_trade_tx_hash VARCHAR(255),
    last_trade_timestamp TIMESTAMP WITHOUT TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),

    -- Unique constraint: one position per leader/market/outcome
    CONSTRAINT unique_leader_market_outcome UNIQUE (watched_address_id, market_id, outcome)
);

-- Indexes for performance
CREATE INDEX idx_leader_positions_watched_market ON leader_positions(watched_address_id, market_id);
CREATE INDEX idx_leader_positions_market ON leader_positions(market_id);
CREATE INDEX idx_leader_positions_updated ON leader_positions(updated_at);

-- Comments
COMMENT ON TABLE leader_positions IS 'Tracks cumulative token quantities for leaders per market/outcome. BUY adds tokens, SELL subtracts. Used for position-based SELL calculations.';
COMMENT ON COLUMN leader_positions.token_quantity IS 'Cumulative token quantity: BUY adds (+), SELL subtracts (-). No backfill - only tracks trades after table creation.';
COMMENT ON COLUMN leader_positions.last_trade_tx_hash IS 'Transaction hash of the last trade that updated this position';
COMMENT ON COLUMN leader_positions.last_trade_timestamp IS 'Timestamp of the last trade that updated this position';

-- =================================================
-- VERIFICATION QUERIES
-- =================================================

-- Check table was created
-- SELECT table_name FROM information_schema.tables
-- WHERE table_name = 'leader_positions';

-- Check columns
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'leader_positions'
-- ORDER BY ordinal_position;

-- Check indexes
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename = 'leader_positions';

-- Check unique constraint
-- SELECT conname, contype, conkey
-- FROM pg_constraint
-- WHERE conrelid = 'leader_positions'::regclass
-- AND conname = 'unique_leader_market_outcome';
