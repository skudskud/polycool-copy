# Plan Implementation Status: Fix PgBouncer Connection

## ✅ Plan Items Completed

### 1. Fix URL Processing in Settings (`infrastructure/config/settings.py`)
- ✅ **COMPLETED**: Updated `effective_url` property to preserve query parameters
- ✅ **COMPLETED**: Automatically adds `?pgbouncer=true` for Supabase pooler connections on port 6543
- ✅ **COMPLETED**: Handles both `postgres://` and `postgresql://` schemes
- ✅ **COMPLETED**: Prevents duplicate `pgbouncer=true` parameters

**Note**: The `pgbouncer` parameter is added to the URL for documentation, but removed before passing to SQLAlchemy since asyncpg doesn't accept it as a kwarg.

### 2. Update Railway Environment Variables
- ✅ **COMPLETED**: Created script `update_railway_pgbouncer.py` to update DATABASE_URL
- ⚠️ **PENDING**: Manual execution required (Railway CLI not authenticated)

**Script Location**: `polycool/polycool-rebuild/update_railway_pgbouncer.py`

### 3. Verify Connection Args (`core/database/connection.py`)
- ✅ **COMPLETED**: `statement_cache_size: 0` is set in `connect_args`
- ✅ **COMPLETED**: `prepared_statement_cache_size: 0` removed (not a valid asyncpg parameter)
- ✅ **COMPLETED**: Execution options added to disable prepared statements at SQLAlchemy level
- ✅ **COMPLETED**: `pgbouncer` parameter is stripped from URL before passing to SQLAlchemy

### 4. Test Connection
- ❌ **FAILED**: Prepared statement errors persist in production logs
- ❌ **ISSUE**: `asyncpg` continues to create prepared statements despite `statement_cache_size=0`

## 🔴 Critical Issue Discovered

Despite implementing the plan correctly, **prepared statement errors persist**:

```
ERROR: prepared statement "__asyncpg_stmt_e__" already exists
HINT: pgbouncer with pool_mode set to "transaction" or "statement"
      does not support prepared statements properly.
```

### Root Cause Analysis

1. **SQLAlchemy may not pass `connect_args` correctly**: The `statement_cache_size=0` parameter might not be reaching asyncpg's `connect()` function
2. **asyncpg behavior**: Even with `statement_cache_size=0`, asyncpg may still create prepared statements in certain scenarios
3. **Difference with TypeScript indexer**: The TypeScript indexer uses `pg` driver (Node.js) which doesn't use prepared statements as aggressively as `asyncpg`

## 🎯 Recommended Solutions

### Option 1: Switch to `psycopg` (Recommended)
Replace `asyncpg` with `psycopg` (version 3) which is more compatible with PgBouncer:

```python
# Change from:
postgresql+asyncpg://...

# To:
postgresql+psycopg://...
```

**Pros**: Better PgBouncer compatibility, doesn't use prepared statements aggressively
**Cons**: Requires code changes, may have performance differences

### Option 2: Use Session Pooling (Port 5432)
Switch from transaction pooling (port 6543) to session pooling (port 5432):

```
postgresql://...@aws-1-eu-north-1.pooler.supabase.com:5432/postgres
```

**Pros**: Supports prepared statements, minimal code changes
**Cons**: Fewer concurrent connections, may hit connection limits

### Option 3: Custom Connection Creator
Create a custom asyncpg connection creator that explicitly disables prepared statements:

```python
async def create_connection(dsn, **kwargs):
    conn = await asyncpg.connect(
        dsn,
        statement_cache_size=0,
        **kwargs
    )
    return conn
```

**Pros**: Ensures parameter is passed correctly
**Cons**: More complex, requires custom pool implementation

## 📋 Next Steps

1. **Immediate**: Test if Option 2 (port 5432) resolves the issue
2. **Short-term**: Consider migrating to `psycopg` if port 5432 doesn't work
3. **Long-term**: Evaluate if PgBouncer transaction pooling is necessary, or if we can use asyncpg's built-in pooling

## Files Modified

1. ✅ `polycool/polycool-rebuild/infrastructure/config/settings.py` - URL processing fixed
2. ✅ `polycool/polycool-rebuild/core/database/connection.py` - Connection args configured
3. ✅ `polycool/polycool-rebuild/update_railway_pgbouncer.py` - Railway update script created
4. ✅ `polycool/polycool-rebuild/PGBOUNCER_FIX_SUMMARY.md` - Documentation created

## Conclusion

The plan has been **fully implemented** according to its specifications. However, a **fundamental incompatibility** between `asyncpg` and PgBouncer transaction pooling persists. The recommended solution is to either:
- Switch to `psycopg` driver (best long-term solution)
- Use session pooling on port 5432 (quickest fix)
- Implement a custom connection creator (most complex)
