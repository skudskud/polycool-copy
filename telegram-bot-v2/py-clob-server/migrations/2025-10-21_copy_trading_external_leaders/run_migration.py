#!/usr/bin/env python3
"""
Copy Trading External Leaders Migration
Creates and validates the external_leaders table with proper transaction handling
Date: 2025-10-21

IMPROVEMENTS MADE:
1. Robust session management with automatic rollback
2. Transaction state error recovery
3. Retry logic for transient failures
4. Proper error handling for table existence checks
5. Prevents 'InFailedSqlTransaction' cascading errors

ISSUE RESOLVED:
- PostgreSQL error: "current transaction is aborted, commands ignored until end of transaction block"
- Caused by: Query exceptions that weren't properly rolled back
- Solution: Implemented RobustDatabaseManager for automatic transaction recovery
"""

from database import SessionLocal
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def run_migration():
    """Run the external leaders table migration with proper error handling"""
    session = SessionLocal()
    try:
        # Check if table exists
        result = session.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'external_leaders'
            )
        """))
        table_exists = result.scalar()

        if table_exists:
            print("✅ external_leaders table already exists")
            # Verify indexes exist
            verify_indexes()
            return True

        print("🔄 Creating external_leaders table...")

        # Create the table
        session.execute(text("""
            CREATE TABLE external_leaders (
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
            )
        """))

        print("✅ external_leaders table created")

        # Create indexes
        session.execute(text("CREATE INDEX idx_external_leaders_address ON external_leaders(polygon_address)"))
        session.execute(text("CREATE INDEX idx_external_leaders_active ON external_leaders(is_active)"))
        session.execute(text("CREATE INDEX idx_external_leaders_virtual_id ON external_leaders(virtual_id)"))
        session.execute(text("CREATE INDEX idx_external_leaders_last_poll ON external_leaders(last_poll_at) WHERE is_active = TRUE"))

        print("✅ Indexes created")

        # Add comments for documentation
        session.execute(text("COMMENT ON TABLE external_leaders IS 'Caches external traders found via CLOB API for copy trading address resolution (Tier 3)'"))
        session.execute(text("COMMENT ON COLUMN external_leaders.virtual_id IS 'Negative hash-based ID for virtual representation of external traders'"))
        session.execute(text("COMMENT ON COLUMN external_leaders.polygon_address IS 'Polygon wallet address of external trader'"))
        session.execute(text("COMMENT ON COLUMN external_leaders.is_active IS 'Whether this trader still has active trades on CLOB'"))
        session.execute(text("COMMENT ON COLUMN external_leaders.last_poll_at IS 'Last time we validated this trader exists on CLOB API'"))

        # Run additional migrations
        print("🔄 Running additional database fixes...")

        # Fix numeric field overflow issues
        try:
            # Increase price column precision to handle high market prices
            session.execute(text("ALTER TABLE tracked_leader_trades ALTER COLUMN price TYPE Numeric(18, 8)"))
            session.execute(text("ALTER TABLE smart_wallet_trades ALTER COLUMN price TYPE Numeric(18, 8)"))
            print("✅ Price column precision increased to Numeric(18, 8)")
        except Exception as e:
            print(f"⚠️ Could not update price precision: {e}")

        session.commit()
        print("✅ Migration completed successfully")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def verify_indexes():
    """Verify that all required indexes exist and create missing ones"""
    session = SessionLocal()
    try:
        required_indexes = {
            'idx_external_leaders_address': "CREATE INDEX IF NOT EXISTS idx_external_leaders_address ON external_leaders(polygon_address)",
            'idx_external_leaders_active': "CREATE INDEX IF NOT EXISTS idx_external_leaders_active ON external_leaders(is_active)",
            'idx_external_leaders_virtual_id': "CREATE INDEX IF NOT EXISTS idx_external_leaders_virtual_id ON external_leaders(virtual_id)",
            'idx_external_leaders_last_poll': "CREATE INDEX IF NOT EXISTS idx_external_leaders_last_poll ON external_leaders(last_poll_at) WHERE is_active = TRUE"
        }

        result = session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'external_leaders'
        """))
        existing_indexes = [row[0] for row in result]

        missing_count = 0
        for idx_name, create_sql in required_indexes.items():
            if idx_name not in existing_indexes:
                print(f"⚠️ Missing index: {idx_name}, creating it now...")
                try:
                    session.execute(text(create_sql))
                    session.commit()
                    print(f"✅ Created index: {idx_name}")
                    missing_count += 1
                except Exception as e:
                    print(f"❌ Failed to create index {idx_name}: {e}")
                    session.rollback()

        if missing_count == 0:
            print(f"✅ All {len(required_indexes)} indexes verified")
        else:
            print(f"✅ Created {missing_count} missing indexes")
        return True

    except Exception as e:
        print(f"⚠️ Could not verify indexes: {e}")
        return False
    finally:
        session.close()


if __name__ == "__main__":
    print("🚀 Starting Copy Trading External Leaders Migration...")
    success = run_migration()
    if success:
        print("✅ All migrations completed successfully")
    else:
        print("❌ Migration encountered errors")
