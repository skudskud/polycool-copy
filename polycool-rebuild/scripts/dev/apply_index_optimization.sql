-- Script to apply index optimization migration
-- Run this in Supabase SQL Editor or via CLI

-- First, verify current state
SELECT 'Current indexes on markets:' as info;
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'markets'
ORDER BY indexname;

SELECT 'Current indexes on copy_trading_allocations:' as info;
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'copy_trading_allocations'
ORDER BY indexname;

-- Apply the optimization
\i migrations/optimize_indexes.sql

-- Verify changes
SELECT 'After optimization - markets indexes:' as info;
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'markets'
ORDER BY indexname;

SELECT 'After optimization - copy_trading_allocations indexes:' as info;
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'copy_trading_allocations'
ORDER BY indexname;

-- Performance impact check
SELECT 'Index usage statistics:' as info;
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC
LIMIT 20;
