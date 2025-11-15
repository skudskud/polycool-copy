#!/usr/bin/env python3
"""
Update Railway DATABASE_URL to include ?pgbouncer=true for Supabase transaction pooling
This fixes "Tenant or user not found" errors caused by prepared statement conflicts
"""
import subprocess
import sys


def run_cmd(cmd: str) -> tuple[str, str, int]:
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def update_railway_pgbouncer():
    """Update DATABASE_URL in Railway to include ?pgbouncer=true"""

    # Current password
    password = "ClDSK0N5IedorZes"

    # Correct URL with pgbouncer=true for transaction pooling (port 6543)
    # This tells asyncpg to disable prepared statements for PgBouncer compatibility
    correct_url = f"postgresql://postgres.xxzdlbwfyetaxcmodiec:{password}@aws-1-eu-north-1.pooler.supabase.com:6543/postgres?pgbouncer=true"

    print("🔧 Updating Railway DATABASE_URL with ?pgbouncer=true parameter...")
    print(f"   This fixes prepared statement errors with PgBouncer transaction pooling")
    print(f"   Full URL: {correct_url.replace(password, '***')}")
    print()

    # Only update services that use the database
    services = ['polycool-api', 'polycool-workers']

    # Note: polycool-bot has SKIP_DB=true, so it doesn't need this
    # polycool-indexer uses TypeORM which handles PgBouncer differently

    success_count = 0

    for service in services:
        print(f"📡 Updating {service}...")

        # Update DATABASE_URL
        cmd = f'railway variables --service {service} --set "DATABASE_URL={correct_url}"'
        stdout, stderr, code = run_cmd(cmd)

        if code == 0:
            print(f"   ✅ Updated {service}")
            success_count += 1
        else:
            print(f"   ❌ Failed to update {service}: {stderr}")
            print(f"   💡 Try manually: railway variables --service {service} --set 'DATABASE_URL={correct_url}'")

    print(f"\n✅ Updated {success_count}/{len(services)} services")

    if success_count == len(services):
        print("\n🚀 Next steps:")
        print("   1. Services will auto-redeploy with new DATABASE_URL")
        print("   2. Check logs to verify no more 'prepared statement already exists' errors")
        print("   3. Verify API webhooks and worker upserts work correctly")
    else:
        print("\n⚠️  Some services failed to update. Try manually:")
        for service in services:
            print(f"   railway variables --service {service} --set 'DATABASE_URL={correct_url}'")


if __name__ == "__main__":
    update_railway_pgbouncer()
