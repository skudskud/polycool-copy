#!/usr/bin/env python3
"""
DB Connection Diagnostic Script
Diagnoses Supabase connection issues for Railway deployment
"""
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


async def diagnose_db_connection():
    """Test database connection and diagnose issues"""

    # Get database URL
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not found in environment")
        return False

    print(f"🔍 Testing connection to: {db_url[:50]}...")

    # Check URL format
    if 'pooler.supabase.com' in db_url:
        print("✅ Using Supabase pooler URL")

        # Check username format
        if db_url.startswith('postgresql://postgres.') and '.supabase.com' in db_url:
            print("✅ Correct Supabase username format (postgres.PROJECT_REF)")
        elif db_url.startswith('postgresql://postgres@') and '.supabase.com' in db_url:
            print("⚠️  WARNING: Using 'postgres@' instead of 'postgres.PROJECT_REF@'")
            print("   This may cause 'Tenant or user not found' errors")
        else:
            print("❓ Unknown username format in pooler URL")
    else:
        print("ℹ️  Not using Supabase pooler URL")

    # Test connection
    try:
        # Create engine with same settings as production
        engine_kwargs = {
            "echo": False,
        }

        if db_url.startswith("postgresql"):
            engine_kwargs["connect_args"] = {
                "ssl": "require",
                "server_settings": {
                    "application_name": "polycool_diagnostic"
                },
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
                "command_timeout": 30,
            }

        engine = create_async_engine(db_url, **engine_kwargs)

        async with engine.begin() as conn:
            # Test basic connectivity
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Connected successfully")
            print(f"   PostgreSQL version: {version[:50]}...")

            # Test Supabase-specific queries
            try:
                result = await conn.execute(text("SELECT current_database(), current_user"))
                db_name, user_name = result.fetchone()
                print(f"✅ Database: {db_name}, User: {user_name}")
            except Exception as e:
                print(f"⚠️  Could not get database info: {e}")

            # Test table access
            try:
                result = await conn.execute(text("SELECT COUNT(*) FROM trades"))
                trade_count = result.scalar()
                print(f"✅ Trades table accessible: {trade_count} records")
            except Exception as e:
                print(f"⚠️  Could not access trades table: {e}")

        await engine.dispose()
        return True

    except Exception as e:
        error_msg = str(e).lower()
        print(f"❌ Connection failed: {e}")

        # Analyze error
        if 'tenant or user not found' in error_msg:
            print("\n🔧 SUPABASE ERROR ANALYSIS:")
            print("   This error typically means:")
            print("   1. Wrong username format in DATABASE_URL")
            print("   2. Project reference missing from username")
            print("   3. Database URL points to wrong project")
            print("\n   SOLUTION: Use format postgresql://postgres.PROJECT_REF:PASSWORD@HOST:PORT/DB")
            print("   Example: postgresql://postgres.xxzdlbwfyetaxcmodiec:PWD@aws-1-eu-north-1.pooler.supabase.com:5432/postgres")

        elif 'authentication failed' in error_msg:
            print("\n🔧 AUTHENTICATION ERROR:")
            print("   Password or username is incorrect")

        elif 'connection timed out' in error_msg:
            print("\n🔧 TIMEOUT ERROR:")
            print("   Database is unreachable or overloaded")

        elif 'ssl' in error_msg:
            print("\n🔧 SSL ERROR:")
            print("   SSL configuration issue with Supabase")

        return False


if __name__ == "__main__":
    print("🩺 Polycool Database Connection Diagnostic")
    print("=" * 50)

    success = asyncio.run(diagnose_db_connection())

    if success:
        print("\n✅ Database connection is working")
    else:
        print("\n❌ Database connection failed - check Railway variables")
        print("\nTo fix Railway DATABASE_URL:")
        print("railway variables --service polycool-api")
        print("# Check if DATABASE_URL uses correct Supabase format")
        print("# Should be: postgresql://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres")
