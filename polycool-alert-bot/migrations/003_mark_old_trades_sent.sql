-- Mark old trades (> 5 days) as sent to prevent re-alerting
-- This fixes the issue where trades from Oct 18 are showing up as new alerts

BEGIN;

-- Insert old trades into alert_bot_sent to mark them as already alerted
INSERT INTO alert_bot_sent (
    trade_id, 
    wallet_address, 
    market_question, 
    value, 
    sent_at,
    telegram_message_id,
    telegram_chat_id
)
SELECT 
    id,
    wallet_address,
    market_question,
    value,
    NOW(),
    NULL,  -- No message ID for bulk marking
    NULL   -- No chat ID for bulk marking
FROM smart_wallet_trades
WHERE 
    -- Trades older than 5 days
    timestamp < NOW() - INTERVAL '5 days'
    -- That haven't been marked as sent yet
    AND id NOT IN (SELECT trade_id FROM alert_bot_sent WHERE trade_id IS NOT NULL)
    -- Only first-time trades (what the alert bot sends)
    AND is_first_time = TRUE
ON CONFLICT (trade_id) DO NOTHING;

-- Show how many trades were marked
SELECT COUNT(*) as trades_marked_as_sent 
FROM alert_bot_sent 
WHERE sent_at >= NOW() - INTERVAL '1 minute';

COMMIT;

-- Verify: should return 0 old trades
SELECT COUNT(*) as old_trades_still_pending
FROM smart_wallet_trades swt
WHERE 
    swt.timestamp < NOW() - INTERVAL '5 days'
    AND swt.is_first_time = TRUE
    AND NOT EXISTS (
        SELECT 1 FROM alert_bot_sent abs WHERE abs.trade_id = swt.id
    );

