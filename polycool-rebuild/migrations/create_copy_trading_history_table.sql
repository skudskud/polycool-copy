-- =================================================
-- MIGRATION: Create Copy Trading History Table
-- Date: November 9, 2025
-- Description: Add audit trail for copied trades (adapted from old system)
-- Tracks execution success/failure and links leader/follower trades
-- =================================================

CREATE TABLE copy_trading_history (
    id SERIAL PRIMARY KEY,
    follower_id INTEGER NOT NULL REFERENCES users(id),
    leader_address_id INTEGER NOT NULL REFERENCES watched_addresses(id),

    -- Link to original leader trade (from indexer)
    leader_transaction_id VARCHAR(255),
    leader_trade_tx_hash VARCHAR(255),

    -- Trade details
    market_id VARCHAR(100) NOT NULL,
    outcome VARCHAR(10) NOT NULL,
    transaction_type VARCHAR(10) NOT NULL, -- 'BUY' or 'SELL'

    -- Copy mode and calculation
    copy_mode VARCHAR(20) NOT NULL, -- 'PROPORTIONAL' or 'FIXED'
    leader_trade_amount NUMERIC(20,2) NOT NULL,
    leader_wallet_balance NUMERIC(20,2),
    calculated_copy_amount NUMERIC(20,2) NOT NULL,
    actual_copy_amount NUMERIC(20,2),

    -- Follower wallet state at time of copy
    follower_wallet_balance NUMERIC(20,2),
    follower_allocated_budget NUMERIC(20,2),

    -- Execution status
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    failure_reason VARCHAR(255),

    -- Fee tracking (for leader rewards)
    fee_from_copy NUMERIC(20,2),

    -- Timestamps
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITHOUT TIME ZONE,

    -- Link to follower's executed trade (when successful)
    follower_transaction_id VARCHAR(255),
    follower_trade_tx_hash VARCHAR(255),

    -- Indexes for performance
    CONSTRAINT fk_copy_trading_history_follower FOREIGN KEY (follower_id) REFERENCES users(id),
    CONSTRAINT fk_copy_trading_history_leader FOREIGN KEY (leader_address_id) REFERENCES watched_addresses(id)
);

-- Indexes for efficient queries
CREATE INDEX idx_copy_history_follower_status ON copy_trading_history(follower_id, status);
CREATE INDEX idx_copy_history_leader_success ON copy_trading_history(leader_address_id, status);
CREATE INDEX idx_copy_history_market ON copy_trading_history(market_id);
CREATE INDEX idx_copy_history_created ON copy_trading_history(created_at);
CREATE INDEX idx_copy_history_executed ON copy_trading_history(executed_at) WHERE executed_at IS NOT NULL;

-- Comments explaining the table purpose
COMMENT ON TABLE copy_trading_history IS 'Audit trail of all copied trades with execution status';
COMMENT ON COLUMN copy_trading_history.leader_transaction_id IS 'Reference to leader transaction from indexer';
COMMENT ON COLUMN copy_trading_history.calculated_copy_amount IS 'Amount calculated by copy algorithm';
COMMENT ON COLUMN copy_trading_history.actual_copy_amount IS 'Amount actually executed (may differ due to minimums/budget)';
COMMENT ON COLUMN copy_trading_history.follower_allocated_budget IS 'Allocated budget at time of copy attempt';
COMMENT ON COLUMN copy_trading_history.status IS 'PENDING, SUCCESS, FAILED, INSUFFICIENT_BUDGET, CANCELLED';

-- =================================================
-- VERIFICATION QUERIES
-- =================================================

-- Check table was created
-- SELECT table_name FROM information_schema.tables
-- WHERE table_name = 'copy_trading_history';

-- Check columns
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'copy_trading_history'
-- ORDER BY ordinal_position;

-- Check indexes
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename = 'copy_trading_history';
