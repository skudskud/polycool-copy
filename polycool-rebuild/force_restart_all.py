#!/usr/bin/env python3
"""
Force restart all Railway services to apply new DATABASE_URL
"""
import subprocess
import sys
import time


def run_cmd(cmd: str) -> tuple[str, str, int]:
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def force_restart_service(service: str):
    """Force restart a Railway service by triggering a redeploy"""
    print(f"\n🔄 Triggering restart for {service}...")
    
    # Method 1: Try to trigger redeploy by touching a file or using railway up
    # Since we can't directly restart, we'll trigger a redeploy
    cmd = f"railway up --service {service}"
    stdout, stderr, code = run_cmd(cmd)
    
    if code == 0:
        print(f"   ✅ Redeploy triggered for {service}")
        return True
    else:
        print(f"   ⚠️  Could not trigger redeploy for {service}: {stderr[:100]}")
        print("   Try restarting manually in Railway dashboard")
        return False


def main():
    """Main function"""
    print("🚀 Force Restart All Railway Services")
    print("=" * 45)
    print("This will redeploy all services to apply new DATABASE_URL")
    print()
    
    services = ['polycool-api', 'polycool-bot', 'polycool-workers', 'polycool-indexer']
    
    success_count = 0
    
    for service in services:
        if force_restart_service(service):
            success_count += 1
        time.sleep(5)  # Wait between services
    
    print(f"\n✅ Redeploy triggered for {success_count}/{len(services)} services")
    print("\n⏳ Services will restart with new DATABASE_URL")
    print("   Check logs in ~2-3 minutes:")
    print("   railway logs polycool-workers --follow")
    
    if success_count < len(services):
        print("\n⚠️  Some services may need manual restart in Railway dashboard")


if __name__ == "__main__":
    main()
