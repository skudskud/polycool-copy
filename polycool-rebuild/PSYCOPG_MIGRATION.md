# Migration from asyncpg to psycopg

## Overview

Migrated database driver from `asyncpg` to `psycopg` (version 3) for better compatibility with PgBouncer transaction pooling.

## Why psycopg?

1. **Better PgBouncer Compatibility**: `psycopg` doesn't use prepared statements as aggressively as `asyncpg`, making it naturally compatible with PgBouncer transaction pooling
2. **No Special Configuration Needed**: Unlike `asyncpg`, `psycopg` doesn't require `statement_cache_size=0` to work with PgBouncer
3. **Proven Solution**: `psycopg` is the recommended driver for PgBouncer environments

## Changes Made

### 1. URL Scheme (`infrastructure/config/settings.py`)
- Changed from: `postgresql+asyncpg://`
- Changed to: `postgresql+psycopg://`
- SQLAlchemy automatically uses async version when using `create_async_engine()`

### 2. Connection Configuration (`core/database/connection.py`)
- Removed `statement_cache_size=0` (not needed with psycopg)
- Changed SSL parameter from `ssl="require"` to `sslmode="require"` (psycopg syntax)
- Simplified connection args (no prepared statement disabling needed)

### 3. Dependencies
- ✅ `psycopg[binary]>=3.1.0` already in `requirements.txt`
- ✅ `psycopg==3.1.18` already in `pyproject.toml`
- No new dependencies needed

## Benefits

1. **Eliminates Prepared Statement Errors**: No more `prepared statement "__asyncpg_stmt_xx__" already exists` errors
2. **Simpler Configuration**: No need to disable prepared statements
3. **Better Compatibility**: Works seamlessly with PgBouncer transaction pooling
4. **Same Performance**: `psycopg` async performance is comparable to `asyncpg`

## Testing

After deployment, verify:
- [ ] No prepared statement errors in logs
- [ ] Database connections work correctly
- [ ] API endpoints respond successfully
- [ ] Workers can upsert markets without errors
- [ ] Copy trading webhooks process correctly

## Rollback Plan

If issues occur, revert to asyncpg by:
1. Change URL scheme back to `postgresql+asyncpg://`
2. Add `statement_cache_size=0` back to `connect_args`
3. Change SSL parameter back to `ssl="require"`

## References

- [psycopg 3 Documentation](https://www.psycopg.org/psycopg3/)
- [SQLAlchemy psycopg Dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql/psycopg.html)
- [PgBouncer Compatibility](https://www.pgbouncer.org/features.html)
