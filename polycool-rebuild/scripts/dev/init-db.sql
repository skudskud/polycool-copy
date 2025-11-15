-- Polycool Development Database Initialization
-- This script runs when the PostgreSQL container starts

-- Create polycool user (only if not exists)
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'polycool') THEN
      CREATE USER polycool WITH PASSWORD 'polycool2025';
   END IF;
END
$$;

-- Create development database if it doesn't exist
-- (Note: This is handled by POSTGRES_DB env var in docker-compose.yml)

-- Grant permissions on the database
GRANT ALL PRIVILEGES ON DATABASE polycool_dev TO polycool;

-- Set timezone
SET timezone = 'UTC';

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create polycool schema
CREATE SCHEMA IF NOT EXISTS polycool;

-- Grant permissions
GRANT ALL PRIVILEGES ON SCHEMA polycool TO polycool;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA polycool TO polycool;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA polycool TO polycool;

-- Set search path
SET search_path TO polycool, public;

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE 'Polycool development database initialized successfully';
END $$;
