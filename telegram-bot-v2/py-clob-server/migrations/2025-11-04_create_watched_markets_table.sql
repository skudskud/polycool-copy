-- Create WatchedMarkets table for streamer subscription management
-- This table tracks markets that users have active positions in, so the streamer knows which markets to monitor

CREATE TABLE IF NOT EXISTS public.watched_markets (
    market_id TEXT PRIMARY KEY,
    condition_id TEXT,
    title TEXT,
    added_at TIMESTAMPTZ DEFAULT now(),
    last_position_at TIMESTAMPTZ DEFAULT now(),
    active_positions INTEGER DEFAULT 0,
    total_volume NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_watched_markets_condition_id ON public.watched_markets(condition_id);
CREATE INDEX IF NOT EXISTS idx_watched_markets_active_positions ON public.watched_markets(active_positions DESC);

-- Comments
COMMENT ON TABLE public.watched_markets IS 'Markets being watched by streamer due to user positions (beyond top 1000)';
COMMENT ON COLUMN public.watched_markets.market_id IS 'Short market ID (e.g., 516947)';
COMMENT ON COLUMN public.watched_markets.condition_id IS 'Full condition ID (0x... format)';
COMMENT ON COLUMN public.watched_markets.active_positions IS 'Number of active positions in this market';
COMMENT ON COLUMN public.watched_markets.last_position_at IS 'Last time a position was added in this market';
