#!/usr/bin/env python3
"""
Update Railway DATABASE_URL with new Supabase password
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


def update_railway_password():
    """Update DATABASE_URL in Railway with new password"""
    
    # New password that works
    new_password = "ClDSK0N5IedorZes"
    
    # Correct URL template with new password
    correct_url = f"postgresql://postgres.xxzdlbwfyetaxcmodiec:{new_password}@aws-1-eu-north-1.pooler.supabase.com:5432/postgres"
    
    print("🔧 Updating Railway DATABASE_URL with NEW password...")
    print(f"   Password: {new_password}")
    print(f"   Full URL: {correct_url}")
    print()

    services = ['polycool-api', 'polycool-bot', 'polycool-workers', 'polycool-indexer']

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

    print(f"\n✅ Updated {success_count}/{len(services)} services")
    
    if success_count == len(services):
        print("\n🚀 Next: Run 'railway up' to redeploy with new password")
        print("   This should fix the 'Tenant or user not found' errors")
    else:
        print("\n⚠️  Some services failed to update. Try manually or check Railway CLI.")


if __name__ == "__main__":
    update_railway_password()
