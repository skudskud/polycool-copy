-- Copy Trading External Leaders Cache - Database Migration
-- Date: 2025-10-21
-- Creates external_leaders table for caching traders found via CLOB API

-- TABLE: external_leaders
-- Caches external traders (not in our users table) who are found via CLOB API
-- Used for Tier 3 address resolution in copy trading
CREATE TABLE IF NOT EXISTS external_leaders (
    id SERIAL PRIMARY KEY,
    virtual_id BIGINT NOT NULL UNIQUE,
    polygon_address VARCHAR(42) NOT NULL UNIQUE,
    last_trade_id VARCHAR(255) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_poll_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT polygon_address_format CHECK (polygon_address ~ '^0x'),
    CONSTRAINT virtual_id_negative CHECK (virtual_id < 0)
);

-- Indexes for fast lookups
CREATE INDEX idx_external_leaders_address ON external_leaders(polygon_address);
CREATE INDEX idx_external_leaders_active ON external_leaders(is_active);
CREATE INDEX idx_external_leaders_virtual_id ON external_leaders(virtual_id);
CREATE INDEX idx_external_leaders_last_poll ON external_leaders(last_poll_at) WHERE is_active = TRUE;

-- COMMENTS FOR DOCUMENTATION
COMMENT ON TABLE external_leaders IS 'Caches external traders found via CLOB API for copy trading address resolution (Tier 3)';
COMMENT ON COLUMN external_leaders.virtual_id IS 'Negative hash-based ID for virtual representation of external traders';
COMMENT ON COLUMN external_leaders.polygon_address IS 'Polygon wallet address of external trader';
COMMENT ON COLUMN external_leaders.is_active IS 'Whether this trader still has active trades on CLOB';
COMMENT ON COLUMN external_leaders.last_poll_at IS 'Last time we validated this trader exists on CLOB API';
