-- Copy Trading System - Database Migration
-- Date: 2025-10-20
-- Creates 4 tables: subscriptions, budgets, history, stats

-- TABLE 1: copy_trading_subscriptions
CREATE TABLE IF NOT EXISTS copy_trading_subscriptions (
    id SERIAL PRIMARY KEY,
    follower_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    leader_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    copy_mode VARCHAR(20) NOT NULL DEFAULT 'PROPORTIONAL',
    fixed_amount NUMERIC(20, 2) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_follower_one_leader UNIQUE(follower_id),
    CONSTRAINT follower_not_leader CHECK (follower_id != leader_id),
    CONSTRAINT fixed_amount_positive CHECK (fixed_amount IS NULL OR fixed_amount > 0)
);

CREATE INDEX idx_copy_sub_follower ON copy_trading_subscriptions(follower_id);
CREATE INDEX idx_copy_sub_leader ON copy_trading_subscriptions(leader_id);
CREATE INDEX idx_copy_sub_status ON copy_trading_subscriptions(status);
CREATE INDEX idx_copy_sub_follower_status ON copy_trading_subscriptions(follower_id, status);
CREATE INDEX idx_copy_sub_leader_status ON copy_trading_subscriptions(leader_id, status);

-- TABLE 2: copy_trading_budgets
CREATE TABLE IF NOT EXISTS copy_trading_budgets (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    allocation_percentage NUMERIC(5, 2) NOT NULL DEFAULT 50.00,
    total_wallet_balance NUMERIC(20, 2) NOT NULL DEFAULT 0,
    allocated_budget NUMERIC(20, 2) NOT NULL DEFAULT 0,
    budget_used NUMERIC(20, 2) NOT NULL DEFAULT 0,
    budget_remaining NUMERIC(20, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_wallet_sync TIMESTAMP NULL,
    CONSTRAINT allocation_pct_range CHECK (allocation_percentage >= 5.00 AND allocation_percentage <= 100.00),
    CONSTRAINT budget_amounts_positive CHECK (allocated_budget >= 0 AND budget_used >= 0),
    CONSTRAINT budget_remaining_consistent CHECK (budget_remaining = allocated_budget - budget_used)
);

CREATE INDEX idx_copy_budget_user ON copy_trading_budgets(user_id);
CREATE INDEX idx_copy_budget_created ON copy_trading_budgets(created_at);

-- TABLE 3: copy_trading_history
CREATE TABLE IF NOT EXISTS copy_trading_history (
    id SERIAL PRIMARY KEY,
    follower_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    leader_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    leader_transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    follower_transaction_id INTEGER UNIQUE REFERENCES transactions(id) ON DELETE SET NULL,
    market_id VARCHAR(100) NOT NULL,
    outcome VARCHAR(10) NOT NULL,
    transaction_type VARCHAR(10) NOT NULL,
    copy_mode VARCHAR(20) NOT NULL,
    leader_trade_amount NUMERIC(20, 2) NOT NULL,
    leader_wallet_balance NUMERIC(20, 2) NOT NULL,
    calculated_copy_amount NUMERIC(20, 2) NOT NULL,
    actual_copy_amount NUMERIC(20, 2) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    failure_reason VARCHAR(255) NULL,
    fee_from_copy NUMERIC(20, 2) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP NULL,
    CONSTRAINT copy_amount_positive CHECK (calculated_copy_amount > 0),
    CONSTRAINT actual_amount_positive CHECK (actual_copy_amount IS NULL OR actual_copy_amount > 0)
);

CREATE INDEX idx_copy_hist_follower ON copy_trading_history(follower_id);
CREATE INDEX idx_copy_hist_leader ON copy_trading_history(leader_id);
CREATE INDEX idx_copy_hist_status ON copy_trading_history(status);
CREATE INDEX idx_copy_hist_created ON copy_trading_history(created_at);
CREATE INDEX idx_copy_hist_market ON copy_trading_history(market_id);
CREATE INDEX idx_copy_hist_follower_status ON copy_trading_history(follower_id, status);
CREATE INDEX idx_copy_hist_leader_success ON copy_trading_history(leader_id, status) WHERE status = 'SUCCESS';

-- TABLE 4: copy_trading_stats
CREATE TABLE IF NOT EXISTS copy_trading_stats (
    id SERIAL PRIMARY KEY,
    leader_id BIGINT NOT NULL UNIQUE REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    total_active_followers BIGINT NOT NULL DEFAULT 0,
    total_trades_copied BIGINT NOT NULL DEFAULT 0,
    total_volume_copied NUMERIC(20, 2) NOT NULL DEFAULT 0,
    total_fees_from_copies NUMERIC(20, 2) NOT NULL DEFAULT 0,
    total_pnl_followers NUMERIC(20, 2) NULL,
    avg_follower_pnl NUMERIC(20, 2) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_calculated TIMESTAMP NULL,
    CONSTRAINT stats_amounts_positive CHECK (
        total_active_followers >= 0 
        AND total_trades_copied >= 0 
        AND total_volume_copied >= 0 
        AND total_fees_from_copies >= 0
    )
);

CREATE INDEX idx_copy_stats_leader ON copy_trading_stats(leader_id);
CREATE INDEX idx_copy_stats_fees ON copy_trading_stats(total_fees_from_copies DESC);
CREATE INDEX idx_copy_stats_followers ON copy_trading_stats(total_active_followers DESC);

-- ADDITIONAL INDEXES FOR JOIN QUERIES
CREATE INDEX idx_copy_hist_follower_leader_success ON copy_trading_history(follower_id, leader_id, status);
CREATE INDEX idx_copy_hist_executed_at ON copy_trading_history(executed_at) WHERE executed_at IS NOT NULL;

-- COMMENTS FOR DOCUMENTATION
COMMENT ON TABLE copy_trading_subscriptions IS 'Tracks copy trading relationships: who follows whom and their configuration';
COMMENT ON TABLE copy_trading_budgets IS 'Per-user budget allocation for copy trading (default 50% of wallet)';
COMMENT ON TABLE copy_trading_history IS 'Audit trail of all copied trades for tracking and reconciliation';
COMMENT ON TABLE copy_trading_stats IS 'Aggregated stats for leaders to track rewards and performance';
