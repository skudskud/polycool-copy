"""
Rebuild subsquid_user_transactions table from scratch.
Kills blocking connections first, then drops and recreates.
"""

import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()


async def rebuild():
    """Rebuild the table"""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL not set")
        return

    print("🔌 Connecting...")
    conn = await asyncpg.connect(database_url)

    try:
        # Kill blocking connections to subsquid_user_transactions
        print("🔪 Killing blocking connections...")
        await conn.execute("""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND query LIKE '%subsquid_user_transactions%';
        """)

        # Wait a bit
        await asyncio.sleep(1)

        # Drop table
        print("🗑️  Dropping old table...")
        await conn.execute("DROP TABLE IF EXISTS subsquid_user_transactions CASCADE;")

        # Wait a bit
        await asyncio.sleep(1)

        # Recreate table
        print("🏗️  Recreating table with new schema...")
        await conn.execute("""
        CREATE TABLE subsquid_user_transactions (
            id TEXT PRIMARY KEY,
            tx_id TEXT UNIQUE NOT NULL,
            user_address TEXT NOT NULL,
            position_id TEXT,
            market_id TEXT NOT NULL,
            outcome INTEGER NOT NULL,
            tx_type TEXT NOT NULL,
            amount NUMERIC(18,8) NOT NULL,
            price NUMERIC(8,4),
            amount_in_usdc NUMERIC(20,8) NOT NULL,
            tx_hash TEXT NOT NULL,
            block_number BIGINT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        # Create indexes
        print("📑 Creating indexes...")
        await conn.execute("""
        CREATE INDEX idx_subsquid_user_transactions_user_address_ts
            ON subsquid_user_transactions(user_address, timestamp DESC);
        """)

        await conn.execute("""
        CREATE INDEX idx_subsquid_user_transactions_market_id_ts
            ON subsquid_user_transactions(market_id, timestamp DESC);
        """)

        print("✅ Table recreated successfully!")

        # Verify
        result = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM subsquid_user_transactions"
        )
        print(f"✨ New table has {result['cnt']} rows (should be 0)")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(rebuild())
