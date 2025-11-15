#!/usr/bin/env python3
"""
Check Supabase credentials and connection details
"""
import asyncio
import os
import httpx
from typing import Optional


async def check_supabase_project():
    """Check if the project exists and get connection details"""

    # Extract project ref from current DATABASE_URL
    current_url = os.getenv('DATABASE_URL', '')
    if not current_url:
        print("❌ No DATABASE_URL found")
        return

    # Extract project ref (xxzdlbwfyetaxcmodiec)
    if 'postgres.' in current_url and '@' in current_url:
        project_ref = current_url.split('postgres.')[1].split('@')[0].split(':')[0]
        print(f"📋 Project ref from URL: {project_ref}")
    else:
        print("❌ Could not extract project ref from DATABASE_URL")
        return

    # Try to get project info from Supabase API
    api_url = f"https://api.supabase.com/v1/projects/{project_ref}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # We can't authenticate without API key, but we can try basic info
            response = await client.get(api_url)

            if response.status_code == 401:
                print("🔒 Project exists (authentication required for details)")
                print("   This confirms the project ref is valid")
            elif response.status_code == 404:
                print("❌ Project not found - INVALID PROJECT REF")
                print(f"   The project ref '{project_ref}' does not exist")
                return False
            elif response.status_code == 200:
                print("✅ Project found and accessible")
                data = response.json()
                print(f"   Name: {data.get('name', 'Unknown')}")
                print(f"   Region: {data.get('region', 'Unknown')}")
                print(f"   Status: {data.get('status', 'Unknown')}")
            else:
                print(f"⚠️  Unexpected response: {response.status_code}")

    except Exception as e:
        print(f"❌ Could not check project: {e}")

    return True


async def check_connection_string_format():
    """Check if the connection string format is correct"""

    url = os.getenv('DATABASE_URL', '')
    if not url:
        print("❌ No DATABASE_URL found")
        return

    print("🔍 Analyzing DATABASE_URL format...")

    # Check basic format
    if not url.startswith('postgresql://'):
        print("❌ URL should start with 'postgresql://'")
        return

    # Check user format
    if 'postgres.' not in url:
        print("❌ Username should be 'postgres.PROJECT_REF' format")
        print("   Current format appears to be missing project ref")
        return
    else:
        print("✅ Username format: postgres.PROJECT_REF ✓")

    # Check region
    if 'aws-1-eu-north-1.pooler.supabase.com' in url:
        print("✅ Region: aws-1-eu-north-1 ✓")
    elif 'aws-0-eu-north-1.pooler.supabase.com' in url:
        print("⚠️  Region: aws-0-eu-north-1 (different from expected aws-1)")
    else:
        print("❓ Region: Unknown or custom")

    # Check port
    if ':5432/' in url:
        print("✅ Port: 5432 (pooled connection) ✓")
    elif ':6543/' in url:
        print("ℹ️  Port: 6543 (direct connection)")
    else:
        print("❓ Port: Unknown")

    print("
📋 Full URL structure:"    print(f"   {url}")
    print()


async def main():
    """Main function"""
    print("🔍 Supabase Credentials Checker")
    print("=" * 40)

    await check_connection_string_format()
    await check_supabase_project()

    print("\n💡 If you still get 'Tenant or user not found':")
    print("   1. Check your Supabase dashboard → Settings → Database")
    print("   2. Verify the connection string EXACTLY matches")
    print("   3. Make sure you're using the POOLER connection (not direct)")
    print("   4. Try resetting the password if needed")


if __name__ == "__main__":
    asyncio.run(main())
