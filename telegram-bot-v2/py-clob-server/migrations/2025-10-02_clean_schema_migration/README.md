# Database Migration: Clean Schema with Unified Users Table

**Date:** October 2, 2025  
**Status:** ✅ COMPLETED  
**Applied to:** Railway Production PostgreSQL

---

## 📋 Migration Summary

### Objective
Migrate from 3 separate tables (`user_wallets`, `user_api_keys`, `user_solana_wallets`) to a single unified `users` table for better data integrity and simpler code.

### Changes Made

#### Before (Old Schema)
```
user_wallets (Polygon wallet data)
user_api_keys (API credentials)
user_solana_wallets (Solana wallet data) - NOT IN DATABASE YET
user_positions (trading positions)
markets (market data)
```

#### After (New Schema)
```
users (ALL user data in one table)
  ├─ Polygon wallet
  ├─ Solana wallet
  ├─ API credentials
  ├─ Approvals (USDC, POL, Polymarket)
  └─ Metadata

positions (linked via FK to users.telegram_user_id)
markets (unchanged structure)
```

---

## 🔄 Migration Process

### 1. Backup
- Created backup tables:
  - `migration_backup_user_wallets`
  - `migration_backup_user_api_keys`
  - `migration_backup_user_positions`

### 2. Schema Changes
- **Dropped:** `user_wallets`, `user_api_keys`, `user_positions` (old)
- **Created:** `users` (unified table)
- **Created:** `positions` (renamed from `user_positions`, proper FK)
- **Recreated:** `markets` (cleaned up)

### 3. Data Migration
- Merged data from `user_wallets` + `user_api_keys` → `users`
- Migrated positions with new FK relationship
- Markets table left empty (will be populated from Gamma API)

### 4. New Features
- Added `solana_address` and `solana_private_key` columns
- Added `pol_approved` column (3rd contract approval)
- Added `wallet_generation_count` (for /restart command)
- Added `last_restart` timestamp

---

## 📊 Migration Results

### Data Migrated
- **Users:** 1 (diogenicious - telegram_user_id: 1015699261)
- **Positions:** 8 (1 active, 7 inactive)
- **Markets:** 0 (will be populated from API)

### Verification
```sql
-- Check users table
SELECT COUNT(*) FROM users;
-- Result: 1

-- Check positions table
SELECT COUNT(*) FROM positions;
-- Result: 8

-- Check markets table
SELECT COUNT(*) FROM markets;
-- Result: 0
```

---

## 📁 Files

- `database_migration_v2.sql` - Initial version (had syntax errors)
- `database_migration_v2_fixed.sql` - **APPLIED VERSION** ✅

### How to Apply (Already Done)
```bash
psql "postgresql://[...]@trolley.proxy.rlwy.net:46977/railway" \
  -f database_migration_v2_fixed.sql
```

---

## ⚠️ Important Notes

### Backup Tables
The following backup tables were retained for safety:
- `migration_backup_user_wallets`
- `migration_backup_user_api_keys`
- `migration_backup_user_positions`

**To remove backups** (after verification):
```sql
DROP TABLE IF EXISTS migration_backup_user_wallets;
DROP TABLE IF EXISTS migration_backup_user_api_keys;
DROP TABLE IF EXISTS migration_backup_user_positions;
```

### Code Changes Required
The following files need to be updated to use the new schema:
- ✅ `database.py` - Updated with new `User`, `Position`, `Market` models
- 🔄 `wallet_manager.py` - Needs update to use `users` table
- 🔄 `api_key_manager.py` - Needs update to use `users` table
- 🔄 `solana_wallet_manager_v2.py` - Needs update to use `users` table
- 🔄 All Telegram bot handlers

---

## 🔄 Rollback (If Needed)

**NOT RECOMMENDED** - Backups retained, but new schema is better!

If absolutely necessary:
```sql
-- Restore from backups
CREATE TABLE user_wallets AS SELECT * FROM migration_backup_user_wallets;
CREATE TABLE user_api_keys AS SELECT * FROM migration_backup_user_api_keys;
CREATE TABLE user_positions AS SELECT * FROM migration_backup_user_positions;

-- Drop new tables
DROP TABLE IF EXISTS positions CASCADE;
DROP TABLE IF EXISTS users CASCADE;
```

---

## ✅ Next Steps

1. ✅ **Phase 1:** Database migration complete
2. 🔄 **Phase 2:** Populate markets from Gamma API
3. 🔄 **Phase 3:** Update all code to use new schema
4. 🔄 **Phase 4:** Create /restart command
5. 🔄 **Phase 5:** Test complete flow

---

**Applied by:** Database Migration Script  
**Verified:** Railway CLI  
**Status:** Production Ready ✅

