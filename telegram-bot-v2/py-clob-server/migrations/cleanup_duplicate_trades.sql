-- Clean up duplicate trades in smart_wallet_trades_to_share
-- Run this ONCE after deploying the fix

-- Step 1: Identify duplicates (trades with same base ID but different suffixes)
WITH duplicates AS (
    SELECT 
        trade_id,
        market_question,
        value,
        timestamp,
        -- Extract base ID (remove _XXX suffix)
        CASE 
            WHEN trade_id ~ '_[0-9]+$' THEN REGEXP_REPLACE(trade_id, '_[0-9]+$', '')
            ELSE trade_id
        END as base_id,
        -- Keep oldest trade (first one we saw)
        ROW_NUMBER() OVER (
            PARTITION BY CASE 
                WHEN trade_id ~ '_[0-9]+$' THEN REGEXP_REPLACE(trade_id, '_[0-9]+$', '')
                ELSE trade_id
            END 
            ORDER BY timestamp ASC
        ) as rn
    FROM smart_wallet_trades_to_share
)
SELECT 
    'DUPLICATES FOUND' as status,
    base_id,
    COUNT(*) as duplicate_count,
    ARRAY_AGG(trade_id ORDER BY timestamp) as all_trade_ids
FROM duplicates
GROUP BY base_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC;

-- Step 2: Delete duplicates, keeping only the first occurrence
-- UNCOMMENT BELOW TO EXECUTE DELETE:
/*
WITH duplicates AS (
    SELECT 
        trade_id,
        CASE 
            WHEN trade_id ~ '_[0-9]+$' THEN REGEXP_REPLACE(trade_id, '_[0-9]+$', '')
            ELSE trade_id
        END as base_id,
        ROW_NUMBER() OVER (
            PARTITION BY CASE 
                WHEN trade_id ~ '_[0-9]+$' THEN REGEXP_REPLACE(trade_id, '_[0-9]+$', '')
                ELSE trade_id
            END 
            ORDER BY timestamp ASC
        ) as rn
    FROM smart_wallet_trades_to_share
)
DELETE FROM smart_wallet_trades_to_share
WHERE trade_id IN (
    SELECT trade_id 
    FROM duplicates 
    WHERE rn > 1
);
*/

-- Step 3: Verify no duplicates remain
SELECT 
    CASE 
        WHEN trade_id ~ '_[0-9]+$' THEN REGEXP_REPLACE(trade_id, '_[0-9]+$', '')
        ELSE trade_id
    END as base_id,
    COUNT(*) as count,
    ARRAY_AGG(trade_id) as trade_ids
FROM smart_wallet_trades_to_share
GROUP BY base_id
HAVING COUNT(*) > 1;
-- Should return 0 rows after cleanup

