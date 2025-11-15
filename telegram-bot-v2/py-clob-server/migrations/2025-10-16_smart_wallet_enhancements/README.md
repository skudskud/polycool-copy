# Smart Wallet Enhancements Migration

## Date: 2025-10-16

## Purpose
Fix critical issues with smart wallet trading system:
1. Add `market_numeric_id` column to store numeric market ID alongside `conditionId`
2. Enable efficient market lookups for smart wallet trades
3. Fix "Market not found" errors when clicking smart trade buttons

## Problem
- Smart wallet trades store `market_id` as `conditionId` (format: `0xb4104961...`, 66 chars)
- Market service `get_market_by_id()` searches by numeric `id` (format: `553813`)
- Result: All market lookups fail, buttons don't work

## Solution
- Add `market_numeric_id` column to `smart_wallet_trades` table
- Populate it by joining with `markets.condition_id`
- Use numeric ID for all lookups and callbacks

## Files
- `add_market_numeric_id.sql` - SQL migration
- `run_migration.py` - Python script to execute migration

## Execution
```bash
cd "telegram bot v2/py-clob-server"
python migrations/2025-10-16_smart_wallet_enhancements/run_migration.py
```

## Verification
```sql
SELECT
    COUNT(*) as total_trades,
    COUNT(market_numeric_id) as trades_with_numeric_id,
    COUNT(*) - COUNT(market_numeric_id) as trades_without_numeric_id
FROM smart_wallet_trades;
```

Expected: All trades should have `market_numeric_id` populated.
