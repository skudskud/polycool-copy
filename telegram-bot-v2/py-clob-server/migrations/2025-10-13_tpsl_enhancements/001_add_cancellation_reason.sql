-- Migration: Add cancellation reason tracking to TP/SL orders
-- Date: 2025-10-13
-- Purpose: Track why TP/SL orders were cancelled for better UX and debugging

-- Add cancellation reason column
ALTER TABLE tpsl_orders 
ADD COLUMN IF NOT EXISTS cancelled_reason VARCHAR(50);

-- Add comment for documentation
COMMENT ON COLUMN tpsl_orders.cancelled_reason IS 
'Reason for cancellation:
- user_cancelled: User manually cancelled
- market_closed: Market stopped trading
- market_resolved: Market outcome decided
- position_closed: User sold all tokens manually
- position_increased: User bought more, TP/SL auto-updated (old order replaced)
- insufficient_tokens: TP/SL trigger but not enough tokens to execute
- both_null: User cancelled both TP and SL individually';

-- Create index for analytics queries (only on cancelled orders)
CREATE INDEX IF NOT EXISTS idx_tpsl_cancelled_reason 
ON tpsl_orders(cancelled_reason) 
WHERE status = 'cancelled';

-- Verify the column was added
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name='tpsl_orders' 
        AND column_name='cancelled_reason'
    ) THEN
        RAISE NOTICE '✅ Migration successful: cancelled_reason column added';
    ELSE
        RAISE EXCEPTION '❌ Migration failed: cancelled_reason column not found';
    END IF;
END $$;

