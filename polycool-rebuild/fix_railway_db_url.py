#!/usr/bin/env python3
"""
Fix Railway DATABASE_URL for Supabase compatibility
"""
import os
import subprocess
import sys


def run_cmd(cmd: str) -> str:
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def get_railway_variables(service: str) -> dict:
    """Get Railway variables for a service"""
    cmd = f"railway variables --service {service}"
    stdout, stderr, code = run_cmd(cmd)

    if code != 0:
        print(f"❌ Failed to get variables for {service}: {stderr}")
        return {}

    variables = {}
    for line in stdout.split('\n'):
        if '=' in line:
            key, value = line.split('=', 1)
            variables[key.strip()] = value.strip()

    return variables


def fix_database_url():
    """Fix DATABASE_URL format for Supabase compatibility"""

    print("🔧 Checking Railway DATABASE_URL configuration...")

    services = ['polycool-api', 'polycool-bot', 'polycool-workers']

    for service in services:
        print(f"\n📡 Checking {service}...")

        # Get current variables
        vars_dict = get_railway_variables(service)
        current_url = vars_dict.get('DATABASE_URL', '')

        if not current_url:
            print(f"   ⚠️  No DATABASE_URL found for {service}")
            continue

        print(f"   Current: {current_url[:60]}...")

        # Check if it's using the wrong format
        if current_url.startswith('postgresql://postgres@') and 'pooler.supabase.com' in current_url:
            print("   ❌ WRONG FORMAT: Using 'postgres@' instead of 'postgres.PROJECT_REF@'")

            # Extract components
            # Format: postgresql://postgres:PASSWORD@aws-1-eu-north-1.pooler.supabase.com:5432/postgres
            try:
                # Split to get password and host
                prefix = 'postgresql://postgres:'
                suffix_start = current_url.find('@')
                if suffix_start == -1:
                    print("   ❌ Could not parse URL format")
                    continue

                password_and_host = current_url[suffix_start + 1:]  # Everything after 'postgres:'
                password_end = password_and_host.find('@')
                if password_end == -1:
                    print("   ❌ Could not parse password")
                    continue

                password = password_and_host[:password_end]
                host_and_db = password_and_host[password_end + 1:]  # Everything after password

                # Create correct URL with project ref
                correct_url = f'postgresql://postgres.xxzdlbwfyetaxcmodiec:{password}@{host_and_db}'

                print(f"   ✅ FIXED: {correct_url[:60]}...")

                # Set the corrected URL
                cmd = f'railway variables --service {service} --set "DATABASE_URL={correct_url}"'
                stdout, stderr, code = run_cmd(cmd)

                if code == 0:
                    print(f"   ✅ Updated {service} DATABASE_URL")
                else:
                    print(f"   ❌ Failed to update {service}: {stderr}")

            except Exception as e:
                print(f"   ❌ Error parsing URL: {e}")

        elif current_url.startswith('postgresql://postgres.xxzdlbwfyetaxcmodiec@'):
            print("   ✅ Already using correct format")
        else:
            print("   ℹ️  Not a Supabase pooler URL, skipping")


def main():
    """Main function"""
    print("🚀 Polycool Railway DATABASE_URL Fixer")
    print("=" * 50)

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

    fix_database_url()

    print("\n✅ Fix complete!")
    print("\nNext steps:")
    print("1. Redeploy your services: railway up")
    print("2. Check logs for connection success")
    print("3. Run diagnostic: python diagnose_db_connection.py")


if __name__ == "__main__":
    main()
