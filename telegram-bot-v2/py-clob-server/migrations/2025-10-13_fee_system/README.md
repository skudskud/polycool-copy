# Fee System Migration

## Overview

This migration implements a 1% trading fee system with a 3-tier referral commission structure (25%/5%/3%).

## Tables Created

1. **`referrals`** - Tracks referral relationships (3 levels deep)
2. **`fees`** - Logs all fee collections with transaction hashes
3. **`referral_commissions`** - Individual commission records for each referrer

## Migration Order

**IMPORTANT:** Execute the SQL files in the following order:

1. `001_create_referrals_table.sql`
2. `002_create_fees_table.sql`
3. `003_create_referral_commissions_table.sql`

## Execution Methods

### Method 1: Railway CLI (Recommended)

```bash
# Navigate to migration directory
cd "telegram bot v2/py-clob-server/migrations/2025-10-13_fee_system"

# Link to your Railway project (if not already linked)
railway link

# Execute each migration in order
railway run psql < 001_create_referrals_table.sql
railway run psql < 002_create_fees_table.sql
railway run psql < 003_create_referral_commissions_table.sql
```

### Method 2: Direct psql

```bash
# Get DATABASE_URL from Railway dashboard
export DATABASE_URL="postgresql://..."

# Execute migrations
psql $DATABASE_URL -f 001_create_referrals_table.sql
psql $DATABASE_URL -f 002_create_fees_table.sql
psql $DATABASE_URL -f 003_create_referral_commissions_table.sql
```

### Method 3: Railway Dashboard

1. Go to Railway dashboard
2. Open your project
3. Navigate to PostgreSQL database
4. Open Query tab
5. Copy/paste content of each SQL file in order
6. Execute

## Verification

After running migrations, verify tables were created:

```sql
-- Check if tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('referrals', 'fees', 'referral_commissions');

-- Check table structures
\d referrals
\d fees
\d referral_commissions

-- Verify indexes
SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('referrals', 'fees', 'referral_commissions');
```

Expected output: 3 tables with multiple indexes each.

## Rollback (If Needed)

To rollback the migration:

```sql
-- Drop tables in reverse order (due to foreign key constraints)
DROP TABLE IF EXISTS referral_commissions CASCADE;
DROP TABLE IF EXISTS fees CASCADE;
DROP TABLE IF EXISTS referrals CASCADE;
```

## Schema Details

### Referrals Table
- Stores referral relationships between users
- Each user can only be referred once (UNIQUE constraint)
- Supports 3 levels of referrals

### Fees Table
- Logs every fee collection attempt
- Tracks fee amount, percentage, and minimum application
- Links to transactions table
- Stores blockchain transaction hashes
- Status tracking: pending/collected/failed

### Referral Commissions Table
- Individual commission records per referrer
- Linked to fees table
- Payment tracking with transaction hashes
- Status: pending/paid/failed

## Testing After Migration

```sql
-- Test inserting a referral (will need real user_ids)
-- INSERT INTO referrals (referrer_user_id, referred_user_id, level)
-- VALUES (123456789, 987654321, 1);

-- Check fees table structure
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'fees'
ORDER BY ordinal_position;

-- Verify foreign key constraints
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name IN ('referrals', 'fees', 'referral_commissions');
```

## Next Steps

After successful migration:

1. Deploy updated code to Railway
2. Monitor logs for fee collection attempts
3. Test with small trades ($1-$5)
4. Verify transactions on PolygonScan
5. Check database records in fees table

## Support

If migration fails:
- Check DATABASE_URL is correct
- Verify you have write permissions
- Check for existing tables with same names
- Review error messages carefully

## Notes

- All fee amounts are stored in USDC (6 decimals)
- Treasury wallet: `0xaEF1Da195Dd057c9252A6C03081B70f38453038c`
- Fee collection happens in background (non-blocking)
- Minimum fee: $0.20
- Base fee: 1% of trade amount
