# Solana Keys Encryption Fix Migration

## Overview

This migration fixes a critical issue: **users with Solana wallets but empty/missing private keys**.

**Problem**:
- Previous users have a `solana_address` but `solana_private_key` column is NULL/empty
- When `/wallet` command calls `user.solana_private_key`, it returns `None`
- Encryption system detects empty key and logs: `❌ [DECRYPTION_FAILED] reason=empty_private_key`

**Solution**:
This migration:
1. Finds all users with Solana address but empty private key
2. Generates NEW Solana keypairs for them
3. Encrypts all Solana keys (new + existing)
4. Verifies all keys are properly encrypted

---

## When to Run

### ⏱️ Timing
- **After**: `2025-10-17_encrypt_private_keys/run_migration.py` (Polygon + API keys)
- **Before**: Users try to view Solana private keys

### 📊 Impact
- No downtime required
- Users won't lose existing SOL (only private key is new)
- Existing Solana addresses are preserved
- All keys encrypted at rest

---

## How to Run

### Prerequisites
```bash
# Ensure ENCRYPTION_KEY is set
echo $ENCRYPTION_KEY  # Should output base64 string (45+ chars)

# Ensure you're in the py-clob-server directory
cd "telegram bot v2/py-clob-server"
```

### Execute Migration
```bash
python migrations/2025-10-17_encrypt_solana_keys/fix_missing_solana_keys.py
```

### Expected Output
```
================================================================================
🔐 MIGRATION: Fix Missing & Encrypt Solana Private Keys
================================================================================

[Step 1/4] Validating encryption key...
✅ Encryption key validated

[Step 2/4] Generating missing Solana private keys...
🔍 Found 5 users with Solana address but MISSING private key
📝 Generating and encrypting 5 missing Solana private keys...
  ✓ Generated new Solana key for user 123456 (address: GdQ2j7...)
  ✓ Generated new Solana key for user 234567 (address: xP8kL9...)
✅ Successfully generated keys for 5 users

[Step 3/4] Encrypting plaintext Solana keys...
📝 Checking for plaintext Solana keys to encrypt...
✅ No Solana keys found to encrypt

[Step 4/4] Verifying all keys are encrypted...
🔍 Verifying all Solana keys are encrypted...
✅ All 5 users have properly encrypted Solana keys!

================================================================================
✅ MIGRATION COMPLETE: All Solana keys are now encrypted!
================================================================================
```

---

## Troubleshooting

### Error: "ENCRYPTION_KEY not set"
```bash
# Check if key exists
echo $ENCRYPTION_KEY

# If empty, get it from Railway
railway variables  --service py-clob-server

# Set locally for testing
export ENCRYPTION_KEY="your-base64-key-here"
```

### Error: "Failed to generate Solana keypair"
- Check if `solders` and `base58` are installed
- Run: `pip install solders>=0.18.0 base58>=2.1.0`

### Error: "Database connection failed"
- Ensure `DATABASE_URL` is set
- For local testing: `postgresql://localhost:5432/trading_bot`

---

## What Changed in the Database

### Before Migration
```sql
SELECT telegram_user_id, solana_address, solana_private_key
FROM users
LIMIT 5;

-- Results:
-- user_id | solana_address | solana_private_key
-- 123456  | GdQ2j7fQM...   | NULL
-- 234567  | xP8kL9vB...    | NULL
-- 345678  | mR4tY2nL...    | NULL
```

### After Migration
```sql
SELECT telegram_user_id, solana_address, LENGTH(solana_private_key) as key_length
FROM users
LIMIT 5;

-- Results:
-- user_id | solana_address | key_length
-- 123456  | GdQ2j7fQM...   | 108  ← Encrypted (Base64)
-- 234567  | xP8kL9vB...    | 112  ← Encrypted (Base64)
-- 345678  | mR4tY2nL...    | 110  ← Encrypted (Base64)
```

---

## Verification After Migration

### 1. Check Logs
```bash
# Filter for migration logs
railway logs --filter "MIGRATION: Fix Missing" --log-type deploy

# Should see: "✅ MIGRATION COMPLETE"
```

### 2. Test /wallet Command
```bash
# In Telegram bot
/wallet

# Click: 🔑 Solana Private Key
# Should see: "🔑 Your Solana Private Key: ..." (then auto-delete in 30s)
# Logs should show: ✅ [MESSAGE_SENT] | ✅ [MESSAGE_DELETED]
```

### 3. Database Verification
```sql
-- Check that ALL users with Solana address have encrypted keys
SELECT
    COUNT(*) as total_users,
    COUNT(CASE WHEN solana_private_key IS NOT NULL THEN 1 END) as users_with_key,
    COUNT(CASE WHEN solana_private_key IS NULL THEN 1 END) as users_missing_key
FROM users
WHERE solana_address IS NOT NULL;

-- Expected: total_users = users_with_key, users_missing_key = 0
```

---

## Emergency Procedures

### If Migration Fails
1. **Stop the bot**
2. **Check logs** for specific error
3. **Fix the issue** (ENCRYPTION_KEY, dependencies, etc.)
4. **Run migration again** (idempotent - safe to re-run)

### If You Need to Rollback
```bash
# This migration doesn't have a rollback (data-only, not destructive)
# If needed, restore from database backup

# Alternative: Generate new keys for failed users
python migrations/2025-10-17_encrypt_solana_keys/fix_missing_solana_keys.py
```

---

## Related Migrations

### Previous
- `2025-10-17_encrypt_private_keys/run_migration.py` - Encrypt Polygon + API keys

### Next
- (None planned)

---

## Questions?

See `ENCRYPTION_SETUP.md` for complete encryption documentation.

**Questions about logs?** See `ENCRYPTION_MONITORING.md`.
