# Migration: Restore Correct Private Keys from Backup

**Date**: 2025-10-17  
**Status**: Critical Fix

## Problem

The previous `fix_missing_solana_keys` migration had a critical flaw:

1. It GENERATED new random keypairs for users who had addresses but no keys
2. These new keys don't match the stored wallet addresses
3. When ClobClient tries to use these mismatched keys, it generates a different address than what's stored
4. Trading fails because the funds are on the original address, not the new mismatched one

Example:
```
Stored Address:    0xE235db7fcbc64161028eFbc0E131852188d8f11D
Generated Key Derives To: 0x5e1Ab23a3035AEB86692cA28B71F56f8843a33D5  ❌ MISMATCH
```

## Root Cause

The original encryption migration created backup columns with the correct plaintext keys. The "fix missing keys" migration should have checked these backups first instead of generating new keys.

## Solution

This migration:

1. **Finds** all users with plaintext backup keys
2. **Validates** that backup key matches the stored address
3. **Encrypts** the correct key using AES-256-GCM
4. **Updates** `polygon_private_key` (encrypted) column with the correct encrypted key

## Results

- ✅ 5 Polygon keys restored
- ⚠️ 0 Solana keys (Solana key restoration needs fixing for `Keypair.from_secret_key`)

## Verification

After running this migration, for each user:
```python
user = User.query.get(user_id)
client = ClobClient(key=user.polygon_private_key, ...)
assert client.get_address() == user.polygon_address  # Should be True
```

## Running the Migration

```bash
cd "telegram bot v2/py-clob-server"
python migrations/2025-10-17_restore_correct_keys/run_migration.py
```

## Impact

- Users can now trade from the correct addresses with all approvals/funding intact
- Trading will work because private key derives to the correct address
- This is a **CRITICAL** fix for the encryption rollout
