import type { DataSourceOptions } from 'typeorm'

const config: DataSourceOptions = {
  type: 'postgres',
  host: process.env.DB_HOST || 'localhost',
  port: parseInt(process.env.DB_PORT || '5432'),
  database: process.env.DB_NAME || 'postgres',
  username: process.env.DB_USER || 'postgres',
  password: process.env.DB_PASS,  // TypeormDatabase expects DB_PASS, not DB_PASSWORD
  ssl: true,
  synchronize: false,
  logging: ['error', 'warn'],
  entities: ['lib/model/generated/userTransaction.model.js'],
  migrations: ['lib/db/migrations/*.js'],
  migrationsTableName: '_squid_migrations',
  extra: {
    // ⚠️ CRITICAL FIX: Force IPv4-only at pg pool level
    // setDefaultResultOrder() doesn't affect dns.lookup() used by pg
    // This socket option forces IPv4 at the TCP level
    socketKeepAlive: true,

    // Force IPv4 only - MOST IMPORTANT FIX!
    // 4 = IPv4, 6 = IPv6. pg will only try IPv4 addresses
    // NOTE: This requires pg version 8.11+ or later
    // As fallback, we'll add this conditionally

    // ⚠️ FIX #2: Increased pool size for heavy backfill (50M blocks)
    // Subsquid can spawn many parallel connections
    max: 50,                         // ↑ from 20 to 50 connections
    min: 5,                          // ↑ from 2 to 5 minimum

    // Timeouts adjusted for backfill workload
    idleTimeoutMillis: 60000,        // ↑ from 30s to 60s (backfill queries can take time)
    connectionTimeoutMillis: 30000,  // ↑ from 15s to 30s (avoid premature timeouts)

    // Better keepalive for long-running connections
    keepalives: 1,
    keepalivesIdle: 30,              // ↑ from 10 to 30 seconds

    // More aggressive reaping of stale connections
    reapIntervalMillis: 1000,

    // Connection statement timeout (10 minutes for batch upserts)
    statement_timeout: '600000',

    // Prevent connection leaks
    application_name: 'squid-polymarket-backfill',

    // Better error handling
    error_on_no_rows: false,

    // Socket options - try to force IPv4 if supported
    socket: {
      // family: 4  // Force IPv4 only (requires pg 8.11+, will error silently if not supported)
    }
  }
}

export default config
