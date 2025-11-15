-- Create leaderboard_entries table for current rankings
-- Stores weekly and all-time leaderboard data
CREATE TABLE IF NOT EXISTS leaderboard_entries (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    
    -- Period: 'weekly' or 'all-time'
    period VARCHAR(20) NOT NULL,
    
    -- Ranking information
    rank INTEGER NOT NULL,
    
    -- P&L calculations
    pnl_amount NUMERIC(20, 2) NOT NULL,           -- Profit/Loss in USD (sells - buys)
    pnl_percentage NUMERIC(10, 4) NOT NULL,       -- Profit/Loss percentage
    
    -- Volume information
    total_volume_traded NUMERIC(20, 2) NOT NULL,  -- Total volume (sum of all buys + sells)
    total_buy_volume NUMERIC(20, 2) NOT NULL,     -- Sum of all buy transactions
    total_sell_volume NUMERIC(20, 2) NOT NULL,    -- Sum of all sell transactions
    
    -- Trade statistics
    total_trades INTEGER NOT NULL,                 -- Total number of trades
    winning_trades INTEGER DEFAULT 0,              -- Number of profitable trades
    losing_trades INTEGER DEFAULT 0,               -- Number of losing trades
    win_rate NUMERIC(5, 2) DEFAULT 0,              -- Win rate percentage
    
    -- Weekly metadata
    week_start_date TIMESTAMP,                     -- Start of the week (for weekly period)
    week_end_date TIMESTAMP,                       -- End of the week (for weekly period)
    
    -- Cached user data for quick display
    username VARCHAR(100),                         -- Cached username
    telegram_user_id BIGINT,                       -- Cached telegram_user_id for reference
    
    -- Timestamps
    calculated_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_user_leaderboard FOREIGN KEY (user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    CONSTRAINT unique_user_period UNIQUE (user_id, period, week_start_date)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_leaderboard_entries_period ON leaderboard_entries(period);
CREATE INDEX IF NOT EXISTS idx_leaderboard_entries_rank ON leaderboard_entries(period, rank);
CREATE INDEX IF NOT EXISTS idx_leaderboard_entries_user ON leaderboard_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_leaderboard_entries_week ON leaderboard_entries(week_start_date, period);
CREATE INDEX IF NOT EXISTS idx_leaderboard_entries_calculated ON leaderboard_entries(calculated_at);
CREATE INDEX IF NOT EXISTS idx_leaderboard_entries_pnl ON leaderboard_entries(pnl_percentage DESC);

-- Create leaderboard_history table to maintain historical records
-- Archives past leaderboards for trend analysis
CREATE TABLE IF NOT EXISTS leaderboard_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    
    -- Period information
    period VARCHAR(20) NOT NULL,
    week_number INTEGER NOT NULL,
    week_year INTEGER NOT NULL,
    week_start_date TIMESTAMP NOT NULL,
    week_end_date TIMESTAMP NOT NULL,
    
    -- Ranking snapshot
    rank INTEGER NOT NULL,
    rank_change INTEGER,                           -- Change from previous week (positive = improvement)
    
    -- P&L snapshot
    pnl_amount NUMERIC(20, 2) NOT NULL,
    pnl_percentage NUMERIC(10, 4) NOT NULL,
    pnl_change NUMERIC(10, 4),                     -- Change from previous week
    
    -- Volume snapshot
    total_volume_traded NUMERIC(20, 2) NOT NULL,
    total_buy_volume NUMERIC(20, 2) NOT NULL,
    total_sell_volume NUMERIC(20, 2) NOT NULL,
    
    -- Trade statistics snapshot
    total_trades INTEGER NOT NULL,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(5, 2) DEFAULT 0,
    
    -- Cached user data
    username VARCHAR(100),
    telegram_user_id BIGINT,
    
    -- Timestamps
    recorded_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_user_history FOREIGN KEY (user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE
);

-- Create indexes for history queries
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_user ON leaderboard_history(user_id);
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_week ON leaderboard_history(week_start_date, period);
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_rank ON leaderboard_history(week_start_date, rank);
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_recorded ON leaderboard_history(recorded_at);

-- Create user_stats table for performance optimization
-- Caches calculated stats to avoid recalculation on every query
CREATE TABLE IF NOT EXISTS user_stats (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    
    -- Aggregate statistics (all-time)
    total_buy_volume NUMERIC(20, 2) DEFAULT 0,
    total_sell_volume NUMERIC(20, 2) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    
    -- Weekly statistics (last 7 days)
    weekly_buy_volume NUMERIC(20, 2) DEFAULT 0,
    weekly_sell_volume NUMERIC(20, 2) DEFAULT 0,
    weekly_trades INTEGER DEFAULT 0,
    
    -- P&L tracking
    total_pnl NUMERIC(20, 2) DEFAULT 0,
    weekly_pnl NUMERIC(20, 2) DEFAULT 0,
    
    -- Last calculation time
    last_calculated TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_user_stats FOREIGN KEY (user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE
);

-- Create indexes for user_stats
CREATE INDEX IF NOT EXISTS idx_user_stats_user ON user_stats(user_id);
CREATE INDEX IF NOT EXISTS idx_user_stats_updated ON user_stats(updated_at);

-- Add comments for documentation
COMMENT ON TABLE leaderboard_entries IS 'Current leaderboard rankings for weekly and all-time periods';
COMMENT ON TABLE leaderboard_history IS 'Historical leaderboard records for trend analysis';
COMMENT ON TABLE user_stats IS 'Cached user statistics for performance optimization';

COMMENT ON COLUMN leaderboard_entries.period IS 'Period type: "weekly" or "all-time"';
COMMENT ON COLUMN leaderboard_entries.pnl_amount IS 'Profit/Loss calculated as: sum(SELL amounts) - sum(BUY amounts)';
COMMENT ON COLUMN leaderboard_entries.pnl_percentage IS 'Profit/Loss percentage: (pnl_amount / sum(BUY amounts)) * 100';
COMMENT ON COLUMN leaderboard_entries.total_volume_traded IS 'Total trading volume: sum(BUY amounts) + sum(SELL amounts)';

\echo '✅ Leaderboard tables created successfully'
