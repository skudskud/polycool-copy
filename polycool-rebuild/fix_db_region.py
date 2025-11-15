#!/usr/bin/env python3
"""
Fix Railway DATABASE_URL to use correct Supabase region and password
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


def fix_database_urls():
    """Fix DATABASE_URL for all services to use aws-1 region and correct password"""

    # Correct URL template (using aws-1 region)
    correct_url = "postgresql://postgres.xxzdlbwfyetaxcmodiec:ClDSK0N5IedorZes@aws-1-eu-north-1.pooler.supabase.com:5432/postgres"

    print("🔧 Fixing Railway DATABASE_URL password (region aws-1 is correct)...")
    print(f"   Target URL: {correct_url}")
    print()

    services = ['polycool-api', 'polycool-bot', 'polycool-workers']

    for service in services:
        print(f"📡 Updating {service}...")

        # Set the correct DATABASE_URL
        cmd = f'railway variables --service {service} --set "DATABASE_URL={correct_url}"'
        stdout, stderr, code = run_cmd(cmd)

        if code == 0:
            print(f"   ✅ Updated {service}")
        else:
            print(f"   ❌ Failed to update {service}: {stderr}")


def main():
    """Main function"""
    print("🚀 Polycool Database Region Fix")
    print("=" * 40)

    # Check if railway CLI is available
    stdout, stderr, code = run_cmd("railway --version")
    if code != 0:
        print("❌ Railway CLI not found. Please install it first:")
        print("   curl -fsSL https://railway.app/install.sh | sh")
        sys.exit(1)

    # Check if logged in
    stdout, stderr, code = run_cmd("railway whoami")
    if code != 0:
        print("❌ Not logged in to Railway. Please run:")
        print("   railway login")
        sys.exit(1)

    fix_database_urls()

    print("\n✅ All services updated!")
    print("\nNext steps:")
    print("1. Redeploy: railway up")
    print("2. Check logs for successful connections")
    print("3. Test webhooks: they should work without 'Tenant or user not found' errors")


if __name__ == "__main__":
    main()
