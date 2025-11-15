# Withdrawal Feature Migration

**Date:** 2025-10-08  
**Feature:** In-Bot Withdrawal System  
**Networks:** Solana (SOL) + Polygon (USDC.e)

---

## 📋 Overview

This migration adds the `withdrawals` table to support direct withdrawals from the Telegram bot without requiring users to export private keys.

### Features:
- ✅ Withdraw SOL from Solana wallet
- ✅ Withdraw USDC.e from Polygon wallet  
- ✅ Complete audit trail for compliance
- ✅ Rate limiting support (10/day, $1000/day)
- ✅ Transaction tracking with blockchain links

---

## 🗄️ Database Changes

### New Table: `withdrawals`

Stores all withdrawal transactions with complete metadata:

```sql
withdrawals (
  id SERIAL PRIMARY KEY,
  user_id BIGINT (FK → users),
  network VARCHAR(10),  -- 'SOL' or 'POLYGON'
  token VARCHAR(10),    -- 'SOL', 'USDC', 'USDC.e'
  amount NUMERIC(20, 8),
  gas_cost NUMERIC(20, 8),
  from_address TEXT,
  destination_address TEXT,
  tx_hash TEXT,
  status VARCHAR(20),   -- 'pending', 'confirmed', 'failed'
  created_at TIMESTAMP,
  submitted_at TIMESTAMP,
  confirmed_at TIMESTAMP,
  failed_at TIMESTAMP,
  error_message TEXT,
  retry_count INT,
  estimated_usd_value NUMERIC(10, 2)
)
```

### Indexes Created:

1. `idx_withdrawals_user_id` - User's withdrawal history
2. `idx_withdrawals_status` - Pending withdrawal monitoring
3. `idx_withdrawals_tx_hash` - Transaction lookup
4. `idx_withdrawals_recent` - Rate limiting queries (24h)
5. `idx_withdrawals_network` - Network-specific queries

---

## 🚀 How to Run Migration

### Method 1: Railway MCP (Recommended)

```bash
# From Cursor/IDE with Railway MCP
mcp_Railway_run-sql --sql-file migrations/2025-10-08_withdrawal_feature/create_withdrawals_table.sql
```

### Method 2: Railway CLI

```bash
cd "telegram bot v2/py-clob-server"
railway link
railway run psql < migrations/2025-10-08_withdrawal_feature/create_withdrawals_table.sql
```

### Method 3: Direct psql

```bash
# Get DATABASE_URL from Railway dashboard
export DATABASE_URL="postgresql://user:pass@host:port/db"
psql $DATABASE_URL -f migrations/2025-10-08_withdrawal_feature/create_withdrawals_table.sql
```

### Method 4: Python Script

```python
from database import engine, Base, Withdrawal

# Create table from model
Base.metadata.create_all(bind=engine, tables=[Withdrawal.__table__])
print("✅ withdrawals table created!")
```

---

## ✅ Verification

After running migration, verify success:

```sql
-- Check table exists
SELECT table_name 
FROM information_schema.tables 
WHERE table_name = 'withdrawals';

-- Check columns
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'withdrawals'
ORDER BY ordinal_position;

-- Check indexes
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'withdrawals';

-- Test insert (optional)
INSERT INTO withdrawals (user_id, network, token, amount, from_address, destination_address, status)
VALUES (12345, 'SOL', 'SOL', 1.0, 'test_from', 'test_to', 'pending');

SELECT * FROM withdrawals;
```

---

## 🔄 Rollback Plan

If issues occur, rollback with:

```sql
BEGIN;

-- Drop indexes
DROP INDEX IF EXISTS idx_withdrawals_user_id;
DROP INDEX IF EXISTS idx_withdrawals_status;
DROP INDEX IF EXISTS idx_withdrawals_tx_hash;
DROP INDEX IF EXISTS idx_withdrawals_recent;
DROP INDEX IF EXISTS idx_withdrawals_network;

-- Drop table
DROP TABLE IF EXISTS withdrawals;

COMMIT;
```

---

## 📊 Sample Queries

### User's withdrawal history
```sql
SELECT * FROM withdrawals
WHERE user_id = 12345
ORDER BY created_at DESC
LIMIT 10;
```

### Rate limit check (24h)
```sql
SELECT COUNT(*), SUM(estimated_usd_value)
FROM withdrawals
WHERE user_id = 12345
  AND created_at > NOW() - INTERVAL '24 hours'
  AND status IN ('pending', 'confirmed');
```

### Failed withdrawals (needs investigation)
```sql
SELECT id, user_id, network, amount, error_message
FROM withdrawals
WHERE status = 'failed'
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

### Daily statistics
```sql
SELECT 
  DATE(created_at) as date,
  network,
  COUNT(*) as withdrawals,
  SUM(amount) as total_amount,
  COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as successful
FROM withdrawals
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY DATE(created_at), network
ORDER BY date DESC;
```

---

## 🎯 Next Steps

1. ✅ Migration complete
2. Add `Withdrawal` model to `database.py`
3. Create `withdrawal_service.py` for TX execution
4. Create `withdrawal_handlers.py` for UI
5. Update `/wallet` command with new buttons
6. Test on testnet (Devnet + Mumbai)
7. Deploy to production

---

## 📝 Notes

- **Cascading delete:** If user is deleted, their withdrawal records are also deleted
- **Rate limiting:** Query `idx_withdrawals_recent` index for fast 24h checks
- **Audit trail:** All withdrawals logged permanently (never delete)
- **Transaction tracking:** Store `tx_hash` for blockchain verification
- **Error tracking:** Store `error_message` for debugging failed withdrawals

---

## 🔗 Related Files

- `database.py` - Withdrawal model definition
- `telegram_bot/services/withdrawal_service.py` - Withdrawal execution
- `telegram_bot/handlers/withdrawal_handlers.py` - User interface
- `telegram_bot/handlers/setup_handlers.py` - /wallet integration

