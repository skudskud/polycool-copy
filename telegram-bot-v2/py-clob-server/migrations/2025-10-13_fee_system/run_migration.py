#!/usr/bin/env python3
"""
Fee System Migration Runner
Executes the 3 SQL migration files in order
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import database module
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def run_migration():
    """Execute fee system migration"""
    try:
        import psycopg2
        from dotenv import load_dotenv

        # Load .env file from project root
        env_path = Path(__file__).parent.parent.parent / '.env'
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ Loaded environment from {env_path}")

        # Get DATABASE_URL from environment
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("❌ ERROR: DATABASE_URL environment variable not set")
            print("   Set it with: export DATABASE_URL='postgresql://...'")
            return False

        print("🚀 Starting Fee System Migration")
        print(f"📊 Database: {database_url.split('@')[1] if '@' in database_url else 'localhost'}")
        print()

        # Connect to database
        conn = psycopg2.connect(database_url)
        conn.set_session(autocommit=False)
        cursor = conn.cursor()

        # Migration files in order
        migration_dir = Path(__file__).parent
        migration_files = [
            '001_create_referrals_table.sql',
            '002_create_fees_table.sql',
            '003_create_referral_commissions_table.sql'
        ]

        # Execute each migration
        for i, filename in enumerate(migration_files, 1):
            filepath = migration_dir / filename

            if not filepath.exists():
                print(f"❌ ERROR: Migration file not found: {filename}")
                conn.rollback()
                return False

            print(f"📝 [{i}/3] Executing: {filename}")

            with open(filepath, 'r') as f:
                sql_content = f.read()

            try:
                cursor.execute(sql_content)
                print(f"   ✅ Success")
            except psycopg2.Error as e:
                print(f"   ❌ Failed: {e}")
                conn.rollback()
                cursor.close()
                conn.close()
                return False

        # Commit all changes
        conn.commit()
        print()
        print("✅ All migrations executed successfully!")

        # Verify tables were created
        print()
        print("🔍 Verifying tables...")
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('referrals', 'fees', 'referral_commissions')
            ORDER BY table_name;
        """)

        tables = cursor.fetchall()
        if len(tables) == 3:
            print("   ✅ All 3 tables created:")
            for table in tables:
                print(f"      • {table[0]}")
        else:
            print(f"   ⚠️  Warning: Expected 3 tables, found {len(tables)}")

        # Verify indexes
        cursor.execute("""
            SELECT tablename, COUNT(*) as index_count
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('referrals', 'fees', 'referral_commissions')
            GROUP BY tablename
            ORDER BY tablename;
        """)

        indexes = cursor.fetchall()
        print()
        print("   ✅ Indexes created:")
        for table_name, count in indexes:
            print(f"      • {table_name}: {count} indexes")

        cursor.close()
        conn.close()

        print()
        print("🎉 Migration complete! Fee system ready to use.")
        print()
        print("Next steps:")
        print("1. Deploy updated code to Railway")
        print("2. Test with small trade amounts")
        print("3. Monitor logs for fee collection")
        print("4. Verify transactions on PolygonScan")

        return True

    except ImportError:
        print("❌ ERROR: psycopg2 not installed")
        print("   Install with: pip install psycopg2-binary")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
